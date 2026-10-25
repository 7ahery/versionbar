r"""rustup: the Rust toolchains it holds, found by asking `rustup toolchain list -v`.

Each toolchain is a folder with its own `bin\rustc.exe` and `bin\cargo.exe`;
those are the installs, not the proxies in `~\.cargo\bin` that PATH finds and
that follow whichever toolchain is selected. rustup's own folder rules
(`RUSTUP_HOME`, `CARGO_HOME`, overrides) apply because rustup answers, not
VersionBar. `toolchain list` only reads what is installed: it never installs or
switches a toolchain, so the `rust-toolchain.toml` auto-install that running a
proxy can trigger does not apply.
"""

import ntpath
import re

from versionbar.provider import Located, Provider
from versionbar.system import System
from versionbar.system.resolve import path_hits

_LIST_ARGS = ["toolchain", "list", "-v"]
# `<name> [(active, default)] <path>`: the flags are optional and the path may
# contain spaces.
_LINE = re.compile(r"(\S+)(?: \([^)]*\))? +(\S.*)")


class Rustup(Provider):
    id = "rustup"
    name = "rustup"
    # The only listing captured so far is from Windows (hard rule 4).
    os = ("windows",)
    tools = ("rustc", "cargo")

    def locate(self, system: System, tool: str, timeout: float) -> Located:
        rustup = _find_rustup(system)
        if rustup is None:
            return Located()
        process = system.run([rustup, *_LIST_ARGS], timeout)
        if process.launch_error is not None:
            raise RuntimeError(f"could not run {rustup}: {process.launch_error}")
        if process.timed_out:
            raise RuntimeError(f"rustup toolchain list did not answer within {timeout:g} s")
        if process.exit_code != 0:
            raise RuntimeError(f"rustup toolchain list exited with code {process.exit_code}")
        try:
            folders = _toolchain_folders(process.stdout.decode("utf-8"))
        except ValueError as error:
            raise RuntimeError(
                f"rustup toolchain list printed something unexpected ({error})"
            ) from error
        executables: list[str] = []
        notes: list[str] = []
        for folder in folders:
            executable = ntpath.join(folder, "bin", f"{tool}.exe")
            if system.is_executable(executable):
                executables.append(executable)
            else:
                notes.append(f"rustup: {folder} has no bin\\{tool}.exe, so it is not an install")
        return Located(executables, notes)


def _find_rustup(system: System) -> str | None:
    # What typing `rustup` runs, then the folder cargo's installer uses.
    on_path = next(iter(path_hits(system, "rustup")), None)
    if on_path is not None:
        return on_path
    home = (system.getenv("CARGO_HOME") or "").strip().strip('"')
    if not home:
        profile = (system.getenv("USERPROFILE") or "").strip().strip('"')
        home = ntpath.join(profile, ".cargo") if profile else ""
    if not home or not ntpath.isabs(home):
        return None
    candidate = ntpath.join(ntpath.normpath(home), "bin", "rustup.exe")
    return candidate if system.is_executable(candidate) else None


def _toolchain_folders(text: str) -> list[str]:
    folders = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _LINE.fullmatch(line.strip())
        if match is None or not ntpath.isabs(match.group(2)):
            raise ValueError(f"line {line.strip()!r}")
        folders.append(match.group(2))
    return folders
