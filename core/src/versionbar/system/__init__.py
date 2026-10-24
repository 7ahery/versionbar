"""The one interface between the core and the machine (ADR 0004).

Everything outside this package reaches processes, environment variables and
files only through a `System`. Tests inject a fixture-backed fake; real
implementations live behind the platform boundary in `versionbar.system.real`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

# Ids used both for the running machine and in tool definitions' `os` lists.
type OsName = Literal["windows", "linux"]


@dataclass(frozen=True)
class ProcessResult:
    # None when the process never produced an exit status (launch failure or timeout).
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    launch_error: str | None = None


@dataclass(frozen=True)
class AppExecutionAlias:
    """What a Windows App Execution Alias (a zero-byte file in a `WindowsApps`
    folder) launches, read from the file itself without running it."""

    package_family: str
    # The application user model id, `<package family>!<app>`.
    app_user_model_id: str
    target: str


@dataclass(frozen=True)
class UnreadableAlias:
    """A file that is an App Execution Alias, but whose data could not be read."""

    reason: str


class System(Protocol):
    @property
    def os(self) -> OsName: ...

    def getenv(self, name: str) -> str | None: ...

    @property
    def runtime_dirs(self) -> Sequence[str]:
        """PATH folders of the environment VersionBar itself runs in.

        `uv run` and `uvx` put that environment's scripts folder first on PATH,
        so without this the uv-managed Python running the core would be
        reported as the user's active Python.
        """
        ...

    def is_executable(self, path: str) -> bool: ...

    def run(self, argv: Sequence[str], timeout: float) -> ProcessResult: ...

    def app_execution_alias(self, path: str) -> AppExecutionAlias | UnreadableAlias | None:
        """The alias stored in `path`, or None when it is not one (always None off Windows).

        UnreadableAlias when the file is an alias but its data could not be
        read, so callers can refuse to run it rather than guess.

        Reads the file's reparse data only: running an alias can have side
        effects, such as the Store placeholders opening the Microsoft Store.
        """
        ...

    @property
    def platform_description(self) -> str:
        """Human-readable OS name and version, recorded as capture provenance."""
        ...

    def write_file(self, path: str, data: bytes) -> None:
        """Write `data` to `path`, creating missing parent folders. Raises OSError on failure."""
        ...

    def now(self) -> datetime:
        """Current time, timezone-aware. Behind the seam so scans are reproducible in tests."""
        ...
