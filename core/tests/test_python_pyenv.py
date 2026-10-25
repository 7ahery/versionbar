"""pyenv attribution on the python definition (ticket 09), through the CLI seam.

The shim paths are synthetic (no pyenv machine was available); the replayed
output is a real python capture.
"""

import json

from fakes import PYTHON_314_WINDOWS, WINDOWS_PATHEXT, FakeSystem, load_capture, run_cli


def python_tool(system: FakeSystem) -> dict:
    result = run_cli(system, "list", "--json")
    assert result.exit_code == 0, result.output
    tools = {t["id"]: t for t in json.loads(result.stdout)["tools"]}
    return tools["python"]


def machine(path: str, python: str, **env: str) -> FakeSystem:
    system = FakeSystem(
        os="windows",
        env={"PATH": rf"C:\WINDOWS\system32;{path}", "PATHEXT": WINDOWS_PATHEXT, **env},
    )
    system.add_executable(python, load_capture(PYTHON_314_WINDOWS))
    return system


def test_a_plain_install_has_no_manager() -> None:
    tool = python_tool(machine(r"C:\Python314", r"C:\Python314\python.exe"))

    assert tool["active"]["via"] is None


def test_pyenv_win_shim_is_attributed_through_the_pyenv_variable() -> None:
    shims = r"C:\Users\dev\.pyenv\pyenv-win\shims"
    system = machine(shims, rf"{shims}\python.bat", PYENV=r"C:\Users\dev\.pyenv\pyenv-win")
    tool = python_tool(system)

    assert (tool["active"]["via"], tool["active"]["source"]) == ("pyenv", "path")
    assert tool["active"]["version"] == "3.14.8"


def test_pyenv_in_a_nonstandard_location_is_found_by_its_variable() -> None:
    shims = r"D:\tools\pyenv\shims"
    system = machine(shims, rf"{shims}\python.bat", PYENV_ROOT=r"D:\tools\pyenv")

    assert python_tool(system)["active"]["via"] == "pyenv"


def test_a_folder_that_only_looks_like_pyenv_is_not_tagged() -> None:
    shims = r"D:\tools\pyenv\shims"
    system = machine(shims, rf"{shims}\python.bat")

    assert python_tool(system)["active"]["via"] is None


def test_pyenv_home_variable_also_locates_pyenv_win() -> None:
    shims = r"E:\pyenv-win\shims"
    system = machine(shims, rf"{shims}\python.bat", PYENV_HOME=r"E:\pyenv-win")

    assert python_tool(system)["active"]["via"] == "pyenv"
