"""The M1 core four (git, node, python, uv) on Windows, through the CLI seam."""

import json

from typer.testing import CliRunner

from versionbar.cli import app

from fakes import (
    GIT_WINDOWS,
    NODE_WINDOWS,
    PYTHON_313_WINDOWS,
    PYTHON_314_WINDOWS,
    STORE_PYTHON_PLACEHOLDER,
    UV_WINDOWS,
    WINDOWS_PATHEXT,
    WINGET_ALIAS,
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
