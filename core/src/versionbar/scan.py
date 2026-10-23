"""The generic detection engine. It knows nothing about individual tools: all
tool-specific knowledge comes from definitions."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from versionbar.definition import ToolDefinition
from versionbar.models import Install, ScanResult, Tool, ToolStatus
from versionbar.system import ProcessResult, System
from versionbar.system.resolve import path_hits

DEFAULT_TIMEOUT_SECONDS = 5.0


def scan(system: System, definitions: list[ToolDefinition]) -> ScanResult:
    tools = [
        _detect(system, definition.for_os(system.os))
        for definition in definitions
        if system.os in definition.os
    ]
    return ScanResult(scanned_at=system.now(), platform=system.os, tools=tools)


def _detect(system: System, definition: ToolDefinition) -> Tool:
    paths = _all_hits(system, definition.binaries)
    if not paths:
        names = ", ".join(definition.binaries)
        return _tool(definition, "missing", notes=[f"not found on PATH (looked for: {names})"])

    # The first hit is what runs when the command is typed. If it cannot
    # report a version the tool is in error; the other installs are not probed
    # because there is no active install to put them beside.
    active = _probe(system, definition, paths[0])
    if isinstance(active, _Failed):
        return _tool(definition, active.status, notes=[active.note])

    installs = [active]
    notes: list[str] = []
    for path in paths[1:]:
        other = _probe(system, definition, path)
        if isinstance(other, _Failed):
            # Not the active install, so it cannot make the whole tool fail;
            # it stays visible as a note instead of silently vanishing.
            notes.append(other.note)
        else:
            installs.append(other)
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
    if process.timed_out:
        return _Failed("timeout", f"{path} did not answer within {DEFAULT_TIMEOUT_SECONDS:g} s")
    if process.launch_error is not None:
        return _Failed("error", f"could not run {path}: {process.launch_error}")

    output = _decode(process)
    match = re.search(definition.version_regex, output)
    if process.exit_code != 0 or match is None:
        problem = (
            f"exited with code {process.exit_code}"
            if process.exit_code != 0
            else "printed no version"
        )
        captured = output.strip()
        return _Failed("error", f"{path} {problem}" + (f": {captured}" if captured else ""))

    return Install(version=match["version"], path=path, source="path", raw=output.strip())


def _all_hits(system: System, binaries: list[str]) -> list[str]:
    # Binaries keep their declared order, so an earlier name outranks a later one.
    return [hit for binary in binaries for hit in path_hits(system, binary)]


def _decode(process: ProcessResult) -> str:
    # Per-tool encoding detection (UTF-16 for WSL) arrives with ticket 07.
    parts = (process.stdout, process.stderr)
    return "\n".join(part.decode("utf-8", errors="replace") for part in parts if part)
