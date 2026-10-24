"""Shim attribution (`via`) and batch wrappers, through the CLI seam.

The rules are definition data. Ecosystem definitions (pyenv, volta, corepack)
belong to their own tickets, so these tests attach rules to the built-in node
and python definitions, which is exactly what those definitions will do. The
version output is always a real capture; PATH, environment and file contents
are synthetic machine state.
"""

import json

import pytest

from versionbar import cli, definition
from versionbar.definition import ToolDefinition

from fakes import (
    NODE_WINDOWS,
    PYTHON_313_WINDOWS,
    PYTHON_314_WINDOWS,
    WINDOWS_PATHEXT,
    FakeSystem,
    load_capture,
    run_cli,
)

PYENV = r"C:\Users\dev\.pyenv\pyenv-win"
PYENV_SHIM = rf"{PYENV}\shims\python.bat"
PLAIN_PYTHON = r"C:\Program Files\Python313\python.exe"


def with_rules(monkeypatch, tool_id: str, **fields: object) -> None:
    """Replace the built-ins with copies where `tool_id` carries extra TOML keys.

    Goes through `model_validate`, the loader built-in TOML goes through, so
    the rules are checked exactly as a definition file's would be.
    """
    builtins = definition.builtin_definitions()

    def patched() -> list[ToolDefinition]:
        return [
            ToolDefinition.model_validate({**d.model_dump(), **fields}) if d.id == tool_id else d
            for d in builtins
        ]

    monkeypatch.setattr(cli, "builtin_definitions", patched)


def windows(path: list[str], **env: str) -> FakeSystem:
    return FakeSystem(
        os="windows", env={"PATH": ";".join(path), "PATHEXT": WINDOWS_PATHEXT, **env}
    )


def tool(system: FakeSystem, tool_id: str) -> dict:
    result = run_cli(system, "show", tool_id, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["tools"][0]


def pyenv_machine(**env: str) -> FakeSystem:
    # The pyenv shim comes first, so it is what `python` runs.
    system = windows([rf"{PYENV}\shims", r"C:\Program Files\Python313"], **env)
    system.add_executable(PYENV_SHIM, load_capture(PYTHON_314_WINDOWS))
    system.add_executable(PLAIN_PYTHON, load_capture(PYTHON_313_WINDOWS))
    return system


PYENV_RULE = {"manager": "pyenv", "dirs": ["{PYENV}/shims", "{PYENV_ROOT}/shims"]}


def test_an_install_in_a_manager_folder_is_tagged_and_keeps_its_place(monkeypatch) -> None:
    with_rules(monkeypatch, "python", via=[PYENV_RULE])

    python = tool(pyenv_machine(PYENV=PYENV + "\\"), "python")

    assert [(i["path"], i["version"], i["source"], i["via"]) for i in python["installs"]] == [
        (PYENV_SHIM, "3.14.8", "path", "pyenv"),
        (PLAIN_PYTHON, "3.13.16", "path", None),
    ]
    assert python["active"] == python["installs"][0]


def test_a_manager_in_a_nonstandard_folder_is_found_through_its_environment(monkeypatch) -> None:
    with_rules(monkeypatch, "python", via=[PYENV_RULE])
    # Moved to another drive and named only by the fallback variable, which is
    # quoted and spelt with other case and separators than PATH: same folder.
    system = windows([r"d:\tools\pyenv\shims", r"C:\Program Files\Python313"])
    system.env["PYENV_ROOT"] = '"D:/Tools/PyEnv/"'
    system.add_executable(r"D:\tools\pyenv\shims\python.bat", load_capture(PYTHON_314_WINDOWS))
    system.add_executable(PLAIN_PYTHON, load_capture(PYTHON_313_WINDOWS))

    python = tool(system, "python")

    assert [i["via"] for i in python["installs"]] == ["pyenv", None]


@pytest.mark.parametrize(
    "env", [{}, {"PYENV": ""}, {"PYENV": "pyenv-win"}], ids=["unset", "empty", "relative"]
)
def test_a_manager_folder_is_never_assumed_without_its_variable(monkeypatch, env) -> None:
    # The shim sits where pyenv-win puts it by default, but nothing says pyenv
    # is installed there, so the install is reported untagged.
    with_rules(monkeypatch, "python", via=[PYENV_RULE])

    python = tool(pyenv_machine(**env), "python")

    assert [(i["path"], i["via"]) for i in python["installs"]] == [
        (PYENV_SHIM, None),
        (PLAIN_PYTHON, None),
    ]


NODE_DIR = r"C:\Program Files\nodejs"
TAGGED_SHIM = r"C:\Users\dev\AppData\Roaming\npm\node.cmd"
UNTAGGED_SHIM = r"C:\tools\node.cmd"
# Synthetic shim scripts (file contents are machine state): the first carries
# the marker its manager writes into every shim it generates, the second is a
# hand-written wrapper that only looks similar.
TAGGED_CONTENT = b'@ECHO off\r\n"%~dp0\\node_modules\\shimmgr\\dist\\node.js" %*\r\n'
UNTAGGED_CONTENT = b'@ECHO off\r\n"C:\\Program Files\\nodejs\\node.exe" %*\r\n'
CONTENT_RULE = {"manager": "shimmgr", "content_regex": r"node_modules[\\/]shimmgr[\\/]"}


def shim_machine(*, readable: bool = True) -> FakeSystem:
    system = windows([r"C:\Users\dev\AppData\Roaming\npm", r"C:\tools", NODE_DIR])
    node = load_capture(NODE_WINDOWS)
    system.add_executable(TAGGED_SHIM, node)
    system.add_executable(UNTAGGED_SHIM, node)
    system.add_executable(rf"{NODE_DIR}\node.exe", node)
    if not readable:
        return system
    system.add_content(TAGGED_SHIM, TAGGED_CONTENT)
    system.add_content(UNTAGGED_SHIM, UNTAGGED_CONTENT)
    system.add_content(rf"{NODE_DIR}\node.exe", b"MZ\x90\x00")
    return system


def test_a_shim_is_recognised_by_what_its_manager_writes_into_it(monkeypatch) -> None:
    with_rules(monkeypatch, "node", via=[CONTENT_RULE])

    node = tool(shim_machine(), "node")

    assert [(i["path"], i["via"]) for i in node["installs"]] == [
        (TAGGED_SHIM, "shimmgr"),
        (UNTAGGED_SHIM, None),
        (rf"{NODE_DIR}\node.exe", None),
    ]


def test_an_unreadable_file_is_left_untagged_and_still_reported(monkeypatch) -> None:
    with_rules(monkeypatch, "node", via=[CONTENT_RULE])
    node = tool(shim_machine(readable=False), "node")

    assert [(i["version"], i["via"]) for i in node["installs"]] == [("24.21.0", None)] * 3


def test_a_rule_with_folders_and_content_needs_both(monkeypatch) -> None:
    # The marker alone is not enough when the manager also names its folder:
    # the tagged script outside that folder is someone's copy.
    rule = {**CONTENT_RULE, "dirs": ["{SHIMMGR_HOME}"]}
    with_rules(monkeypatch, "node", via=[rule])
    system = shim_machine()
    system.env["SHIMMGR_HOME"] = r"C:\tools"
    system.add_content(UNTAGGED_SHIM, TAGGED_CONTENT)

    node = tool(system, "node")

    assert [i["via"] for i in node["installs"]] == [None, "shimmgr", None]


def test_the_first_matching_rule_names_the_manager(monkeypatch) -> None:
    with_rules(
        monkeypatch,
        "node",
        via=[
            {"manager": "first", "dirs": ["{APPDATA}/npm"]},
            {"manager": "second", "content_regex": "shimmgr"},
        ],
    )
    system = shim_machine()
    system.env["APPDATA"] = r"C:\Users\dev\AppData\Roaming"

    node = tool(system, "node")

    assert [i["via"] for i in node["installs"]] == ["first", None, None]


def test_an_os_override_replaces_the_rules(monkeypatch) -> None:
    # pyenv-win names its root PYENV; on Linux pyenv uses PYENV_ROOT.
    with_rules(
        monkeypatch,
        "python",
        via=[{"manager": "pyenv", "dirs": ["{PYENV_ROOT}/shims"]}],
        overrides={"windows": {"via": [{"manager": "pyenv-win", "dirs": ["{PYENV}/shims"]}]}},
    )

    python = tool(pyenv_machine(PYENV=PYENV, PYENV_ROOT=PYENV), "python")

    assert [i["via"] for i in python["installs"]] == ["pyenv-win", None]


def test_human_show_names_the_manager_beside_the_source(monkeypatch) -> None:
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    with_rules(monkeypatch, "python", via=[PYENV_RULE])

    result = run_cli(pyenv_machine(PYENV=PYENV), "show", "python")

    assert result.exit_code == 0, result.output
    shim_line = next(line for line in result.stdout.splitlines() if PYENV_SHIM in line)
    assert shim_line.rstrip().endswith("path via pyenv")


def test_a_batch_wrapper_is_an_install_like_a_plain_executable() -> None:
    # npm, code and pyenv shims are `.cmd`/`.bat` wrappers beside an
    # extensionless shell script for Git Bash. Windows runs the wrapper, so it
    # is the install reported, at the wrapper's own path; the script never is.
    system = windows([r"C:\Users\dev\AppData\Roaming\npm", NODE_DIR])
    node = load_capture(NODE_WINDOWS)
    system.add_executable(r"C:\Users\dev\AppData\Roaming\npm\node", node)
    system.add_executable(TAGGED_SHIM, node)
    system.add_executable(rf"{NODE_DIR}\node.exe", node)

    result = tool(system, "node")

    assert [(i["path"], i["version"]) for i in result["installs"]] == [
        (TAGGED_SHIM, "24.21.0"),
        (rf"{NODE_DIR}\node.exe", "24.21.0"),
    ]
    assert result["active"]["path"] == TAGGED_SHIM
    # Probes run in parallel, so only the set of commands is fixed.
    assert sorted(system.runs) == sorted(
        [(TAGGED_SHIM, "--version"), (rf"{NODE_DIR}\node.exe", "--version")]
    )
