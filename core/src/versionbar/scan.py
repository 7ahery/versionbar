"""The generic detection engine. It knows nothing about individual tools: all
tool-specific knowledge comes from definitions."""

import ntpath
import re
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from versionbar.decoding import decode_output
from versionbar.definition import ToolDefinition
from versionbar.models import Install, ScanResult, Tool, ToolStatus
from versionbar.system import ProcessResult, System
from versionbar.system.resolve import is_store_placeholder, path_hits

DEFAULT_TIMEOUT_SECONDS = 5.0
# Version commands mostly wait on process start-up, so overlapping them is what
# keeps a full scan near a second. The cap keeps a long PATH from launching
# dozens of processes at once.
MAX_PARALLEL_COMMANDS = 16


def scan(system: System, definitions: list[ToolDefinition]) -> ScanResult:
    applicable = [
        definition.for_os(system.os) for definition in definitions if system.os in definition.os
    ]
    # Every version command of every tool shares one pool, so a slow tool
    # delays nothing else; results are collected in definition order.
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_COMMANDS) as pool:
        jobs = [_submit(pool, system, definition) for definition in applicable]
        tools = [
            _detect(definition, paths, [future.result() for future in futures])
            for definition, paths, futures in jobs
        ]
    return ScanResult(scanned_at=system.now(), platform=system.os, tools=tools)


def _submit(
    pool: ThreadPoolExecutor, system: System, definition: ToolDefinition
) -> tuple[ToolDefinition, _Hits, list[Future[Install | _Failed]]]:
    # Resolution only checks files, so it stays on this thread; a tool's
    # commands start as soon as its paths are known.
    hits = _Hits.of(system, definition.binaries)
    return definition, hits, [pool.submit(_probe, system, definition, path) for path in hits.paths]


def _detect(definition: ToolDefinition, hits: _Hits, probes: list[Install | _Failed]) -> Tool:
    if not hits.paths:
        names = ", ".join(definition.binaries)
        if hits.placeholders:
            first = f"only Microsoft Store placeholders found on PATH (looked for: {names})"
        else:
            first = f"not found on PATH (looked for: {names})"
        return _tool(definition, "missing", notes=[first, *hits.placeholder_notes(definition)])

    # The first hit is what runs when the command is typed. If it cannot
    # report a version the tool is in error; the other installs are dropped
    # because there is no active install to put them beside. (They were probed
    # anyway: waiting for the active result first would double the scan time.)
    active = probes[0]
    if isinstance(active, _Failed):
        return _tool(
            definition, active.status, notes=[active.note, *hits.placeholder_notes(definition)]
        )

    installs = [active]
    notes: list[str] = []
    for other in probes[1:]:
        if isinstance(other, _Failed):
            # Not the active install, so it cannot make the whole tool fail;
            # it stays visible as a note instead of silently vanishing.
            notes.append(other.note)
        else:
            installs.append(other)
    notes += hits.placeholder_notes(definition, active=active.path)
    return _tool(definition, "found", active=active, installs=installs, notes=notes)


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


def _probe(system: System, definition: ToolDefinition, path: str) -> Install | _Failed:
    process = system.run([path, *definition.version_args], DEFAULT_TIMEOUT_SECONDS)
    if process.launch_error is not None:
        return _Failed("error", f"could not run {path}: {process.launch_error}")

    # Even a timed-out command keeps what it printed before it was killed,
    # which is often the best clue to why it hung (a prompt, a warning).
    output = _decode(process).strip()
    if process.timed_out:
        return _failed(
            "timeout", f"{path} did not answer within {DEFAULT_TIMEOUT_SECONDS:g} s", output
        )
    match = re.search(definition.version_regex, output)
    if process.exit_code != 0 or match is None:
        problem = (
            f"exited with code {process.exit_code}"
            if process.exit_code != 0
            else "printed no version"
        )
        return _failed("error", f"{path} {problem}", output)

    return Install(version=match["version"], path=path, source="path", raw=output)


def _failed(status: ToolStatus, message: str, output: str) -> _Failed:
    return _Failed(status, message + (f": {output}" if output else ""))


@dataclass(frozen=True)
class _Hits:
    """A tool's PATH matches, in the order the OS would try them."""

    # Every match, placeholders included, so their PATH position is known.
    ordered: list[str]
    placeholders: frozenset[str]

    @classmethod
    def of(cls, system: System, binaries: list[str]) -> _Hits:
        # Binaries keep their declared order, so an earlier name outranks a later one.
        # Two names can match one file (`git` and `git.exe`); path_hits already
        # normalised the spelling, so exact equality collapses those. Case-folding
        # is not repeated here: it only matters across PATH entries, which
        # path_hits handles per name.
        ordered = list(
            dict.fromkeys(hit for binary in binaries for hit in path_hits(system, binary))
        )
        placeholders = frozenset(hit for hit in ordered if is_store_placeholder(system, hit))
        return cls(ordered, placeholders)

    @property
    def paths(self) -> list[str]:
        """The matches that are real installs, the only ones ever run."""
        return [hit for hit in self.ordered if hit not in self.placeholders]

    def placeholder_notes(self, definition: ToolDefinition, active: str | None = None) -> list[str]:
        notes = []
        for hit in self.ordered:
            if hit not in self.placeholders:
                continue
            note = (
                f"{hit} is a Microsoft Store placeholder, not an install"
                f" (it only offers to install {definition.name} from the Store); it was not run"
            )
            if active is not None and self._shadows(hit, active):
                note += (
                    f", but it comes first on PATH, so typing `{_command_name(hit)}`"
                    f" runs it instead of {active}"
                )
            notes.append(note)
        return notes

    def _shadows(self, placeholder: str, active: str) -> bool:
        # Only a placeholder for the same command name is what typing that
        # command reaches; `python.exe` does not hide a later `python3.exe`.
        same_command = _command_name(placeholder).casefold() == _command_name(active).casefold()
        return same_command and self.ordered.index(placeholder) < self.ordered.index(active)


def _command_name(path: str) -> str:
    return ntpath.splitext(ntpath.basename(path))[0]


def _decode(process: ProcessResult) -> str:
    # Each stream is decoded on its own: a tool may print UTF-16 on one and
    # UTF-8 on the other. Some tools print their version on stderr only.
    parts = (process.stdout, process.stderr)
    return "\n".join(decode_output(part) for part in parts if part)
