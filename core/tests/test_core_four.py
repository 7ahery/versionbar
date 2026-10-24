"""The M1 core four (git, node, python, uv) on Windows, through the CLI seam."""

import json

from typer.testing import CliRunner

from versionbar.cli import app
from versionbar.system import ProcessResult, UnreadableAlias

from fakes import (
    GIT_WINDOWS,
    NODE_WINDOWS,
    PYTHON_313_WINDOWS,
    PYTHON_314_WINDOWS,
    STORE_PYTHON_PLACEHOLDER,
    UV_WINDOWS,
    WINDOWS_PATHEXT,
    WINGET_ALIAS,
    Capture,
    FakeSystem,
    load_capture,
)

GIT = r"C:\Program Files\Git\cmd\git.exe"
NODE = r"C:\Users\dev\AppData\Local\nvm\.nodejs\node.exe"
UV = r"C:\Users\dev\.local\bin\uv.exe"
PYTHON = r"C:\Program Files\Python314\python.exe"


def run_cli(system: FakeSystem, *args: str):
    return CliRunner().invoke(app, list(args), obj=system)


def windows(*directories: str) -> FakeSystem:
    return FakeSystem(
        os="windows",
        env={"PATH": ";".join([r"C:\WINDOWS\system32", *directories]), "PATHEXT": WINDOWS_PATHEXT},
    )


def tools_of(result) -> dict[str, dict]:
    assert result.exit_code == 0, result.output
    return {tool["id"]: tool for tool in json.loads(result.stdout)["tools"]}


def core_four() -> FakeSystem:
    system = windows(
        r"C:\Program Files\Python314",
        r"C:\Program Files\Git\cmd",
        r"C:\Users\dev\AppData\Local\nvm\.nodejs",
        r"C:\Users\dev\.local\bin",
    )
    system.add_executable(GIT, load_capture(GIT_WINDOWS))
    system.add_executable(NODE, load_capture(NODE_WINDOWS))
    system.add_executable(UV, load_capture(UV_WINDOWS))
    system.add_executable(PYTHON, load_capture(PYTHON_314_WINDOWS))
    return system


def test_list_reports_the_core_four_with_versions_and_paths() -> None:
    result = run_cli(core_four(), "list", "--json")

    assert result.exit_code == 0, result.output
    tools = json.loads(result.stdout)["tools"]
    assert [(t["id"], t["name"], t["status"]) for t in tools] == [
        ("git", "Git", "found"),
        ("node", "Node.js", "found"),
        ("python", "Python", "found"),
        ("uv", "uv", "found"),
    ]
    assert [(t["active"]["version"], t["active"]["path"]) for t in tools] == [
        ("2.55.0.windows.2", GIT),
        ("24.21.0", NODE),
        ("3.14.8", PYTHON),
        ("0.12.23", UV),
    ]
    by_id = {t["id"]: t for t in tools}
    # The build details uv prints after its version stay visible in `raw`.
    assert (
        by_id["uv"]["active"]["raw"] == "uv 0.12.23 (46b84fd0b 2026-10-03 x86_64-pc-windows-msvc)"
    )
    assert by_id["node"]["active"]["raw"] == "v24.21.0"


def test_mixed_statuses_are_each_reported_without_hiding_the_others(monkeypatch) -> None:
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    system = with_store_placeholders(core_four())
    system.env["PATH"] = system.env["PATH"].replace(r"C:\Program Files\Python314", WINDOWS_APPS)
    # Real output of a version command rejecting its arguments, replayed as node's.
    failing = load_capture("git/windows-git-badflag-unknown-version.json").result
    system.add_executable(NODE, Capture(("--version",), failing))
    # A hang has no output to capture; this is what the real runner reports.
    system.add_executable(
        UV,
        Capture(
            ("--version",), ProcessResult(exit_code=None, stdout=b"", stderr=b"", timed_out=True)
        ),
    )

    tools = tools_of(run_cli(system, "list", "--json"))
    table = run_cli(system, "list").stdout

    assert {i: t["status"] for i, t in tools.items()} == {
        "git": "found",
        "node": "error",
        "python": "missing",
        "uv": "timeout",
    }
    assert tools["node"]["notes"][0].startswith(f"{NODE} exited with code 129")
    assert tools["uv"]["notes"] == [f"{UV} did not answer within 5 s"]
    rows = {line.split()[0]: line for line in table.splitlines() if line.strip()}
    assert "2.55.0.windows.2" in rows["git"]
    assert "error" in rows["node"]
    assert "missing" in rows["python"]
    assert "timeout" in rows["uv"]


def test_every_python_on_path_is_listed_once_in_path_order() -> None:
    system = windows(
        r"C:\Python313",
        r"C:\Program Files\Python314",
        r"c:\python313\\",
        r"C:\Program Files\Python314",
    )
    system.add_executable(r"C:\Python313\python.exe", load_capture(PYTHON_313_WINDOWS))
    system.add_executable(PYTHON, load_capture(PYTHON_314_WINDOWS))

    python = tools_of(run_cli(system, "show", "python", "--json"))["python"]

    assert python["active"]["path"] == r"C:\Python313\python.exe"
    assert [(i["version"], i["path"]) for i in python["installs"]] == [
        ("3.13.16", r"C:\Python313\python.exe"),
        ("3.14.8", PYTHON),
    ]


def test_python3_is_found_when_no_python_command_exists() -> None:
    # Store Python and most Linux machines offer only `python3`.
    system = windows(r"C:\Tools\py")
    system.add_executable(r"C:\Tools\py\python3.exe", load_capture(PYTHON_314_WINDOWS))

    python = tools_of(run_cli(system, "list", "--json"))["python"]

    assert python["active"]["path"] == r"C:\Tools\py\python3.exe"


WINDOWS_APPS = r"C:\Users\dev\AppData\Local\Microsoft\WindowsApps"
STORE_PYTHON = rf"{WINDOWS_APPS}\python.exe"
STORE_PYTHON3 = rf"{WINDOWS_APPS}\python3.exe"


def with_store_placeholders(system: FakeSystem) -> FakeSystem:
    system.add_app_execution_alias(STORE_PYTHON, STORE_PYTHON_PLACEHOLDER)
    system.add_app_execution_alias(STORE_PYTHON3, STORE_PYTHON_PLACEHOLDER)
    return system


def placeholder_note(path: str) -> str:
    return (
        f"{path} is a Microsoft Store placeholder, not an install"
        " (it only offers to install Python from the Store); it was not run"
    )


def test_store_placeholders_alone_mean_python_is_missing_and_are_never_run() -> None:
    system = with_store_placeholders(windows(WINDOWS_APPS))

    python = tools_of(run_cli(system, "list", "--json"))["python"]

    assert (python["status"], python["active"], python["installs"]) == ("missing", None, [])
    assert python["notes"] == [
        "only Microsoft Store placeholders found on PATH (looked for: python, python3)",
        placeholder_note(STORE_PYTHON),
        placeholder_note(STORE_PYTHON3),
    ]
    # Running a placeholder can open the Store; it must not even be tried.
    assert system.runs == []


def test_a_real_python_after_the_placeholders_is_active_and_they_stay_noted() -> None:
    system = with_store_placeholders(core_four())
    system.env["PATH"] += f";{WINDOWS_APPS}"

    python = tools_of(run_cli(system, "list", "--json"))["python"]

    assert python["status"] == "found"
    assert [i["path"] for i in python["installs"]] == [PYTHON]
    assert python["active"]["version"] == "3.14.8"
    assert python["notes"] == [placeholder_note(STORE_PYTHON), placeholder_note(STORE_PYTHON3)]
    assert (STORE_PYTHON, "--version") not in system.runs
    assert (STORE_PYTHON3, "--version") not in system.runs


def test_a_placeholder_earlier_on_path_is_named_as_what_typing_the_command_runs() -> None:
    system = with_store_placeholders(core_four())
    system.env["PATH"] = f"{WINDOWS_APPS};{system.env['PATH']}"

    python = tools_of(run_cli(system, "list", "--json"))["python"]

    assert python["active"]["path"] == PYTHON
    assert python["notes"] == [
        placeholder_note(STORE_PYTHON)
        + f", but it comes first on PATH, so typing `python` runs it instead of {PYTHON}",
        # Typing `python3` finds no real install to hide.
        placeholder_note(STORE_PYTHON3),
    ]


def test_store_placeholder_notes_reach_the_human_output(monkeypatch) -> None:
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    system = with_store_placeholders(windows(WINDOWS_APPS))

    listed = run_cli(system, "list").stdout.splitlines()
    shown = run_cli(system, "show", "python").stdout.splitlines()

    # `list` stays one row per tool; `show` is where the explanation is read.
    assert "missing" in next(line for line in listed if line.startswith("python "))
    assert "missing" in next(line for line in shown if line.startswith("python "))
    assert f"python: {placeholder_note(STORE_PYTHON)}" in shown
    assert f"python: {placeholder_note(STORE_PYTHON3)}" in shown


# An alias whose data could not be read: what the real system reports when the
# reparse point cannot be opened or holds a layout it does not know.
UNREADABLE = UnreadableAlias(reason="could not open it: Windows error 5")


def test_an_unreadable_python_alias_is_treated_as_a_placeholder_and_not_run() -> None:
    system = windows(WINDOWS_APPS)
    system.add_app_execution_alias(STORE_PYTHON, UNREADABLE)

    python = tools_of(run_cli(system, "list", "--json"))["python"]

    assert (python["status"], python["active"]) == ("missing", None)
    assert python["notes"] == [
        "only Microsoft Store placeholders found on PATH (looked for: python, python3)",
        f"{STORE_PYTHON} is an App Execution Alias whose data could not be read"
        " (could not open it: Windows error 5), so it is treated as a Microsoft Store"
        " placeholder; it was not run",
    ]
    assert system.runs == []


def test_an_unreadable_alias_for_another_command_is_still_run() -> None:
    system = windows(WINDOWS_APPS)
    system.add_app_execution_alias(rf"{WINDOWS_APPS}\uv.exe", UNREADABLE, load_capture(UV_WINDOWS))

    uv = tools_of(run_cli(system, "list", "--json"))["uv"]

    assert (uv["status"], uv["active"]["version"]) == ("found", "0.12.23")


def test_other_app_execution_aliases_still_run_even_from_the_same_package() -> None:
    # winget's alias belongs to the same App Installer package as the Python
    # placeholder. With no winget definition, it stands in as `uv` (real uv
    # output): what matters is that a non-placeholder alias is run normally.
    system = windows(WINDOWS_APPS)
    system.add_app_execution_alias(
        rf"{WINDOWS_APPS}\uv.exe", WINGET_ALIAS, load_capture(UV_WINDOWS)
    )

    uv = tools_of(run_cli(system, "list", "--json"))["uv"]

    assert (uv["status"], uv["active"]["path"]) == ("found", rf"{WINDOWS_APPS}\uv.exe")


# Where the app keeps the environment VersionBar itself runs in; `uv run`
# puts its Scripts folder first on PATH for the core's process.
RUNTIME_SCRIPTS = r"C:\Users\dev\AppData\Local\VersionBar\.venv\Scripts"
RUNTIME_PYTHON = rf"{RUNTIME_SCRIPTS}\python.exe"


def launched_by_uv(system: FakeSystem) -> FakeSystem:
    system.env["PATH"] = f"{RUNTIME_SCRIPTS};{system.env['PATH']}"
    system.runtime_dirs = [RUNTIME_SCRIPTS]
    # Real output of the uv-managed 3.14 the environment is built on.
    system.add_executable(RUNTIME_PYTHON, load_capture(PYTHON_314_WINDOWS))
    return system


def test_the_python_running_versionbar_never_stands_in_for_a_missing_python() -> None:
    system = launched_by_uv(with_store_placeholders(windows(WINDOWS_APPS)))

    python = tools_of(run_cli(system, "list", "--json"))["python"]

    assert (python["status"], python["active"]) == ("missing", None)
    assert all(RUNTIME_SCRIPTS not in note for note in python["notes"])
    assert system.runs == []


def test_the_users_own_python_is_active_however_versionbar_was_launched() -> None:
    system = with_store_placeholders(windows(r"C:\Python313", WINDOWS_APPS))
    system.add_executable(r"C:\Python313\python.exe", load_capture(PYTHON_313_WINDOWS))
    launched_by_uv(system)

    python = tools_of(run_cli(system, "list", "--json"))["python"]

    assert [(i["version"], i["path"]) for i in python["installs"]] == [
        ("3.13.16", r"C:\Python313\python.exe")
    ]


def test_the_runtime_folder_is_recognised_whatever_its_spelling_on_path() -> None:
    system = launched_by_uv(with_store_placeholders(windows(WINDOWS_APPS)))
    system.env["PATH"] = system.env["PATH"].replace(RUNTIME_SCRIPTS, RUNTIME_SCRIPTS.lower() + "\\")

    python = tools_of(run_cli(system, "list", "--json"))["python"]

    assert python["status"] == "missing"
