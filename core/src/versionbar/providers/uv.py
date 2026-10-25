r"""uv: the Python installs it manages, found by asking `uv python list`.

Only installed Pythons are asked for (`--only-installed`), never the catalog
of downloadable ones. uv names one managed Python several times: the install
itself, its launcher in the user's bin folder and a minor-version link folder.
Only the install is reported; the others are the same files under another name.
Entries that uv found elsewhere (PATH, the registry) are not uv's installs and
are left to PATH and the launcher.
"""

import json
import ntpath

from versionbar.provider import Located, Provider
from versionbar.system import System
from versionbar.system.resolve import path_hits

# --no-config: a uv.toml or pyproject.toml in the working directory (a
# python-preference, say) must not change which installed Pythons are listed.
_LIST_ARGS = ["python", "list", "--no-config", "--only-installed", "--output-format", "json"]


class Uv(Provider):
    id = "uv"
    name = "uv"
    # The only listing captured so far is from Windows (hard rule 4).
    os = ("windows",)
    tools = ("python",)

    def locate(self, system: System, tool: str, timeout: float) -> Located:
        uv = _find_uv(system)
        if uv is None:
            return Located()
        process = system.run([uv, *_LIST_ARGS], timeout)
        if process.launch_error is not None:
            raise RuntimeError(f"could not run {uv}: {process.launch_error}")
        if process.timed_out:
            raise RuntimeError(f"uv python list did not answer within {timeout:g} s")
        if process.exit_code != 0:
            raise RuntimeError(f"uv python list exited with code {process.exit_code}")
        try:
            entries = json.loads(process.stdout)
            executables = list(dict.fromkeys(_managed_paths(entries)))
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise RuntimeError(
                f"uv python list printed something unexpected ({error!r})"
            ) from error
        return Located(executables)


def _find_uv(system: System) -> str | None:
    # What typing `uv` runs, then the folder the installer was told to use.
    # No fixed default folder: managers are found through the environment.
    on_path = next(iter(path_hits(system, "uv")), None)
    if on_path is not None:
        return on_path
    folder = (system.getenv("UV_INSTALL_DIR") or "").strip().strip('"')
    if folder and ntpath.isabs(folder):
        candidate = ntpath.join(ntpath.normpath(folder), "uv.exe")
        if system.is_executable(candidate):
            return candidate
    return None


def _managed_paths(entries: list[dict]) -> list[str]:
    """Paths of the entries that sit in the folder uv names after their key."""
    paths = []
    for entry in entries:
        path = entry["path"]
        # A managed install is `<python dir>\<key>\python.exe`; its launcher
        # and the minor-version link folder have other names.
        if ntpath.basename(ntpath.dirname(path)) == entry["key"]:
            paths.append(path)
    return paths
