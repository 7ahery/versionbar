"""Executable resolution: which file runs when a command name is typed.

Written against the `System` primitives (environment, executable check) rather
than inside the real system, so the PATH/PATHEXT rules themselves run under the
fake in tests. Path joining follows the target OS, not the OS running the code,
so Windows rules are exercised on Linux CI too.
"""

import ntpath
import posixpath
from collections.abc import Iterator

from versionbar.system import System

# What cmd.exe falls back to when PATHEXT is unset.
_DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD"


def path_hits(system: System, command: str) -> Iterator[str]:
    """Yield every PATH match for `command`, in the order the OS would try them."""
    if system.os == "windows":
        yield from _windows_hits(system, command)
    else:
        yield from _posix_hits(system, command)


def _windows_hits(system: System, command: str) -> Iterator[str]:
    # Lowercased so reported paths match how the files are normally named on
    # disk (PATHEXT itself is conventionally uppercase).
    extensions = [
        ext.strip().lower()
        for ext in (system.getenv("PATHEXT") or _DEFAULT_PATHEXT).split(";")
        if ext.strip()
    ]
    # A bare name only ever resolves through PATHEXT; extensionless files
    # (such as the shell script beside VS Code's `code.cmd`) are not runnable.
    if ntpath.splitext(command)[1].lower() in extensions:
        names = [command]
    else:
        names = [command + ext for ext in extensions]
    for directory in _entries(system.getenv("PATH"), ";"):
        for name in names:
            candidate = ntpath.join(directory.strip('"'), name)
            if system.is_executable(candidate):
                yield candidate


def _posix_hits(system: System, command: str) -> Iterator[str]:
    for directory in _entries(system.getenv("PATH"), ":"):
        candidate = posixpath.join(directory, command)
        if system.is_executable(candidate):
            yield candidate


def _entries(path: str | None, separator: str) -> Iterator[str]:
    # Empty entries mean "current directory" to a shell; a scan has no
    # meaningful current directory, so they are skipped.
    return (entry for entry in (path or "").split(separator) if entry.strip())
