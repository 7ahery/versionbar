"""`versionbar` / `versionbar list` over a fake system, through the CLI seam."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from versionbar.cli import app

from fakes import (
    GIT_LINUX,
    GIT_WINDOWS,
    WINDOWS_PATHEXT,
    FakeSystem,
    load_capture,
    windows_with_git,
)


def run_cli(system: FakeSystem, *args: str):
    return CliRunner().invoke(app, list(args), obj=system)


def run_entry_point(args: list[str], system_expr: str) -> subprocess.CompletedProcess[bytes]:
    """Run the real `main()` in a fresh interpreter with real, piped stdout.

    `system_expr` is Python source building the fake system from `fakes`. The
    child reports on stderr whether Rich was imported.
    """
    program = (
        "import sys\n"
        "import fakes\n"
        "from versionbar.cli import main\n"
        f"sys.argv = ['versionbar', *{args!r}]\n"
        "try:\n"
        f"    main({system_expr})\n"
        "finally:\n"
        "    sys.stderr.write('rich imported' if 'rich' in sys.modules else 'rich absent')\n"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parent)}
    # Let the child pick its platform-default stdout encoding (cp1252 on a
    # Windows pipe), which is what a user's redirect gets.
    for name in ("PYTHONUTF8", "PYTHONIOENCODING"):
        env.pop(name, None)
    return subprocess.run([sys.executable, "-c", program], capture_output=True, env=env)


def test_list_json_reports_git_active_install_from_path() -> None:
    result = run_cli(windows_with_git(), "list", "--json")

    assert result.exit_code == 0, result.output
    scan = json.loads(result.stdout)
    git = next(tool for tool in scan["tools"] if tool["id"] == "git")
    assert git["status"] == "found"
    assert git["active"]["version"] == "2.55.0.windows.2"
    assert git["active"]["path"] == r"C:\Program Files\Git\cmd\git.exe"
    assert git["active"]["source"] == "path"
    assert git["installs"] == [git["active"]]


def test_bare_command_prints_human_table_with_active_version_and_path(monkeypatch) -> None:
    # Captured output is a pipe; FORCE_COLOR would legitimately override that.
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    result = run_cli(windows_with_git())

    assert result.exit_code == 0, result.output
    row = next(line for line in result.stdout.splitlines() if line.startswith("git"))
    assert "2.55.0.windows.2" in row
    assert r"C:\Program Files\Git\cmd\git.exe" in row
    assert "\x1b[" not in result.stdout


def test_human_table_shows_missing_git() -> None:
    system = FakeSystem(os="windows", env={"PATH": r"C:\WINDOWS\system32"})

    result = run_cli(system, "list")

    row = next(line for line in result.stdout.splitlines() if line.startswith("git"))
    assert "missing" in row


def test_force_color_and_no_color_are_read_from_the_system_environment(monkeypatch) -> None:
    # The process environment says the opposite, to prove it is not consulted.
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    system = FakeSystem(os="windows", env={"PATH": r"C:\WINDOWS\system32", "FORCE_COLOR": "1"})
    assert "\x1b[" in run_cli(system, "list").stdout

    system.env["NO_COLOR"] = "1"
    assert "\x1b[" not in run_cli(system, "list").stdout


def test_piped_human_output_never_wraps_long_paths(monkeypatch) -> None:
    # COLUMNS describes a terminal; piped output has no width to respect.
    monkeypatch.setenv("COLUMNS", "40")
    git_dir = r"C:\Users\developer\AppData\Local\Programs\Portable Toolchains\Git 2.55\cmd"
    system = windows_with_git(git_dir)

    result = run_cli(system, "list")

    row = next(line for line in result.stdout.splitlines() if line.startswith("git"))
    assert rf"{git_dir}\git.exe" in row


@pytest.mark.parametrize("args", [["list"], ["list", "--json"]])
def test_non_ascii_paths_print_as_utf8_on_a_pipe(args: list[str]) -> None:
    git_dir = r"C:\Users\Дмитрий\Git\cmd"

    completed = run_entry_point(args, f"fakes.windows_with_git({git_dir!r})")

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    assert rf"{git_dir}\git.exe".encode() in completed.stdout.replace(b"\\\\", b"\\")


def test_bare_json_flag_matches_list_json() -> None:
    bare = json.loads(run_cli(windows_with_git(), "--json").stdout)
    listed = json.loads(run_cli(windows_with_git(), "list", "--json").stdout)

    assert bare == listed


@pytest.mark.parametrize("args", [["list", "--json"], ["--json"]])
def test_json_runs_never_import_rich(args: list[str]) -> None:
    # A fresh interpreter, because this test session has already imported Rich.
    completed = run_entry_point(args, "fakes.FakeSystem(env={'PATH': ''})")

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["tools"]
    assert completed.stderr == b"rich absent"


def test_list_json_envelope_carries_schema_version_time_and_platform() -> None:
    result = run_cli(windows_with_git(), "list", "--json")

    scan = json.loads(result.stdout)
    assert scan["schema_version"] == 1
    assert scan["scanned_at"] == "2026-10-23T21:04:52Z"
    assert scan["platform"] == "windows"


def test_missing_git_stays_visible_with_null_active() -> None:
    system = FakeSystem(
        os="windows", env={"PATH": r"C:\WINDOWS\system32", "PATHEXT": WINDOWS_PATHEXT}
    )

    result = run_cli(system, "list", "--json")

    assert result.exit_code == 0, result.output
    git = next(tool for tool in json.loads(result.stdout)["tools"] if tool["id"] == "git")
    assert git["status"] == "missing"
    assert git["active"] is None
    assert git["installs"] == []
    assert system.runs == []


def test_resolution_follows_path_order_then_pathext_and_skips_extensionless_files() -> None:
    system = FakeSystem(
        os="windows",
        env={
            # Windows environment names are case-insensitive.
            "Path": r"C:\tools\shims;C:\Program Files\Git\cmd;C:\Program Files\Git\bin",
            "PATHEXT": WINDOWS_PATHEXT,
        },
    )
    git = load_capture(GIT_WINDOWS)
    # An extensionless script earlier on PATH is not what `git` runs on Windows.
    system.add_executable(r"C:\tools\shims\git", git)
    # Within one directory, PATHEXT order decides (.EXE before .CMD).
    system.add_executable(r"C:\Program Files\Git\cmd\git.cmd", git)
    system.add_executable(r"C:\Program Files\Git\cmd\git.exe", git)
    system.add_executable(r"C:\Program Files\Git\bin\git.exe", git)

    result = run_cli(system, "list", "--json")

    tool = next(t for t in json.loads(result.stdout)["tools"] if t["id"] == "git")
    assert tool["active"]["path"] == r"C:\Program Files\Git\cmd\git.exe"
    assert system.runs == [(r"C:\Program Files\Git\cmd\git.exe", "--version")]


def test_pathext_entries_with_stray_spaces_still_resolve() -> None:
    system = windows_with_git()
    system.env["PATHEXT"] = ".COM; .EXE ;.BAT"

    result = run_cli(system, "list", "--json")

    tool = next(t for t in json.loads(result.stdout)["tools"] if t["id"] == "git")
    assert tool["active"]["path"] == r"C:\Program Files\Git\cmd\git.exe"


def test_linux_reports_git_from_path() -> None:
    system = FakeSystem(os="linux", env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/bin:/bin"})
    system.add_executable("/usr/bin/git", load_capture(GIT_LINUX))

    scan = json.loads(run_cli(system, "list", "--json").stdout)

    assert scan["platform"] == "linux"
    git = next(t for t in scan["tools"] if t["id"] == "git")
    assert git["status"] == "found"
    assert git["active"]["version"] == "2.43.0"
    assert git["active"]["path"] == "/usr/bin/git"


def test_linux_reports_missing_git() -> None:
    # Linux paths are case-sensitive: /USR/BIN is a different directory.
    system = FakeSystem(os="linux", env={"PATH": "/USR/BIN:/bin"})
    system.add_executable("/usr/bin/git", load_capture(GIT_LINUX))

    scan = json.loads(run_cli(system, "list", "--json").stdout)

    git = next(t for t in scan["tools"] if t["id"] == "git")
    assert git["status"] == "missing"
    assert git["active"] is None
