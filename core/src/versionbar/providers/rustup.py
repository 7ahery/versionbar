r"""rustup: the Rust toolchains it holds, read from `<RUSTUP_HOME>\toolchains`.

Each toolchain is a folder with its own `bin\rustc.exe` and `bin\cargo.exe`;
those are the installs, not the proxies in `~\.cargo\bin` that PATH finds and
that follow whichever toolchain is selected.

rustup itself is never run. Even `rustup toolchain list` installs the toolchain
pinned by a `rust-toolchain.toml` in the working directory, and VersionBar
never installs anything (hard rule 5). Listing the folder only reads.
"""

import ntpath

from versionbar.provider import Located, Provider
from versionbar.system import System


class Rustup(Provider):
    id = "rustup"
    name = "rustup"
    # The toolchain layout is only confirmed on Windows (hard rule 4).
    os = ("windows",)
    tools = ("rustc", "cargo")

    def locate(self, system: System, tool: str, timeout: float) -> Located:
        home = _rustup_home(system)
        if home is None:
            return Located()
        root = ntpath.join(home, "toolchains")
        try:
            names = system.list_dir(root)
        except FileNotFoundError, NotADirectoryError:
            # No rustup here, or a stale RUSTUP_HOME. Other errors propagate
            # and become a note, since the manager is there but unreadable.
            return Located()
        executables: list[str] = []
        notes: list[str] = []
        for name in sorted(names):
            folder = ntpath.join(root, name)
            executable = ntpath.join(folder, "bin", f"{tool}.exe")
            if system.is_executable(executable):
                executables.append(executable)
            else:
                notes.append(f"rustup: {folder} has no bin\\{tool}.exe, so it is not an install")
        return Located(executables, notes)


def _rustup_home(system: System) -> str | None:
    # rustup never sets RUSTUP_HOME, so most machines rely on its documented
    # default; that is the one fixed location allowed here, derived from the
    # user's profile folder rather than hard-coded.
    home = (system.getenv("RUSTUP_HOME") or "").strip().strip('"')
    if not home:
        profile = (system.getenv("USERPROFILE") or "").strip().strip('"')
        home = ntpath.join(profile, ".rustup") if profile else ""
    if not home or not ntpath.isabs(home):
        return None
    return ntpath.normpath(home)
