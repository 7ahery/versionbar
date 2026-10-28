"""All PATH installs, `show`, and de-duplication, through the CLI seam."""

import json

from versionbar import cli, definition

from fakes import (
    GIT_LINUX,
    GIT_WINDOWS,
    UV_WINDOWS,
    WINDOWS_PATHEXT,
    FakeSystem,
    load_capture,
    run_cli,
)

WIN_GIT = r"C:\Program Files\Git\cmd\git.exe"
SCOOP_GIT = r"C:\Users\dev\scoop\shims\git.exe"


def builtin_git():
    return next(d for d in definition.builtin_definitions() if d.id == "git")


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


def test_show_human_headers_sit_over_their_values(monkeypatch) -> None:
    monkeypatch.delenv("FORCE_COLOR", raising=False)

    result = run_cli(windows_with_two_gits(), "show", "git", "node")

    header, active, other, node = [line for line in result.stdout.splitlines() if line.strip()][:4]
    column = header.index
    # Every column has a title, so each one starts where its values start.
    assert header.split() == ["Tool", "Install", "Version", "Path", "Source"]
    assert active.index("active") == other.index("other") == column("Install")
    assert active.index("2.55.0.windows.2") == other.index("2.43.0") == column("Version")
    assert active.index(WIN_GIT) == other.index(SCOOP_GIT) == column("Path")
    assert active.index("path", len(WIN_GIT) + column("Path")) == column("Source")
    # A tool with no install shows its status where a version would be, as `list` does.
    assert node.index("missing") == column("Version")


def test_list_counts_the_other_installs(monkeypatch) -> None:
    monkeypatch.delenv("FORCE_COLOR", raising=False)

    result = run_cli(windows_with_two_gits(), "list")

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    header, row = lines[0], next(line for line in lines if line.startswith("git"))
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
    assert "git" in result.stderr.split("known tools:")[1]
    assert system.runs == []


def test_tool_known_only_for_another_os_is_not_called_unknown(monkeypatch) -> None:
    linux_only = builtin_git().model_copy(update={"id": "linuxonly", "os": ["linux"]})
    # The core four all run on both OSes; remove once a built-in is OS-specific
    # (WSL, ticket 15, #17).
    monkeypatch.setattr(
        cli, "builtin_definitions", lambda: [*definition.builtin_definitions(), linux_only]
    )

    result = run_cli(windows_with_two_gits(), "show", "linuxonly")

    assert result.exit_code == 2
    assert "linuxonly is not available on windows" in result.stderr
    assert "Unknown" not in result.stderr


def test_relative_path_entries_are_skipped_not_reported_as_bare_names() -> None:
    # `.` and `..\x` mean "relative to the cwd", which a scan does not have.
    system = windows_with_two_gits(r".;.\;..\bin;C:\Program Files\Git\cmd;C:\Users\dev\scoop\shims")
    system.add_executable("git.exe", load_capture(GIT_LINUX))
    system.add_executable(r"..\bin\git.exe", load_capture(GIT_LINUX))

    git = git_of(run_cli(system, "list", "--json"))

    assert [i["path"] for i in git["installs"]] == [WIN_GIT, SCOOP_GIT]


def test_relative_posix_path_entries_are_skipped() -> None:
    system = FakeSystem(os="linux", env={"PATH": ".:bin:/usr/bin"})
    system.add_executable("git", load_capture(GIT_LINUX))
    system.add_executable("bin/git", load_capture(GIT_LINUX))
    system.add_executable("/usr/bin/git", load_capture(GIT_LINUX))

    git = git_of(run_cli(system, "list", "--json"))

    assert [i["path"] for i in git["installs"]] == ["/usr/bin/git"]


def test_a_binary_matched_by_two_declared_names_is_one_install(monkeypatch) -> None:
    both = builtin_git().model_copy(update={"binaries": ["git", "git.exe"]})
    # No built-in declares two names for one file, so one is made up here.
    monkeypatch.setattr(cli, "builtin_definitions", lambda: [both])

    git = git_of(run_cli(windows_with_two_gits(), "list", "--json"))

    assert [i["path"] for i in git["installs"]] == [WIN_GIT, SCOOP_GIT]


def test_show_requires_at_least_one_tool() -> None:
    result = run_cli(windows_with_two_gits(), "show")

    assert result.exit_code == 2


def test_show_with_several_tools_keeps_found_and_missing_visible() -> None:
    system = windows_with_two_gits()
    system.add_executable(r"C:\Users\dev\scoop\shims\uv.exe", load_capture(UV_WINDOWS))

    result = run_cli(system, "show", "node", "git", "uv", "git", "--json")

    assert result.exit_code == 0, result.output
    tools = json.loads(result.stdout)["tools"]
    # Requested order, duplicates dropped, unrequested tools (python) left out.
    assert [(t["id"], t["status"]) for t in tools] == [
        ("node", "missing"),
        ("git", "found"),
        ("uv", "found"),
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
