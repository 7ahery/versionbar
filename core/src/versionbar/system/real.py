"""The real machine, behind the platform boundary. The only module in the core
that touches processes, the environment or the machine's filesystem directly
(reading the package's own bundled data is not machine access)."""

import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from versionbar.system import OsName, ProcessResult, System


class _LocalSystem:
    def __init__(self, os_name: OsName) -> None:
        self._os: OsName = os_name

    @property
    def os(self) -> OsName:
        return self._os

    def getenv(self, name: str) -> str | None:
        return os.environ.get(name)

    def is_executable(self, path: str) -> bool:
        if self._os == "windows":
            # Windows has no execute bit; PATHEXT decides what is runnable.
            return os.path.isfile(path)
        return os.path.isfile(path) and os.access(path, os.X_OK)

    def run(self, argv: Sequence[str], timeout: float) -> ProcessResult:
        try:
            completed = subprocess.run(
                list(argv),
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as expired:
            return ProcessResult(
                exit_code=None,
                stdout=expired.stdout or b"",
                stderr=expired.stderr or b"",
                timed_out=True,
            )
        except OSError as error:
            return ProcessResult(exit_code=None, stdout=b"", stderr=b"", launch_error=str(error))
        return ProcessResult(
            exit_code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
        )

    def now(self) -> datetime:
        return datetime.now(UTC)


def local_system() -> System:
    if sys.platform == "win32":
        return _LocalSystem("windows")
    if sys.platform == "linux":
        # Not shipped in v1, but core tests and smoke checks run on Ubuntu.
        return _LocalSystem("linux")
    raise RuntimeError(f"unsupported platform: {sys.platform}")
