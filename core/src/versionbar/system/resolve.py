"""Executable resolution: which file runs when a command name is typed.

Written against the `System` primitives (environment, executable check) rather
than inside the real system, so the PATH/PATHEXT rules themselves run under the
fake in tests. Path joining follows the target OS, not the OS running the code,
so Windows rules are exercised on Linux CI too.
"""

import ntpath
import posixpath
from collections.abc import Callable, Iterator

from versionbar.system import System

# What cmd.exe falls back to when PATHEXT is unset.
_DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD"


def path_hits(system: System, command: str) -> Iterator[str]:
    """Yield every PATH match for `command`, in the order the OS would try them.

    A binary reached through several PATH entries is yielded once, at its first
    position. Candidates are normalised before the executable check (so `.`, `..`
    and repeated separators never reach the system), and equality is then only
    case on Windows. Symlinks are not resolved: that would need the machine.
    """
    if system.os == "windows":
        hits = _windows_hits(system, command)
        fold = ntpath.normcase
    else:
        hits = _posix_hits(system, command)
        fold = str
    # The launcher's folders are not part of the PATH the user typed into.
    # Compared after the same normalisation as hits, so any spelling matches.
    paths = ntpath if system.os == "windows" else posixpath
    runtime = {fold(paths.normpath(directory)) for directory in system.runtime_dirs}
    seen: set[str] = set()
    for hit in hits:
        key = fold(hit)
        if fold(paths.dirname(hit)) in runtime:
            continue
        if key not in seen:
            seen.add(key)
            yield hit


# App Installer redirectors that stand in for an app until it is installed: run,
# they open the Microsoft Store (or print a pointer to it and exit 9009). Keyed
# by application user model id because the same package also ships real tools
# (`winget`). Only the Python redirector has been observed; add others here
# once seen on a real machine.
_STORE_PLACEHOLDERS = frozenset({"Microsoft.DesktopAppInstaller_8wekyb3d8bbwe!PythonRedirector"})


def is_store_placeholder(system: System, path: str) -> bool:
    """Whether `path` is a Microsoft Store placeholder rather than an install.

    Decided from the alias data alone, so the placeholder itself never runs.
    """
    alias = system.app_execution_alias(path)
    return alias is not None and alias.app_user_model_id in _STORE_PLACEHOLDERS


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
    for directory in _entries(system.getenv("PATH"), ";", ntpath.isabs):
        for name in names:
            candidate = ntpath.normpath(ntpath.join(directory, name))
            if system.is_executable(candidate):
                yield candidate


def _posix_hits(system: System, command: str) -> Iterator[str]:
    for directory in _entries(system.getenv("PATH"), ":", posixpath.isabs):
        candidate = posixpath.normpath(posixpath.join(directory, command))
        if system.is_executable(candidate):
            yield candidate


def _entries(path: str | None, separator: str, is_absolute: Callable[[str], bool]) -> Iterator[str]:
    # Empty entries and relative ones (`.`, `..\bin`, `bin`) mean "relative to
    # the current directory" to a shell. A scan has no meaningful cwd, and
    # reporting such a hit would give a bare name that is not the file that
    # was detected, so they are skipped.
    for entry in (path or "").split(separator):
        entry = entry.strip().strip('"')
        if entry and is_absolute(entry):
            yield entry
