"""Language toolchain definitions (ticket 14) on Windows, through the CLI seam."""

import json

from fakes import WINDOWS_PATHEXT, Capture, FakeSystem, load_capture, run_cli

BIN = r"C:\Users\dev\.cargo\bin"


def rust_machine() -> FakeSystem:
    system = FakeSystem(
        os="windows",
        env={"PATH": rf"C:\WINDOWS\system32;{BIN}", "PATHEXT": WINDOWS_PATHEXT},
    )
    system.add_executable(rf"{BIN}\rustc.exe", load_capture("rustc/windows-rustc-1.99.1.json"))
    system.add_executable(rf"{BIN}\cargo.exe", load_capture("cargo/windows-cargo-1.99.1.json"))
    system.add_executable(rf"{BIN}\rustup.exe", load_capture("rustup/windows-rustup-1.29.1.json"))
    return system


def test_rust_toolchain_tools_report_versions_from_real_captures() -> None:
    result = run_cli(rust_machine(), "list", "--json")

    assert result.exit_code == 0, result.output
    tools = {t["id"]: t for t in json.loads(result.stdout)["tools"]}
    assert {
        i: (tools[i]["status"], tools[i]["active"]["version"])
        for i in tools
        if i in ("rustc", "cargo", "rustup")
    } == {
        "rustc": ("found", "1.99.1"),
        "cargo": ("found", "1.99.1"),
        "rustup": ("found", "1.29.1"),
    }
    assert tools["rustc"]["active"]["raw"] == "rustc 1.99.1 (58cf8f9c3 2026-10-13)"
    assert tools["rustup"]["active"]["path"] == rf"{BIN}\rustup.exe"


def test_tools_without_an_install_are_missing() -> None:
    result = run_cli(rust_machine(), "list", "--json")

    tools = {t["id"]: t for t in json.loads(result.stdout)["tools"]}
    for tool_id in ("java", "go", "dotnet", "ruby", "php", "composer"):
        assert tools[tool_id]["status"] == "missing", tool_id


CAPTURES = {
    "java": ("java.exe", "java/windows-java-17.0.20.1.json", "17.0.20.1"),
    "go": ("go.exe", "go/windows-go-1.24.13.json", "1.24.13"),
    "dotnet": ("dotnet.exe", "dotnet/windows-dotnet-10.0.402.json", "10.0.402"),
    "ruby": ("ruby.exe", "ruby/windows-ruby-3.3.12.json", "3.3.12"),
    "php": ("php.exe", "php/windows-php-8.5.11.json", "8.5.11"),
    # A wrapper: runs through cmd.exe, and the PHP notice on stderr must not hide the version.
    "composer": ("composer.bat", "composer/windows-composer-2.10.3.json", "2.10.3"),
}
TOOLS_DIR = r"C:\tools"


def toolchain_machine() -> FakeSystem:
    system = FakeSystem(
        os="windows",
        env={"PATH": rf"C:\WINDOWS\system32;{TOOLS_DIR}", "PATHEXT": WINDOWS_PATHEXT},
    )
    for file_name, capture, _ in CAPTURES.values():
        system.add_executable(rf"{TOOLS_DIR}\{file_name}", load_capture(capture))
    return system


def test_every_captured_toolchain_reports_the_version_the_tool_printed() -> None:
    result = run_cli(toolchain_machine(), "list", "--json")

    assert result.exit_code == 0, result.output
    tools = {t["id"]: t for t in json.loads(result.stdout)["tools"]}
    assert {i: (tools[i]["status"], tools[i]["active"]["version"]) for i in CAPTURES} == {
        i: ("found", version) for i, (_, _, version) in CAPTURES.items()
    }
    assert tools["java"]["active"]["raw"].startswith('openjdk version "17.0.20.1"')
    assert tools["composer"]["active"]["path"] == rf"{TOOLS_DIR}\composer.bat"


def test_two_java_installs_on_path_are_both_listed_first_active() -> None:
    system = toolchain_machine()
    system.env["PATH"] = rf"C:\WINDOWS\system32;{TOOLS_DIR};C:\other"
    # Same real output at a second path: only the placement is synthetic.
    system.add_executable(r"C:\other\java.exe", load_capture(CAPTURES["java"][1]))

    result = run_cli(system, "show", "java", "--json")

    java = json.loads(result.stdout)["tools"][0]
    assert [i["path"] for i in java["installs"]] == [rf"{TOOLS_DIR}\java.exe", r"C:\other\java.exe"]
    assert java["active"]["path"] == rf"{TOOLS_DIR}\java.exe"


def test_a_failing_version_command_is_an_error_not_a_version() -> None:
    system = toolchain_machine()
    failing = load_capture("git/windows-git-badflag-unknown-version.json").result
    system.add_executable(rf"{TOOLS_DIR}\go.exe", Capture(("version",), failing))

    tools = {t["id"]: t for t in json.loads(run_cli(system, "list", "--json").stdout)["tools"]}

    assert tools["go"]["status"] == "error"
    assert tools["java"]["status"] == "found"
