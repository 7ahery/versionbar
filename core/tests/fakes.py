"""A fake system built from real captured fixtures, injected at the CLI seam.

Machine state (PATH, environment, which files exist) is synthetic and set per
test; command output only ever comes from captured fixtures, never invented
strings.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from versionbar.capture import CaptureFile
from versionbar.cli import app
from versionbar.system import AppExecutionAlias, OsName, ProcessResult, UnreadableAlias

FIXTURES = Path(__file__).parent / "fixtures"

WINDOWS_CONFIG_DIR = r"C:\Users\dev\AppData\Roaming\versionbar"
LINUX_CONFIG_DIR = "/home/dev/.config/versionbar"

WINDOWS_PATHEXT = ".COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC;.CPL"


@dataclass(frozen=True)
class Capture:
    args: tuple[str, ...]
    result: ProcessResult
    # How long the command takes to answer on the fake machine. One slower
    # than the timeout it is run with times out, printing nothing.
    seconds: float = 0.0


def capture_from_bytes(data: bytes) -> Capture:
    """Replay a capture file (as written by `debug capture`) byte for byte."""
    record = CaptureFile.model_validate_json(data)
    return Capture(
        args=tuple(record.args),
        result=ProcessResult(
            exit_code=record.exit_code, stdout=record.stdout_b64, stderr=record.stderr_b64
        ),
    )


def load_capture(relative: str) -> Capture:
    return capture_from_bytes((FIXTURES / relative).read_bytes())


@dataclass
class FakeSystem:
    os: OsName = "windows"
    env: dict[str, str] = field(default_factory=dict)
    clock: datetime = datetime(2026, 10, 23, 21, 4, 52, tzinfo=UTC)
    _executables: dict[str, list[Capture]] = field(default_factory=dict)
    runs: list[tuple[str, ...]] = field(default_factory=list)
    os_description: str = "Windows-11-10.0.26200-SP0"
    files: dict[str, bytes] = field(default_factory=dict)
    _aliases: dict[str, AppExecutionAlias | UnreadableAlias] = field(default_factory=dict)
    runtime_dirs: list[str] = field(default_factory=list)
    _contents: dict[str, bytes] = field(default_factory=dict)
    # Lets a test make the destination unwritable without touching a real disk.
    write_error: str | None = None
    # Called on the scanning thread before each command answers, so a test can
    # hold commands at a barrier to prove they overlap, without timing anything.
    before_run: Callable[[tuple[str, ...]], object] | None = None
    # Where platformdirs would put VersionBar's config; set per OS when empty.
    config_dir: str = ""
    _read_errors: dict[str, str] = field(default_factory=dict)
    # Every file and folder the machine has, by key, as originally spelled:
    # folder listings are derived from it, so a test only declares files.
    _entries: dict[str, str] = field(default_factory=dict)
    _list_errors: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.config_dir:
            self.config_dir = WINDOWS_CONFIG_DIR if self.os == "windows" else LINUX_CONFIG_DIR

    def _key(self, path: str) -> str:
        # Windows file names are case-insensitive; the fake must be too, or
        # tests would pass or fail on casing the real system ignores.
        return path.casefold() if self.os == "windows" else path

    def add_executable(self, path: str, *captures: Capture) -> None:
        self._executables[self._key(path)] = list(captures)
        self._entries[self._key(path)] = path

    def add_folder(self, path: str) -> None:
        """A folder that exists even if no file in it was added."""
        self._entries[self._key(path)] = path

    def add_unlistable(self, path: str, error: str) -> None:
        """A folder whose listing fails with `error`."""
        self.add_folder(path)
        self._list_errors[self._key(path)] = error

    def list_dir(self, path: str) -> list[str]:
        separator = "\\" if self.os == "windows" else "/"
        key = self._key(path).rstrip(separator)
        error = self._list_errors.get(key)
        if error is not None:
            raise PermissionError(error)
        names: dict[str, None] = {}
        for entry_key, original in self._entries.items():
            if entry_key.startswith(key + separator):
                names[original[len(key) + 1 :].split(separator)[0]] = None
        if key in self._executables or key in self._contents:
            raise NotADirectoryError(path)
        if not names and key not in self._entries:
            raise FileNotFoundError(path)
        # Insertion order, not sorted: the real listing promises no order.
        return list(names)

    def add_app_execution_alias(
        self, path: str, alias: AppExecutionAlias | UnreadableAlias, *captures: Capture
    ) -> None:
        # Placeholders get no captures, so running one fails the test.
        self.add_executable(path, *captures)
        self._aliases[self._key(path)] = alias

    def add_content(self, path: str, data: bytes) -> None:
        """What reading the file at `path` returns; files without content are unreadable."""
        self._contents[self._key(path)] = data
        self._entries[self._key(path)] = path

    def read_file_head(self, path: str, limit: int) -> bytes | None:
        data = self._contents.get(self._key(path))
        return None if data is None else data[:limit]

    def read_file(self, path: str) -> bytes:
        error = self._read_errors.get(self._key(path))
        if error is not None:
            raise PermissionError(error)
        data = self._contents.get(self._key(path))
        if data is None:
            raise FileNotFoundError(path)
        return data

    @property
    def config_path(self) -> str:
        separator = "\\" if self.os == "windows" else "/"
        return f"{self.config_dir}{separator}config.toml"

    def add_unreadable(self, path: str, error: str) -> None:
        """A file that exists but whose reading fails with `error`."""
        self._read_errors[self._key(path)] = error

    def add_config(self, text: str) -> None:
        """Give the machine a user config file holding `text`."""
        self.add_content(self.config_path, text.encode())

    def app_execution_alias(self, path: str) -> AppExecutionAlias | UnreadableAlias | None:
        return self._aliases.get(self._key(path))

    def getenv(self, name: str) -> str | None:
        if self.os == "windows":
            matches = [v for k, v in self.env.items() if k.upper() == name.upper()]
            return matches[0] if matches else None
        return self.env.get(name)

    def is_executable(self, path: str) -> bool:
        return self._key(path) in self._executables

    def run(self, argv: Sequence[str], timeout: float) -> ProcessResult:
        self.runs.append(tuple(argv))
        if self.before_run is not None:
            self.before_run(tuple(argv))
        captures = self._executables[self._key(argv[0])]
        for capture in captures:
            if capture.args == tuple(argv[1:]):
                if capture.seconds > timeout:
                    return ProcessResult(exit_code=None, stdout=b"", stderr=b"", timed_out=True)
                return capture.result
        raise AssertionError(f"no captured output for {list(argv)}")

    @property
    def platform_description(self) -> str:
        return self.os_description

    def write_file(self, path: str, data: bytes) -> None:
        if self.write_error is not None:
            raise OSError(self.write_error)
        self.files[path] = data

    def now(self) -> datetime:
        return self.clock


GIT_WINDOWS = "git/windows-git-2.55.0.windows.2.json"
GIT_LINUX = "git/linux-git-2.43.0.json"
NODE_WINDOWS = "node/windows-node-24.21.0.json"
NODE_24_22_WINDOWS = "node/windows-node-24.22.1.json"
NVM_NODE_WINDOWS = "nvm/windows-node-24.21.0.json"
UV_WINDOWS = "uv/windows-uv-0.12.23.json"
UV_PYTHON_LIST_WINDOWS = "uv/windows-uv-python-list-0.12.23.json"
RUSTC_WINDOWS = "rustc/windows-rustc-1.99.1.json"
CARGO_WINDOWS = "cargo/windows-cargo-1.99.1.json"
PYTHON_314_WINDOWS = "python/windows-python-3.14.8.json"
PYTHON_313_WINDOWS = "python/windows-python-3.13.16.json"

# Real alias data, read (not run) from the reparse points in the WindowsApps
# folder of a Windows 11 26200 machine with App Installer 1.29.379.0. On that
# machine `python.exe` and `python3.exe` both hold the first one.
_APP_INSTALLER = "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe"
_APP_INSTALLER_DIR = (
    r"C:\Program Files\WindowsApps\Microsoft.DesktopAppInstaller_1.29.379.0_x64__8wekyb3d8bbwe"
)
STORE_PYTHON_PLACEHOLDER = AppExecutionAlias(
    package_family=_APP_INSTALLER,
    app_user_model_id=f"{_APP_INSTALLER}!PythonRedirector",
    target=rf"{_APP_INSTALLER_DIR}\AppInstallerPythonRedirector.exe",
)
# A real tool from the same App Installer package, so the rule cannot be "any
# App Installer alias".
WINGET_ALIAS = AppExecutionAlias(
    package_family=_APP_INSTALLER,
    app_user_model_id=f"{_APP_INSTALLER}!winget",
    target=rf"{_APP_INSTALLER_DIR}\winget.exe",
)


def windows_with_git(git_dir: str = r"C:\Program Files\Git\cmd") -> FakeSystem:
    system = FakeSystem(
        os="windows",
        env={
            "PATH": rf"C:\WINDOWS\system32;{git_dir};C:\Users\dev\bin",
            "PATHEXT": WINDOWS_PATHEXT,
        },
    )
    system.add_executable(rf"{git_dir}\git.exe", load_capture(GIT_WINDOWS))
    return system


def run_cli(system: FakeSystem, *args: str):
    """Invoke the CLI in-process with `system` injected as the machine."""
    return CliRunner().invoke(app, list(args), obj=system)
