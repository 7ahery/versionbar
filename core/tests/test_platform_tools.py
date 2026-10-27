"""Hosting, shell and platform-manager definitions (ticket 15) on Windows, through the CLI seam."""

import json

from fakes import WINDOWS_PATHEXT, Capture, FakeSystem, load_capture, run_cli

TOOLS_DIR = r"C:\tools"
CODE_DIR = r"C:\Users\dev\AppData\Local\Programs\Microsoft VS Code\bin"

# id -> (file on disk, capture, version). `code` is a wrapper beside a shell script.
CAPTURES = {
    "gh": ("gh.exe", "gh/windows-gh-2.102.0.json", "2.102.0"),
    "pwsh": ("pwsh.exe", "pwsh/windows-pwsh-7.6.6.json", "7.6.6"),
    "winget": ("winget.exe", "winget/windows-winget-1.29.380.json", "1.29.380"),
    # WSL prints UTF-16; its raw bytes are decoded by the engine, not by the definition.
    "wsl": ("wsl.exe", "wsl/windows-wsl-2.7.12.0.json", "2.7.12.0"),
}


def machine() -> FakeSystem:
    system = FakeSystem(
        os="windows",
        env={"PATH": rf"C:\WINDOWS\system32;{TOOLS_DIR};{CODE_DIR}", "PATHEXT": WINDOWS_PATHEXT},
    )
    for file_name, capture, _ in CAPTURES.values():
        system.add_executable(rf"{TOOLS_DIR}\{file_name}", load_capture(capture))
    # Git Bash users get an extensionless script first on PATH; it cannot run on Windows.
    system.add_executable(rf"{CODE_DIR}\code")
    system.add_executable(rf"{CODE_DIR}\code.cmd", load_capture("code/windows-code-1.143.1.json"))
    return system


def listed(system: FakeSystem) -> dict[str, dict]:
    result = run_cli(system, "list", "--json")
    assert result.exit_code == 0, result.output
    return {t["id"]: t for t in json.loads(result.stdout)["tools"]}


def test_every_captured_tool_reports_the_version_the_tool_printed() -> None:
    tools = listed(machine())

    assert {i: (tools[i]["status"], tools[i]["active"]["version"]) for i in CAPTURES} == {
        i: ("found", version) for i, (_, _, version) in CAPTURES.items()
    }
    assert tools["gh"]["active"]["raw"].startswith("gh version 2.102.0 (2026-09-30)")
    assert tools["winget"]["active"]["raw"].strip() == "v1.29.380"
    assert tools["pwsh"]["active"]["raw"].strip() == "PowerShell 7.6.6"


def test_wsl_utf16_output_decodes_to_a_clean_version() -> None:
    wsl = listed(machine())["wsl"]["active"]

    assert wsl["version"] == "2.7.12.0"
    assert wsl["raw"].startswith("WSL version: 2.7.12.0")
    assert "\x00" not in wsl["raw"]


def test_code_resolves_to_its_cmd_wrapper_not_the_extensionless_script() -> None:
    code = listed(machine())["code"]

    assert code["status"] == "found"
    assert code["active"]["version"] == "1.143.1"
    assert code["active"]["path"] == rf"{CODE_DIR}\code.cmd"
    assert [i["path"] for i in code["installs"]] == [rf"{CODE_DIR}\code.cmd"]


def test_code_is_run_as_the_wrapper_with_a_plain_flag() -> None:
    system = machine()

    listed(system)

    # The System seam wraps `.cmd` files in cmd.exe (docs/definitions.md); the definition only
    # has to name a plain flag and resolve to the wrapper.
    assert (rf"{CODE_DIR}\code.cmd", "--version") in system.runs
    assert (rf"{CODE_DIR}\code", "--version") not in system.runs


def test_tools_without_an_install_are_missing() -> None:
    system = FakeSystem(
        os="windows", env={"PATH": r"C:\WINDOWS\system32", "PATHEXT": WINDOWS_PATHEXT}
    )

    tools = listed(system)

    for tool_id in ("gh", "pwsh", "code", "wsl", "winget"):
        assert tools[tool_id]["status"] == "missing", tool_id


def test_windows_only_managers_are_not_scanned_on_linux() -> None:
    system = FakeSystem(os="linux", env={"PATH": "/usr/bin"})

    tools = listed(system)

    for tool_id in ("wsl", "winget"):
        assert tool_id not in tools
    assert {"gh", "pwsh", "code"} <= set(tools)


def test_a_failing_version_command_is_an_error_not_a_version() -> None:
    system = machine()
    failing = load_capture("git/windows-git-badflag-unknown-version.json").result
    system.add_executable(rf"{TOOLS_DIR}\gh.exe", Capture(("--version",), failing))

    tools = listed(system)

    assert tools["gh"]["status"] == "error"
    assert tools["pwsh"]["status"] == "found"


def test_kubectl_reports_the_client_version_without_the_v_or_the_kustomize_line() -> None:
    system = machine()
    system.add_executable(
        rf"{TOOLS_DIR}\kubectl.exe", load_capture("kubectl/windows-kubectl-1.37.1.json")
    )

    kubectl = listed(system)["kubectl"]["active"]

    assert kubectl["version"] == "1.37.1"
    assert kubectl["raw"].startswith("Client Version: v1.37.1")


def test_choco_reports_its_bare_version() -> None:
    system = machine()
    system.add_executable(rf"{TOOLS_DIR}\choco.exe", load_capture("choco/windows-choco-2.7.4.json"))

    assert listed(system)["choco"]["active"]["version"] == "2.7.4"


def test_choco_is_not_scanned_on_linux() -> None:
    tools = listed(FakeSystem(os="linux", env={"PATH": "/usr/bin"}))

    assert "choco" not in tools
    assert "kubectl" in tools


def test_docker_version_drops_the_comma_before_the_build() -> None:
    system = machine()
    system.add_executable(
        rf"{TOOLS_DIR}\docker.exe", load_capture("docker/windows-docker-29.7.2.json")
    )

    docker = listed(system)["docker"]["active"]

    assert docker["version"] == "29.7.2"
    assert docker["raw"].startswith("Docker version 29.7.2, build ")
