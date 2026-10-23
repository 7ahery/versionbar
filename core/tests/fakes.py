"""A fake system built from real captured fixtures, injected at the CLI seam.

Machine state (PATH, environment, which files exist) is synthetic and set per
test; command output only ever comes from captured fixtures, never invented
strings.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from versionbar.capture import CaptureFile
from versionbar.system import OsName, ProcessResult

FIXTURES = Path(__file__).parent / "fixtures"

WINDOWS_PATHEXT = ".COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC;.CPL"


@dataclass(frozen=True)
class Capture:
    args: tuple[str, ...]
    result: ProcessResult


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
    # Lets a test make the destination unwritable without touching a real disk.
    write_error: str | None = None

    def _key(self, path: str) -> str:
        # Windows file names are case-insensitive; the fake must be too, or
        # tests would pass or fail on casing the real system ignores.
        return path.casefold() if self.os == "windows" else path

    def add_executable(self, path: str, *captures: Capture) -> None:
        self._executables[self._key(path)] = list(captures)

    def getenv(self, name: str) -> str | None:
        if self.os == "windows":
            matches = [v for k, v in self.env.items() if k.upper() == name.upper()]
            return matches[0] if matches else None
        return self.env.get(name)

    def is_executable(self, path: str) -> bool:
        return self._key(path) in self._executables

    def run(self, argv: Sequence[str], timeout: float) -> ProcessResult:
        self.runs.append(tuple(argv))
        captures = self._executables[self._key(argv[0])]
        for capture in captures:
            if capture.args == tuple(argv[1:]):
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
