"""The generic detection engine. It knows nothing about individual tools: all
tool-specific knowledge comes from definitions."""

import re

from versionbar.definition import ToolDefinition
from versionbar.models import Install, ScanResult, Tool
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
    def result(status, active=None, notes=()) -> Tool:
        return Tool(
            id=definition.id,
            name=definition.name,
            status=status,
            active=active,
            installs=[active] if active else [],
            notes=list(notes),
        )

    path = _first_hit(system, definition.binaries)
    if path is None:
        names = ", ".join(definition.binaries)
        return result("missing", notes=[f"not found on PATH (looked for: {names})"])

    process = system.run([path, *definition.version_args], DEFAULT_TIMEOUT_SECONDS)
    if process.timed_out:
        return result(
            "timeout", notes=[f"{path} did not answer within {DEFAULT_TIMEOUT_SECONDS:g} s"]
        )
    if process.launch_error is not None:
        return result("error", notes=[f"could not run {path}: {process.launch_error}"])

    output = _decode(process)
    match = re.search(definition.version_regex, output)
    if process.exit_code != 0 or match is None:
        problem = (
            f"exited with code {process.exit_code}" if process.exit_code else "printed no version"
        )
        captured = output.strip()
        note = f"{path} {problem}" + (f": {captured}" if captured else "")
        return result("error", notes=[note])

    install = Install(version=match["version"], path=path, source="path", raw=output.strip())
    return result("found", active=install)


def _first_hit(system: System, binaries: list[str]) -> str | None:
    for binary in binaries:
        for hit in path_hits(system, binary):
            return hit
    return None


def _decode(process: ProcessResult) -> str:
    # Per-tool encoding detection (UTF-16 for WSL) arrives with ticket 07.
    parts = (process.stdout, process.stderr)
    return "\n".join(part.decode("utf-8", errors="replace") for part in parts if part)
