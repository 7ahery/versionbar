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


class System(Protocol):
    @property
    def os(self) -> OsName: ...

    def getenv(self, name: str) -> str | None: ...

    def is_executable(self, path: str) -> bool: ...

    def run(self, argv: Sequence[str], timeout: float) -> ProcessResult: ...

    def now(self) -> datetime:
        """Current time, timezone-aware. Behind the seam so scans are reproducible in tests."""
        ...
