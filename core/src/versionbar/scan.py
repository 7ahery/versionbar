"""The generic detection engine. It knows nothing about individual tools: all
tool-specific knowledge comes from definitions."""

import re
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from versionbar.attribution import via_for
from versionbar.decoding import decode_output
from versionbar.definition import ToolDefinition
from versionbar.models import Install, ScanResult, Tool, ToolStatus
from versionbar.system import ProcessResult, System
from versionbar.system.resolve import ToolHits

DEFAULT_TIMEOUT_SECONDS = 5.0
# Version commands mostly wait on process start-up, so overlapping them is what
# keeps a full scan near a second. The cap keeps a long PATH from launching
# dozens of processes at once.
MAX_PARALLEL_COMMANDS = 16


def _default_timeout(_tool_id: str) -> float:
    return DEFAULT_TIMEOUT_SECONDS


def scan(
    system: System,
    definitions: list[ToolDefinition],
    timeout_for: Callable[[str], float] = _default_timeout,
) -> ScanResult:
    """Detect every definition that applies to this OS, in the given order.

    `timeout_for` gives each tool's per-command timeout in seconds, by tool id.
    """
    applicable = [
        definition.for_os(system.os) for definition in definitions if system.os in definition.os
    ]
    # Every version command of every tool shares one pool, so a slow tool
    # delays nothing else; results are collected in definition order.
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_COMMANDS) as pool:
        jobs = [
            _submit(pool, system, definition, timeout_for(definition.id))
            for definition in applicable
        ]
        tools = [
            _detect(definition, paths, [future.result() for future in futures])
            for definition, paths, futures in jobs
        ]
    return ScanResult(scanned_at=system.now(), platform=system.os, tools=tools)


def _submit(
    pool: ThreadPoolExecutor, system: System, definition: ToolDefinition, timeout: float
) -> tuple[ToolDefinition, ToolHits, list[Future[Install | _Failed]]]:
    # Resolution only checks files, so it stays on this thread; a tool's
    # commands start as soon as its paths are known.
    hits = ToolHits.of(system, definition.binaries)
    return (
        definition,
        hits,
        [pool.submit(_probe, system, definition, path, timeout) for path in hits.paths],
    )


def _detect(definition: ToolDefinition, hits: ToolHits, probes: list[Install | _Failed]) -> Tool:
    if not hits.paths:
        notes = hits.missing_notes(definition.binaries, definition.name)
        return _tool(definition, "missing", notes=notes)

    # The first hit is what runs when the command is typed. If it cannot
    # report a version the tool is in error; the other installs are dropped
    # because there is no active install to put them beside. (They were probed
    # anyway: waiting for the active result first would double the scan time.)
    active = probes[0]
    if isinstance(active, _Failed):
        return _tool(
            definition, active.status, notes=[active.note, *hits.placeholder_notes(definition.name)]
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
    notes += hits.placeholder_notes(definition.name, active=active.path)
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


def _probe(
    system: System, definition: ToolDefinition, path: str, timeout: float
) -> Install | _Failed:
    process = system.run([path, *definition.version_args], timeout)
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
    return Install(version=match["version"], path=path, source="path", via=via, raw=output)


def _failed(status: ToolStatus, message: str, output: str) -> _Failed:
    return _Failed(status, message + (f": {output}" if output else ""))


def _decode(process: ProcessResult) -> str:
    # Each stream is decoded on its own: a tool may print UTF-16 on one and
    # UTF-8 on the other. Some tools print their version on stderr only.
    parts = (process.stdout, process.stderr)
    return "\n".join(decode_output(part) for part in parts if part)
