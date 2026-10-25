"""JS tools and managers (ticket 13) on Windows, through the CLI seam."""

import json

from fakes import WINDOWS_PATHEXT, FakeSystem, load_capture, run_cli

NVM_HOME = r"C:\Users\dev\AppData\Local\nvm"
NODEJS = rf"{NVM_HOME}\.nodejs"


def js_machine() -> FakeSystem:
    system = FakeSystem(
        os="windows",
        env={
            "PATH": rf"C:\WINDOWS\system32;{NVM_HOME};{NODEJS}",
            "PATHEXT": WINDOWS_PATHEXT,
            "NVM_HOME": NVM_HOME,
        },
    )
    system.add_executable(rf"{NVM_HOME}\nvm.exe", load_capture("nvm/windows-nvm-2.0.1.json"))
    system.add_executable(rf"{NODEJS}\npm.exe", load_capture("npm/windows-npm-11.19.0.json"))
    return system


def test_npm_and_nvm_report_the_versions_the_tools_printed() -> None:
    result = run_cli(js_machine(), "list", "--json")

    assert result.exit_code == 0, result.output
    tools = {t["id"]: t for t in json.loads(result.stdout)["tools"]}
    assert (tools["npm"]["status"], tools["npm"]["active"]["version"]) == ("found", "11.19.0")
    assert (tools["nvm"]["status"], tools["nvm"]["active"]["version"]) == ("found", "2.0.1")
    assert tools["nvm"]["active"]["raw"] == "v2.0.1"
    assert tools["npm"]["active"]["path"] == rf"{NODEJS}\npm.exe"
