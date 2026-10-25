"""pip and pipx (ticket 09) on Windows, through the CLI seam, from real runner captures."""

import json

from fakes import WINDOWS_PATHEXT, Capture, FakeSystem, load_capture, run_cli

SCRIPTS = r"C:\hostedtoolcache\windows\Python\3.12.10\x64\Scripts"


def machine() -> FakeSystem:
    system = FakeSystem(
        os="windows",
        env={"PATH": rf"C:\WINDOWS\system32;{SCRIPTS}", "PATHEXT": WINDOWS_PATHEXT},
    )
    system.add_executable(rf"{SCRIPTS}\pip.exe", load_capture("pip/windows-pip-26.2.2.json"))
    system.add_executable(rf"{SCRIPTS}\pipx.exe", load_capture("pipx/windows-pipx-1.18.4.json"))
    return system


def tools_of(system: FakeSystem) -> dict:
    result = run_cli(system, "list", "--json")
    assert result.exit_code == 0, result.output
    return {t["id"]: t for t in json.loads(result.stdout)["tools"]}


def test_pip_and_pipx_report_the_version_the_tool_printed() -> None:
    tools = tools_of(machine())

    assert (tools["pip"]["status"], tools["pip"]["active"]["version"]) == ("found", "26.2.2")
    assert (tools["pipx"]["status"], tools["pipx"]["active"]["version"]) == ("found", "1.18.4")
    assert tools["pipx"]["active"]["path"] == rf"{SCRIPTS}\pipx.exe"


def test_without_installs_they_are_missing() -> None:
    system = FakeSystem(
        os="windows", env={"PATH": r"C:\WINDOWS\system32", "PATHEXT": WINDOWS_PATHEXT}
    )
    tools = tools_of(system)

    assert tools["pip"]["status"] == "missing"
    assert tools["pipx"]["status"] == "missing"


def test_a_failing_pip_is_an_error() -> None:
    system = machine()
    failing = load_capture("git/windows-git-badflag-unknown-version.json").result
    system.add_executable(rf"{SCRIPTS}\pip.exe", Capture(("--version",), failing))

    assert tools_of(system)["pip"]["status"] == "error"
