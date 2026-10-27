"""The Windows `py` launcher: the Pythons registered with it, found by `py -0p`.

Draft: only `listing()` exists so `debug capture --source py` can record a real
`py -0p` fixture (hard rule 4). Parsing the listing comes after that capture.
"""

from collections.abc import Sequence

from versionbar.provider import Located, Provider
from versionbar.system import System
from versionbar.system.resolve import path_hits


class PyLauncher(Provider):
    id = "py"
    name = "py launcher"
    os = ("windows",)
    tools = ("python",)

    def locate(self, system: System, tool: str, timeout: float) -> Located:
        return Located()

    def listing(self, system: System, tool: str) -> Sequence[str] | None:
        launcher = next(iter(path_hits(system, "py")), None)
        return None if launcher is None else [launcher, "-0p"]
