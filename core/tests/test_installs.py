"""All PATH installs, `show`, and de-duplication, through the CLI seam."""

import json

from typer.testing import CliRunner

from versionbar import cli, definition
from versionbar.cli import app

from fakes import GIT_LINUX, GIT_WINDOWS, WINDOWS_PATHEXT, FakeSystem, load_capture

WIN_GIT = r"C:\Program Files\Git\cmd\git.exe"
SCOOP_GIT = r"C:\Users\dev\scoop\shims\git.exe"


def run_cli(system: FakeSystem, *args: str):
    return CliRunner().invoke(app, list(args), obj=system)


def windows_with_two_gits(path: str | None = None) -> FakeSystem:
    """Two distinct git installs on PATH.

    Both reuse real git captures; the Linux capture stands in as a second,
    different version (the output is real, only its placement is synthetic).
    """
    system = FakeSystem(
        os="windows",
        env={
            "PATH": path or r"C:\Program Files\Git\cmd;C:\Users\dev\scoop\shims",
            "PATHEXT": WINDOWS_PATHEXT,
        },
    )
    system.add_executable(WIN_GIT, load_capture(GIT_WINDOWS))
    system.add_executable(SCOOP_GIT, load_capture(GIT_LINUX))
    return system


def git_of(result) -> dict:
    return next(t for t in json.loads(result.stdout)["tools"] if t["id"] == "git")


def test_every_install_on_path_is_listed_with_the_first_hit_active() -> None:
    git = git_of(run_cli(windows_with_two_gits(), "list", "--json"))

    assert git["active"]["path"] == WIN_GIT
    assert [(i["version"], i["path"]) for i in git["installs"]] == [
        ("2.55.0.windows.2", WIN_GIT),
        ("2.43.0", SCOOP_GIT),
    ]
    assert git["installs"][0] == git["active"]


def test_repeated_windows_path_entries_collapse_to_one_install() -> None:
    # The same directory spelled with different case, a trailing separator,
    # quotes, `.` and `..` segments, and forward slashes.
    path = ";".join(
        [
            r"C:\Program Files\Git\cmd",
            r"c:\program files\git\cmd\\",
            r'"C:\Program Files\Git\cmd"',
            r"C:\Program Files\Git\.\cmd",
            r"C:\Program Files\Git\bin\..\cmd",
            "C:/Program Files/Git/cmd",
            r"C:\Users\dev\scoop\shims",
        ]
    )
    system = windows_with_two_gits(path)

    git = git_of(run_cli(system, "list", "--json"))

    assert [i["path"] for i in git["installs"]] == [WIN_GIT, SCOOP_GIT]
    assert sorted(system.runs) == sorted([(WIN_GIT, "--version"), (SCOOP_GIT, "--version")])


def test_show_json_is_the_scan_envelope_limited_to_the_requested_tool() -> None:
    result = run_cli(windows_with_two_gits(), "show", "git", "--json")

    assert result.exit_code == 0, result.output
    scan = json.loads(result.stdout)
    assert scan["schema_version"] == 1
    assert scan["platform"] == "windows"
    assert [t["id"] for t in scan["tools"]] == ["git"]
    assert [i["version"] for i in scan["tools"][0]["installs"]] == ["2.55.0.windows.2", "2.43.0"]
    # The same tool as `list` reports it.
    listed = git_of(run_cli(windows_with_two_gits(), "list", "--json"))
    assert scan["tools"][0] == listed


def test_show_human_marks_the_active_install_and_lists_the_others(monkeypatch) -> None:
    monkeypatch.delenv("FORCE_COLOR", raising=False)

    result = run_cli(windows_with_two_gits(), "show", "git")

    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if "git.exe" in line]
    assert len(lines) == 2
    assert "active" in lines[0] and WIN_GIT in lines[0] and "2.55.0.windows.2" in lines[0]
    assert "active" not in lines[1] and SCOOP_GIT in lines[1] and "2.43.0" in lines[1]
    assert all("path" in line for line in lines)


def test_show_human_reports_a_missing_tool() -> None:
    system = FakeSystem(os="windows", env={"PATH": r"C:\WINDOWS\system32"})

    result = run_cli(system, "show", "git")

    assert result.exit_code == 0, result.output
    assert "missing" in result.stdout
    assert "not found on PATH" in result.stdout


def test_list_counts_the_other_installs(monkeypatch) -> None:
    monkeypatch.delenv("FORCE_COLOR", raising=False)

    result = run_cli(windows_with_two_gits(), "list")

    header, row = [line for line in result.stdout.splitlines() if line.strip()][:2]
    assert "Others" in header
    # One other install besides the active one.
    assert row.split()[-1] == "1"
    assert WIN_GIT in row


def test_unknown_tool_ids_fail_with_the_known_ids_listed() -> None:
    system = windows_with_two_gits()

    result = run_cli(system, "show", "git", "gti", "--json")

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "gti" in result.stderr
    assert "known tools: git" in result.stderr
    assert system.runs == []


def test_show_requires_at_least_one_tool() -> None:
    result = run_cli(windows_with_two_gits(), "show")

    assert result.exit_code == 2


def test_show_with_several_tools_keeps_found_and_missing_visible(monkeypatch) -> None:
    # Only git is defined so far, so a second tool is injected. Its version
    # output is the real git capture, run through a differently named binary.
    other = definition.ToolDefinition(
        id="gitlike",
        name="Git-like",
        os=["windows", "linux"],
        binaries=["gitlike"],
        version_args=["--version"],
        version_regex=r"git version (?P<version>\d+\.\d+\.\d+\S*)",
    )
    third = other.model_copy(update={"id": "absent", "name": "Absent", "binaries": ["absent"]})
    monkeypatch.setattr(
        cli, "builtin_definitions", lambda: [*definition.builtin_definitions(), other, third]
    )
    system = windows_with_two_gits()
    system.add_executable(r"C:\Users\dev\scoop\shims\gitlike.exe", load_capture(GIT_LINUX))

    result = run_cli(system, "show", "absent", "git", "gitlike", "git", "--json")

    assert result.exit_code == 0, result.output
    tools = json.loads(result.stdout)["tools"]
    # Requested order, duplicates dropped, unrequested tools left out.
    assert [(t["id"], t["status"]) for t in tools] == [
        ("absent", "missing"),
        ("git", "found"),
        ("gitlike", "found"),
    ]


def test_repeated_posix_path_entries_collapse_but_case_differences_do_not() -> None:
    system = FakeSystem(
        os="linux", env={"PATH": "/usr/bin:/usr/bin/:/usr/./bin:/opt/../usr/bin:/USR/BIN"}
    )
    system.add_executable("/usr/bin/git", load_capture(GIT_LINUX))
    system.add_executable("/USR/BIN/git", load_capture(GIT_LINUX))

    git = git_of(run_cli(system, "list", "--json"))

    # /USR/BIN is a different directory on a case-sensitive file system.
    assert [i["path"] for i in git["installs"]] == ["/usr/bin/git", "/USR/BIN/git"]
