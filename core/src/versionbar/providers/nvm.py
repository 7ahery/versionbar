r"""nvm-windows: the Node.js versions it holds, found through `NVM_HOME`.

nvm-windows 2 (observed: 2.0.1) keeps each version in
`%NVM_HOME%\installs\v<version>\` and puts its shim folder `%NVM_HOME%\.nodejs`
on PATH, with no `NVM_SYMLINK`. nvm-windows 1 keeps the versions directly in its
root, `NVM_HOME` by default. Both layouts are read. `NVM_SYMLINK` is never
needed: it only names the folder that serves the selected version, and that
folder is found on PATH like any other install.
"""

import ntpath
import re

from versionbar.provider import Located, Provider
from versionbar.system import System

_VERSION_FOLDER = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


class NvmWindows(Provider):
    id = "nvm"
    name = "nvm-windows"
    os = ("windows",)
    tools = ("node",)

    def locate(self, system: System, tool: str, timeout: float) -> Located:
        # Quotes and spaces are how such values commonly arrive from setup
        # scripts; PATH entries are cleaned the same way.
        home = (system.getenv("NVM_HOME") or "").strip().strip('"')
        if not home or not ntpath.isabs(home):
            return Located()
        home = ntpath.normpath(home)
        executables: list[str] = []
        notes: list[str] = []
        for root in (ntpath.join(home, "installs"), home):
            try:
                names = system.list_dir(root)
            except FileNotFoundError, NotADirectoryError:
                # A layout this install does not use, or a stale NVM_HOME left
                # by an uninstall: nothing to report. Other errors propagate
                # and become a note, since the manager is there but unreadable.
                continue
            matches = [(m, name) for name in names if (m := _VERSION_FOLDER.fullmatch(name))]
            # Newest first, comparing numbers: v9 is older than v10.
            matches.sort(
                key=lambda pair: tuple(int(part) for part in pair[0].groups()), reverse=True
            )
            for _, name in matches:
                folder = ntpath.join(root, name)
                executable = ntpath.join(folder, "node.exe")
                if system.is_executable(executable):
                    executables.append(executable)
                else:
                    notes.append(f"nvm-windows: {folder} has no node.exe, so it is not an install")
        return Located(executables, notes)
