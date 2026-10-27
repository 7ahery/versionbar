r""".NET SDKs: every installed SDK, found by asking the host `dotnet --list-sdks`.

All SDKs run through one `dotnet.exe`, so running each one would say nothing
new. The host already names each SDK's exact version and the folder that holds
its version folder, so they are reported as finished installs. Runtime-only
installs never appear in this listing, so they are not reported.
"""

import ntpath
import re
from collections.abc import Sequence

from versionbar.decoding import decode_output
from versionbar.provider import Located, ProvidedInstall, Provider
from versionbar.system import System
from versionbar.system.resolve import path_hits

_LIST_ARGS = ["--list-sdks"]
# `10.0.402 [C:\Program Files\dotnet\sdk]`: version, then the folder that
# contains the SDK's own `<version>` folder.
_LINE = re.compile(r"^(?P<version>\d+\.\d+\.\d+\S*) \[(?P<folder>.+)\]$")


class DotnetSdks(Provider):
    id = "dotnet"
    name = ".NET SDK"
    # Windows only: on Ubuntu /usr/bin/dotnet is a link into /usr/lib/dotnet,
    # which the engine's "under the PATH host" rule cannot see through, so the
    # active SDK would be listed twice.
    os = ("windows",)
    tools = ("dotnet",)

    def locate(self, system: System, tool: str, timeout: float) -> Located:
        argv = self.listing(system, tool)
        if argv is None:
            return Located()
        process = system.run(argv, timeout)
        if process.launch_error is not None:
            raise RuntimeError(f"could not run {argv[0]}: {process.launch_error}")
        if process.timed_out:
            raise RuntimeError(f"dotnet --list-sdks did not answer within {timeout:g} s")
        if process.exit_code != 0:
            raise RuntimeError(f"dotnet --list-sdks exited with code {process.exit_code}")
        return Located(installs=_parse(decode_output(process.stdout)))

    def listing(self, system: System, tool: str) -> Sequence[str] | None:
        host = _find_host(system)
        return None if host is None else [host, *_LIST_ARGS]


def _find_host(system: System) -> str | None:
    # What typing `dotnet` runs, then the host the SDK's own variable names,
    # then the machine-wide install folder the installer documents.
    on_path = next(iter(path_hits(system, "dotnet")), None)
    if on_path is not None:
        return on_path
    for variable, subfolder in (("DOTNET_ROOT", ""), ("ProgramFiles", "dotnet")):
        folder = (system.getenv(variable) or "").strip().strip('"').strip()
        if folder and ntpath.isabs(folder):
            candidate = ntpath.join(ntpath.normpath(folder), subfolder, "dotnet.exe")
            if system.is_executable(candidate):
                return candidate
    return None


def _parse(output: str) -> list[ProvidedInstall]:
    installs = []
    for line in output.splitlines():
        if not line.strip():
            continue
        match = _LINE.match(line.strip())
        if match is None:
            raise RuntimeError(f"dotnet --list-sdks printed something unexpected ({line!r})")
        folder = ntpath.normpath(match["folder"])
        installs.append(ProvidedInstall(match["version"], ntpath.join(folder, match["version"])))
    return installs
