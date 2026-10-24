"""Executable resolution: which file runs when a command name is typed.

Written against the `System` primitives (environment, executable check) rather
than inside the real system, so the PATH/PATHEXT rules themselves run under the
fake in tests. Path joining follows the target OS, not the OS running the code,
so Windows rules are exercised on Linux CI too.
"""

import ntpath
import posixpath
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from versionbar.system import System, UnreadableAlias

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
# they open the Microsoft Store (from a terminal they exit with code 9009). Keyed
# by application user model id because the same package also ships real tools
# (`winget`). Only the Python redirector has been observed; add others here
# once seen on a real machine.
_STORE_PLACEHOLDERS = frozenset({"Microsoft.DesktopAppInstaller_8wekyb3d8bbwe!PythonRedirector"})
# The commands those placeholders answer to. An alias with one of these names
# whose data cannot be read is assumed to be a placeholder: wrongly skipping a
# real Python costs a note, wrongly running a placeholder can open the Store.
_STORE_PLACEHOLDER_COMMANDS = frozenset({"python", "python3"})


@dataclass(frozen=True)
class ToolHits:
    """A tool's PATH matches, in the order the OS would try them, with the
    Microsoft Store placeholders among them told apart from real installs."""

    # Every match, placeholders included, so their PATH position is known.
    ordered: list[str]
    # Placeholder path -> why it could not be read, or None if it was.
    placeholders: dict[str, str | None]

    @classmethod
    def of(cls, system: System, binaries: list[str]) -> ToolHits:
        # Binaries keep their declared order, so an earlier name outranks a later one.
        # Two names can match one file (`git` and `git.exe`); path_hits already
        # normalised the spelling, so exact equality collapses those. Case-folding
        # is not repeated here: it only matters across PATH entries, which
        # path_hits handles per name.
        ordered = list(
            dict.fromkeys(hit for binary in binaries for hit in path_hits(system, binary))
        )
        placeholders = {}
        for hit in ordered:
            is_placeholder, unreadable = _store_placeholder(system, hit)
            if is_placeholder:
                placeholders[hit] = unreadable
        return cls(ordered, placeholders)

    @property
    def paths(self) -> list[str]:
        """The matches that are real installs, the only ones ever run."""
        return [hit for hit in self.ordered if hit not in self.placeholders]

    def missing_notes(self, binaries: list[str], tool_name: str) -> list[str]:
        """Why nothing was found, for a tool with no real install on PATH."""
        names = ", ".join(binaries)
        if self.placeholders:
            first = f"only Microsoft Store placeholders found on PATH (looked for: {names})"
        else:
            first = f"not found on PATH (looked for: {names})"
        return [first, *self.placeholder_notes(tool_name)]

    def placeholder_notes(self, tool_name: str, active: str | None = None) -> list[str]:
        notes = []
        for hit in self.ordered:
            if hit not in self.placeholders:
                continue
            unreadable = self.placeholders[hit]
            if unreadable is None:
                note = (
                    f"{hit} is a Microsoft Store placeholder, not an install"
                    f" (it only offers to install {tool_name} from the Store); it was not run"
                )
            else:
                note = (
                    f"{hit} is an App Execution Alias whose data could not be read"
                    f" ({unreadable}), so it is treated as a Microsoft Store placeholder;"
                    " it was not run"
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


def _store_placeholder(system: System, path: str) -> tuple[bool, str | None]:
    # Decided from the alias data alone, so a placeholder itself never runs.
    alias = system.app_execution_alias(path)
    if alias is None:
        return False, None
    if isinstance(alias, UnreadableAlias):
        unreadable = _command_name(path).casefold() in _STORE_PLACEHOLDER_COMMANDS
        return unreadable, alias.reason
    return alias.app_user_model_id in _STORE_PLACEHOLDERS, None


def _command_name(path: str) -> str:
    # Aliases exist only on Windows, so Windows path rules apply.
    return ntpath.splitext(ntpath.basename(path))[0]


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
