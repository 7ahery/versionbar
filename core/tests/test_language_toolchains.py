"""Language toolchain definitions (ticket 14) on Windows, through the CLI seam."""

import json

from fakes import WINDOWS_PATHEXT, FakeSystem, load_capture, run_cli

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
