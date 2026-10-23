"""The real machine, behind the platform boundary. The only module in the core
that touches processes, the environment or the machine's filesystem directly
(reading the package's own bundled data is not machine access)."""

import contextlib
import os
import platform
import signal
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from versionbar.system import OsName, ProcessResult, System

# How long a timed-out command's tree gets to die and release its pipes.
_DRAIN_SECONDS = 1.0


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
        # Not subprocess.run: after a timeout it kills only the direct child
        # and then, on Windows, waits without limit for the pipes to close. A
        # `.cmd` shim whose hung grandchild inherited them would then stall the
        # scan for as long as the grandchild lives.
        try:
            process = subprocess.Popen(
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # Its own process group, so a timeout can kill the whole tree.
                start_new_session=sys.platform != "win32",
            )
        except OSError as error:
            return ProcessResult(exit_code=None, stdout=b"", stderr=b"", launch_error=str(error))
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._kill_tree(process)
            try:
                stdout, stderr = process.communicate(timeout=_DRAIN_SECONDS)
            except subprocess.TimeoutExpired:
                # Something outside the tree still holds the pipes; the
                # partial output is not worth waiting for.
                stdout, stderr = b"", b""
            return ProcessResult(
                exit_code=None, stdout=stdout or b"", stderr=stderr or b"", timed_out=True
            )
        return ProcessResult(exit_code=process.returncode, stdout=stdout, stderr=stderr)

    def _kill_tree(self, process: subprocess.Popen[bytes]) -> None:
        if sys.platform == "win32":
            # taskkill walks the tree by parent id, so it must run before the
            # child dies. Full path: a scan must not run whatever `taskkill`
            # the PATH under inspection happens to offer.
            system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
            taskkill = os.path.join(system_root, "System32", "taskkill.exe")
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run(
                    [taskkill, "/F", "/T", "/PID", str(process.pid)],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=_DRAIN_SECONDS,
                    check=False,
                )
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        # Covers a taskkill that could not run; harmless if the child is gone.
        process.kill()

    @property
    def platform_description(self) -> str:
        return platform.platform()

    def write_file(self, path: str, data: bytes) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def now(self) -> datetime:
        return datetime.now(UTC)


def local_system() -> System:
    if sys.platform == "win32":
        return _LocalSystem("windows")
    if sys.platform == "linux":
        # Not shipped in v1, but core tests and smoke checks run on Ubuntu.
        return _LocalSystem("linux")
    raise RuntimeError(f"unsupported platform: {sys.platform}")
