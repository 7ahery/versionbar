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

from versionbar.system import AppExecutionAlias, OsName, ProcessResult, System

# How long a timed-out command's tree gets to die and release its pipes.
_DRAIN_SECONDS = 1.0
_IO_REPARSE_TAG_APPEXECLINK = 0x8000001B


class _LocalSystem:
    def __init__(self, os_name: OsName) -> None:
        self._os: OsName = os_name

    @property
    def os(self) -> OsName:
        return self._os

    def getenv(self, name: str) -> str | None:
        return os.environ.get(name)

    @property
    def runtime_dirs(self) -> list[str]:
        # Only a virtual environment (what uv run, uvx and the app use) is the
        # launcher's own. Outside one the interpreter is a base install, which
        # is only on PATH if the user put it there.
        if sys.prefix == sys.base_prefix:
            return []
        return [os.path.join(sys.prefix, "Scripts" if sys.platform == "win32" else "bin")]

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
                self._abandon_pipes(process)
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
            # OSError covers a group that is already gone and one we may not
            # signal; neither may stop the scan.
            with contextlib.suppress(OSError):
                os.killpg(process.pid, signal.SIGKILL)
        # Covers a taskkill that could not run; harmless if the child is gone.
        with contextlib.suppress(OSError):
            process.kill()

    @staticmethod
    def _abandon_pipes(process: subprocess.Popen[bytes]) -> None:
        if sys.platform == "win32":
            # Not closed here: communicate() reads on Windows in daemon threads
            # that hold each pipe's buffer lock, so close() would block until
            # the stray holder exits, which is the very stall this avoids
            # (measured: 28 s for a 30 s sleeper). Those threads end, and the
            # handles are released, when the holder does.
            return
        # On POSIX communicate() reads on this thread, so nothing else holds
        # the pipes and closing them now stops the descriptors leaking.
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()

    def app_execution_alias(self, path: str) -> AppExecutionAlias | None:
        if sys.platform != "win32":
            return None
        try:
            # Cheap filter first: almost every PATH hit is an ordinary file.
            tag = os.stat(path, follow_symlinks=False).st_reparse_tag
        except OSError:
            return None
        if tag != _IO_REPARSE_TAG_APPEXECLINK:
            return None
        return _read_app_execution_alias(path)

    @property
    def platform_description(self) -> str:
        return platform.platform()

    def write_file(self, path: str, data: bytes) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def now(self) -> datetime:
        return datetime.now(UTC)


def _read_app_execution_alias(path: str) -> AppExecutionAlias | None:
    """Read an App Execution Alias's reparse data with FSCTL_GET_REPARSE_POINT.

    Python has no API for this reparse type (os.readlink rejects it), hence
    ctypes. The file is opened with no access rights and as the reparse point
    itself, so nothing it points to is opened or run.
    """
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.restype = wintypes.HANDLE
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    device_io_control = kernel32.DeviceIoControl
    device_io_control.restype = wintypes.BOOL
    device_io_control.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    share_all = 0x1 | 0x2 | 0x4  # FILE_SHARE_READ | WRITE | DELETE
    open_existing = 3
    open_reparse_point = 0x00200000 | 0x02000000  # FILE_FLAG_OPEN_REPARSE_POINT | BACKUP_SEMANTICS
    fsctl_get_reparse_point = 0x000900A8
    handle = create_file(path, 0, share_all, None, open_existing, open_reparse_point, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        return None
    try:
        # MAXIMUM_REPARSE_DATA_BUFFER_SIZE.
        buffer = ctypes.create_string_buffer(16 * 1024)
        returned = wintypes.DWORD()
        if not device_io_control(
            handle,
            fsctl_get_reparse_point,
            None,
            0,
            buffer,
            len(buffer),
            ctypes.byref(returned),
            None,
        ):
            return None
        data = buffer.raw[: returned.value]
    finally:
        kernel32.CloseHandle(handle)
    return _parse_app_execution_alias(data)


def _parse_app_execution_alias(data: bytes) -> AppExecutionAlias | None:
    # REPARSE_DATA_BUFFER: tag (4), data length (2), reserved (2), then the
    # undocumented APPEXECLINK payload: a version (3 so far) and NUL-separated
    # UTF-16 strings: package family, app user model id, target, app type.
    if len(data) < 12 or int.from_bytes(data[:4], "little") != _IO_REPARSE_TAG_APPEXECLINK:
        return None
    if int.from_bytes(data[8:12], "little") != 3:
        return None
    strings = data[12:].decode("utf-16-le", errors="replace").split("\0")
    if len(strings) < 3:
        return None
    family, app_id, target = strings[:3]
    return AppExecutionAlias(package_family=family, app_user_model_id=app_id, target=target)


def local_system() -> System:
    if sys.platform == "win32":
        return _LocalSystem("windows")
    if sys.platform == "linux":
        # Not shipped in v1, but core tests and smoke checks run on Ubuntu.
        return _LocalSystem("linux")
    raise RuntimeError(f"unsupported platform: {sys.platform}")
