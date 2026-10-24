"""The M1 core four (git, node, python, uv) on Windows, through the CLI seam."""

import json

from typer.testing import CliRunner

from versionbar.cli import app

from fakes import (
    GIT_WINDOWS,
    NODE_WINDOWS,
    PYTHON_313_WINDOWS,
    PYTHON_314_WINDOWS,
    UV_WINDOWS,
    WINDOWS_PATHEXT,
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
    assert by_id["uv"]["active"]["raw"] == "uv 0.12.23 (46b84fd0b 2026-10-03 x86_64-pc-windows-msvc)"
    assert by_id["node"]["active"]["raw"] == "v24.21.0"
