"""The Windows `py` launcher: the Pythons registered with it, found by `py -0p`.

`py -0p` prints one line per registered Python: a tag (`-V:3.13`), then the
path of its `python.exe`. A tag line may carry a `*` before the path when the
launcher's default is that Python. A line without a tag, only `*` and a path,
is the Python that is active right now (a virtual environment, say); it is the
`python` that PATH finds, so it is left to PATH. Paths may contain spaces, so
the path is everything after the tag, never a split on whitespace.
"""

import re
from collections.abc import Sequence

from versionbar.provider import Located, Provider
from versionbar.system import System
from versionbar.system.resolve import path_hits

_LIST_ARGS = ["-0p"]
# Newer launchers tag `-V:3.13`; older ones `-3.13-64`. Both start with `-`.
_TAGGED = re.compile(r"^\s*-\S+\s+(?:\*\s+)?(?P<path>\S.*?)\s*$")


class PyLauncher(Provider):
    id = "py"
    name = "py launcher"
    # The only listing captured is from Windows (hard rule 4); the launcher
    # is a Windows program.
    os = ("windows",)
    tools = ("python",)

    def locate(self, system: System, tool: str, timeout: float) -> Located:
        argv = self.listing(system, tool)
        if argv is None:
            return Located()
        process = system.run(argv, timeout)
        if process.launch_error is not None:
            raise RuntimeError(f"could not run {argv[0]}: {process.launch_error}")
        if process.timed_out:
            raise RuntimeError(f"py -0p did not answer within {timeout:g} s")
        if process.exit_code != 0:
            # A launcher with no Python registered exits non-zero on some versions.
            raise RuntimeError(f"py -0p exited with code {process.exit_code}")
        text = process.stdout.decode("utf-8", errors="replace")
        paths = []
        for line in text.splitlines():
            match = _TAGGED.match(line)
            if match is not None:
                paths.append(match.group("path"))
        return Located(list(dict.fromkeys(paths)))

    def listing(self, system: System, tool: str) -> Sequence[str] | None:
        # What typing `py` runs; no fixed folder.
        launcher = next(iter(path_hits(system, "py")), None)
        return None if launcher is None else [launcher, *_LIST_ARGS]
