"""The real system's process runner, against real processes (outside the CLI seam,
like the install smoke test): the fake can only replay what this produces, so the
timeout and capture behaviour behind it is checked here."""

import os
import sys
import time
from pathlib import Path

import pytest

from versionbar.system import AppExecutionAlias
from versionbar.system.real import local_system
from versionbar.system.resolve import path_hits

# The child starts a grandchild that inherits its stdout and outlives it, as a
# `.cmd` shim's hung program would, then hangs itself.
HANGS_WITH_GRANDCHILD = (
    "import subprocess, sys, time\n"
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "print('partial', flush=True)\n"
    "time.sleep(60)\n"
)

LARGE_OUTPUT_THEN_EXIT_3 = (
    "import sys\n"
    "sys.stdout.buffer.write(bytes(range(256)) * 800)\n"
    "sys.stdout.flush()\n"
    "sys.exit(3)\n"
)


def test_a_timeout_kills_the_whole_tree_and_keeps_partial_output() -> None:
    start = time.monotonic()

    result = local_system().run([sys.executable, "-c", HANGS_WITH_GRANDCHILD], 0.5)

    elapsed = time.monotonic() - start
    assert result.timed_out
    assert result.exit_code is None
    assert result.stdout.replace(b"\r\n", b"\n") == b"partial\n"
    # Not a performance threshold: waiting for the grandchild instead of
    # killing it would take the full 60 s, so anything far below that tells
    # the two apart even on a slow CI runner.
    assert elapsed < 20, f"run returned after {elapsed:.1f} s"


def test_large_output_and_exit_code_are_captured_whole() -> None:
    result = local_system().run([sys.executable, "-c", LARGE_OUTPUT_THEN_EXIT_3], 30)

    assert (result.exit_code, result.timed_out, result.launch_error) == (3, False, None)
    # 200 KiB, every byte value: well beyond a pipe buffer, and binary-exact.
    assert result.stdout == bytes(range(256)) * 800
    assert result.stderr == b""


def test_the_interpreter_running_the_core_is_not_found_on_path() -> None:
    # The suite runs under `uv run`, which puts this environment's scripts
    # folder first on PATH, as the app's scan command does.
    name = "python" if sys.platform == "win32" else Path(sys.executable).name
    hits = [os.path.normcase(hit) for hit in path_hits(local_system(), name)]

    assert os.path.normcase(sys.executable) not in hits


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="batch wrappers are Windows-only")


def batch_wrapper(folder: Path, name: str = "tool.cmd") -> Path:
    # Prints the command line cmd.exe was started with and the arguments it
    # passed on, and leaves a mark, so a test can tell whether it ran at all.
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / name
    script.write_bytes(
        b'@echo off\r\necho ran> "%~dp0ran.txt"\r\necho args=%*\r\necho cmdline=%CMDCMDLINE%\r\n'
    )
    return script


@windows_only
@pytest.mark.parametrize("name", ["tool.cmd", "tool.bat"])
def test_a_batch_wrapper_in_a_folder_with_spaces_and_parentheses_runs(
    tmp_path: Path, name: str
) -> None:
    # `Program Files (x86)` is where such wrappers commonly live, and the
    # parentheses are what naive cmd.exe quoting breaks on.
    script = batch_wrapper(tmp_path / "Program Files (x86)" / "tool", name)

    result = local_system().run([str(script), "--version"], 30)

    assert (result.exit_code, result.launch_error) == (0, None), result
    lines = result.stdout.decode().splitlines()
    assert lines[0] == "args=--version"
    # cmd.exe AutoRun hooks (conda, clink) would otherwise run before every
    # wrapper: slower, and free to print or change directory.
    assert " /d " in lines[1].casefold(), lines[1]


@windows_only
@pytest.mark.parametrize(
    "argument",
    ["%PATH%", "a&b", "a|b", "a>b", "a^b", '"quoted"', "a b", "a,b", "a;b", "a=b"],
)
def test_a_batch_wrapper_is_not_given_arguments_cmd_would_reinterpret(
    tmp_path: Path, argument: str
) -> None:
    script = batch_wrapper(tmp_path / "bin")

    result = local_system().run([str(script), argument], 30)

    assert result.exit_code is None
    assert result.launch_error is not None
    assert "cmd.exe" in result.launch_error
    assert not (tmp_path / "bin" / "ran.txt").exists()


@windows_only
def test_a_batch_wrapper_whose_path_cmd_would_expand_is_not_run(tmp_path: Path) -> None:
    script = batch_wrapper(tmp_path / "100%USERNAME%")

    result = local_system().run([str(script), "--version"], 30)

    assert result.launch_error is not None
    assert not (script.parent / "ran.txt").exists()


def test_an_ordinary_executable_is_not_an_app_execution_alias() -> None:
    assert local_system().app_execution_alias(sys.executable) is None


@pytest.mark.skipif(sys.platform != "win32", reason="App Execution Aliases are Windows-only")
def test_an_app_execution_alias_is_read_without_running_it() -> None:
    # winget's alias ships with App Installer on Windows 11 and the Windows CI
    # images; reading it proves the reparse data parsing on a real file.
    winget = Path(os.environ["LOCALAPPDATA"], "Microsoft", "WindowsApps", "winget.exe")
    if not winget.exists():
        pytest.skip("no winget alias on this machine")

    alias = local_system().app_execution_alias(str(winget))

    assert isinstance(alias, AppExecutionAlias), alias
    assert alias.package_family == "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe"
    assert alias.app_user_model_id == "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe!winget"
    assert alias.target.lower().endswith(r"\winget.exe")


def test_the_config_folder_is_the_platform_one() -> None:
    folder = Path(local_system().config_dir)

    assert folder.name == "versionbar"
    if sys.platform == "win32":
        # Roaming AppData, where per-user settings live on Windows.
        assert folder.parent == Path(os.environ["APPDATA"])
    else:
        default = Path(os.environ.get("HOME", "~")).expanduser() / ".config"
        assert folder.parent == Path(os.environ.get("XDG_CONFIG_HOME") or default)


def test_reading_a_file_tells_absent_from_present(tmp_path: Path) -> None:
    present = tmp_path / "config.toml"
    present.write_bytes(b"timeout = 3\n")

    assert local_system().read_file(str(present)) == b"timeout = 3\n"
    with pytest.raises(FileNotFoundError):
        local_system().read_file(str(tmp_path / "absent.toml"))


def test_listing_a_folder_tells_absent_and_file_apart(tmp_path: Path) -> None:
    # Providers rely on these exceptions to tell a manager that is not there
    # (nothing to say) from one they cannot read (a note).
    (tmp_path / "v24.21.0").mkdir()
    (tmp_path / "nvm.exe").write_bytes(b"")

    assert sorted(local_system().list_dir(str(tmp_path))) == ["nvm.exe", "v24.21.0"]
    with pytest.raises(FileNotFoundError):
        local_system().list_dir(str(tmp_path / "absent"))
    with pytest.raises(NotADirectoryError):
        local_system().list_dir(str(tmp_path / "nvm.exe"))
