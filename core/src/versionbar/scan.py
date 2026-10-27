"""The generic detection engine. It knows nothing about individual tools: all
tool-specific knowledge comes from definitions."""

import ntpath
import posixpath
import re
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from types import ModuleType

from versionbar.attribution import via_for
from versionbar.decoding import decode_output
from versionbar.definition import ToolDefinition
from versionbar.models import Install, ScanResult, Tool, ToolStatus
from versionbar.provider import Located, Provider
from versionbar.system import ProcessResult, System
from versionbar.system.resolve import ToolHits

# Version commands mostly wait on process start-up, so overlapping them is what
# keeps a full scan near a second. The cap keeps a long PATH from launching
# dozens of processes at once.
MAX_PARALLEL_COMMANDS = 16


def scan(
    system: System,
    definitions: list[ToolDefinition],
    timeout_for: Callable[[str], float],
    providers: Sequence[Provider],
) -> ScanResult:
    """Detect every definition that applies to this OS, in the given order.

    `timeout_for` gives each tool's per-command timeout in seconds, by tool id.
    `providers` add their installs of the tools they declare, after PATH's.
    """
    applicable = [
        definition.for_os(system.os) for definition in definitions if system.os in definition.os
    ]
    usable = [provider for provider in providers if system.os in provider.os]
    # Every version command of every tool shares one pool, so a slow tool
    # delays nothing else; results are collected in definition order.
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_COMMANDS) as pool:
        jobs = [
            _submit(pool, system, definition, timeout_for(definition.id), usable)
            for definition in applicable
        ]
        # Locations are collected in definition order; each tool's provider
        # installs start probing as soon as its own are known, while the PATH
        # commands already submitted keep running.
        for job in jobs:
            job.probe_provided(pool, system)
        tools = [job.detect(system) for job in jobs]
    return ScanResult(scanned_at=system.now(), platform=system.os, tools=tools)


type _Probe = Future[Install | _Failed]


@dataclass
class _Job:
    """One tool's detection: its PATH probes, then what each provider adds."""

    definition: ToolDefinition
    hits: ToolHits
    timeout: float
    path_probes: list[_Probe]
    located: list[tuple[Provider, Future[Located]]]
    # A provider's installs in report order: probes of its executables, and
    # the finished installs it reported itself.
    provided: list[tuple[Provider, _Probe | Install]] = field(default_factory=list)
    provider_notes: list[str] = field(default_factory=list)

    def probe_provided(self, pool: ThreadPoolExecutor, system: System) -> None:
        paths = _paths(system)
        # A PATH hit is already probed as a PATH install, and two providers
        # naming one path report one install: the first finder keeps it.
        seen = {_fold(paths, path) for path in self.hits.ordered}
        for provider, future in self.located:
            try:
                located = future.result()
            except Exception as error:
                # A provider is code reading data it does not control; its
                # failure is that provider's only, never the scan's.
                self.provider_notes.append(f"{provider.name}: could not list installs: {error}")
                continue
            try:
                # Read in full before anything is kept, so a provider that
                # hands back malformed data loses only its own installs. Only
                # the errors bad data raises are caught: an engine bug here
                # must still fail loudly. (Pydantic's ValidationError is a
                # ValueError.)
                executables = [(path, _fold(paths, path)) for path in located.executables]
                finished = [
                    (
                        Install(version=i.version, path=i.path, source=provider.id),
                        _fold(paths, i.path),
                    )
                    for i in located.installs
                ]
                notes = [str(note) for note in located.notes]
            except (TypeError, ValueError, AttributeError) as error:
                self.provider_notes.append(f"{provider.name}: could not list installs: {error}")
                continue
            self.provider_notes.extend(notes)
            for path, key in executables:
                if key in seen:
                    continue
                seen.add(key)
                probe = pool.submit(
                    _probe, system, self.definition, path, self.timeout, provider.id
                )
                self.provided.append((provider, probe))
            for install, key in finished:
                if key in seen:
                    continue
                seen.add(key)
                self.provided.append((provider, install))

    def detect(self, system: System) -> Tool:
        status, active, installs, notes = _from_path(
            self.definition, self.hits, [future.result() for future in self.path_probes]
        )
        on_path = list(installs)
        notes += self.provider_notes
        paths = _paths(system)
        for provider, outcome in self.provided:
            if isinstance(outcome, Install):
                if not _served_by_shim(outcome, provider, on_path) and not _run_by_path_host(
                    outcome, on_path, paths
                ):
                    installs.append(outcome)
                continue
            result = outcome.result()
            if isinstance(result, _Failed):
                notes.append(f"{provider.name}: {result.note}")
            elif not _served_by_shim(result, provider, on_path):
                installs.append(result)
        return _tool(self.definition, status, active=active, installs=installs, notes=notes)


def _paths(system: System) -> ModuleType:
    return ntpath if system.os == "windows" else posixpath


def _fold(paths: ModuleType, path: str) -> str:
    # As PATH hits are compared: normalised, and caseless on Windows.
    return paths.normcase(paths.normpath(path))


def _served_by_shim(install: Install, provider: Provider, on_path: list[Install]) -> bool:
    # A manager's shim on PATH answers with the version it currently serves,
    # which is one of that manager's own installs: one install, not two. The
    # PATH entry is kept, since it is what typing the command runs.
    return any(i.via == provider.id and i.version == install.version for i in on_path)


def _run_by_path_host(install: Install, on_path: list[Install], paths: ModuleType) -> bool:
    # A host on PATH that runs installs kept in its own folder (the .NET host
    # and its SDKs) answers with the version it runs: the reported install of
    # that version there is the same one, and the PATH entry is kept. Only
    # finished installs are matched this way; a probed executable is its own
    # program, told apart by its path alone.
    folded = _fold(paths, install.path)
    return any(
        i.version == install.version
        and folded.startswith(paths.join(_fold(paths, paths.dirname(i.path)), ""))
        for i in on_path
    )


def _submit(
    pool: ThreadPoolExecutor,
    system: System,
    definition: ToolDefinition,
    timeout: float,
    providers: list[Provider],
) -> _Job:
    # Resolution only checks files, so it stays on this thread; a tool's
    # commands start as soon as its paths are known.
    hits = ToolHits.of(system, definition.binaries)
    return _Job(
        definition,
        hits,
        timeout,
        [pool.submit(_probe, system, definition, path, timeout, "path") for path in hits.paths],
        [
            (provider, pool.submit(provider.locate, system, definition.id, timeout))
            for provider in providers
            if definition.id in provider.tools
        ],
    )


def _from_path(
    definition: ToolDefinition, hits: ToolHits, probes: list[Install | _Failed]
) -> tuple[ToolStatus, Install | None, list[Install], list[str]]:
    """Status, active install, installs and notes from PATH alone."""
    if not hits.paths:
        return "missing", None, [], hits.missing_notes(definition.binaries, definition.name)

    # The first hit is what runs when the command is typed. If it cannot
    # report a version the tool is in error; the other PATH installs are
    # dropped because there is no active install to put them beside. (They
    # were probed anyway: waiting for the active result first would double
    # the scan time.)
    active = probes[0]
    if isinstance(active, _Failed):
        return active.status, None, [], [active.note, *hits.placeholder_notes(definition.name)]

    installs = [active]
    notes: list[str] = []
    for other in probes[1:]:
        if isinstance(other, _Failed):
            # Not the active install, so it cannot make the whole tool fail;
            # it stays visible as a note instead of silently vanishing.
            notes.append(other.note)
        else:
            installs.append(other)
    notes += hits.placeholder_notes(definition.name, active=active.path)
    return "found", active, installs, notes


def _tool(
    definition: ToolDefinition,
    status: ToolStatus,
    *,
    active: Install | None = None,
    installs: Sequence[Install] = (),
    notes: Sequence[str] = (),
) -> Tool:
    return Tool(
        id=definition.id,
        name=definition.name,
        status=status,
        active=active,
        installs=list(installs),
        notes=list(notes),
    )


@dataclass(frozen=True)
class _Failed:
    status: ToolStatus
    note: str


def _probe(
    system: System, definition: ToolDefinition, path: str, timeout: float, source: str
) -> Install | _Failed:
    process = system.run([path, *definition.version_args], timeout, definition.env)
    if process.launch_error is not None:
        return _Failed("error", f"could not run {path}: {process.launch_error}")

    # Even a timed-out command keeps what it printed before it was killed,
    # which is often the best clue to why it hung (a prompt, a warning).
    output = _decode(process).strip()
    if process.timed_out:
        return _failed("timeout", f"{path} did not answer within {timeout:g} s", output)
    match = re.search(definition.version_regex, output)
    if process.exit_code != 0 or match is None:
        problem = (
            f"exited with code {process.exit_code}"
            if process.exit_code != 0
            else "printed no version"
        )
        return _failed("error", f"{path} {problem}", output)

    via = via_for(system, definition.via, path)
    return Install(version=match["version"], path=path, source=source, via=via, raw=output)


def _failed(status: ToolStatus, message: str, output: str) -> _Failed:
    return _Failed(status, message + (f": {output}" if output else ""))


def _decode(process: ProcessResult) -> str:
    # Each stream is decoded on its own: a tool may print UTF-16 on one and
    # UTF-8 on the other. Some tools print their version on stderr only.
    parts = (process.stdout, process.stderr)
    return "\n".join(decode_output(part) for part in parts if part)
