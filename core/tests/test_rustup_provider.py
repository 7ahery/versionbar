"""The rustup toolchain provider, through the CLI seam.

rustup is never run: the toolchains are the folders under `<RUSTUP_HOME>\\toolchains`.
Machine state (folders, environment) is synthetic; version output is the real
rustc and cargo captures.
"""

import json

from fakes import (
    CARGO_WINDOWS,
    RUSTC_WINDOWS,
    WINDOWS_PATHEXT,
    FakeSystem,
    load_capture,
    run_cli,
)

CARGO_BIN = r"C:\Users\dev\.cargo\bin"
RUSTUP_HOME = r"C:\Users\dev\.rustup"
TOOLCHAINS = rf"{RUSTUP_HOME}\toolchains"
STABLE = rf"{TOOLCHAINS}\stable-x86_64-pc-windows-msvc"
PINNED = rf"{TOOLCHAINS}\1.99.1-x86_64-pc-windows-msvc"
RUSTC_NOT_FOUND = "not found on PATH (looked for: rustc)"


def machine(*, home: str = RUSTUP_HOME, pinned_cargo: bool = True) -> FakeSystem:
    """Two toolchains under `home`; the proxies in the cargo bin folder are not on PATH."""
    system = FakeSystem(
        os="windows",
        env={
            "PATH": r"C:\WINDOWS\system32",
            "PATHEXT": WINDOWS_PATHEXT,
            "USERPROFILE": r"C:\Users\dev",
        },
    )
    for toolchain in ("stable-x86_64-pc-windows-msvc", "1.99.1-x86_64-pc-windows-msvc"):
        folder = rf"{home}\toolchains\{toolchain}"
        system.add_executable(rf"{folder}\bin\rustc.exe", load_capture(RUSTC_WINDOWS))
        if pinned_cargo or toolchain.startswith("stable"):
            system.add_executable(rf"{folder}\bin\cargo.exe", load_capture(CARGO_WINDOWS))
    return system


def tool_of(system: FakeSystem, tool: str) -> dict:
    result = run_cli(system, "show", tool, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["tools"][0]


def installs(tool: dict) -> list[tuple[str, str, str]]:
    return [(i["version"], i["path"], i["source"]) for i in tool["installs"]]


def test_every_toolchain_is_a_rustc_and_a_cargo_install_with_source_rustup() -> None:
    system = machine()

    rustc = tool_of(system, "rustc")
    cargo = tool_of(system, "cargo")

    # Folder order: 1.99.1 sorts before stable.
    assert rustc["active"] is None
    assert installs(rustc) == [
        ("1.99.1", rf"{PINNED}\bin\rustc.exe", "rustup"),
        ("1.99.1", rf"{STABLE}\bin\rustc.exe", "rustup"),
    ]
    assert installs(cargo) == [
        ("1.99.1", rf"{PINNED}\bin\cargo.exe", "rustup"),
        ("1.99.1", rf"{STABLE}\bin\cargo.exe", "rustup"),
    ]


def test_rustup_itself_is_never_run() -> None:
    system = machine()
    system.add_executable(rf"{CARGO_BIN}\rustup.exe")
    system.env["PATH"] += f";{CARGO_BIN}"

    tool_of(system, "rustc")

    assert all(not run[0].lower().endswith("rustup.exe") for run in system.runs)


def test_rustup_home_from_the_environment_wins_over_the_default() -> None:
    elsewhere = r"D:\rust\home"
    system = machine(home=elsewhere)
    system.env["RUSTUP_HOME"] = f'"{elsewhere}"'

    paths = [i[1] for i in installs(tool_of(system, "rustc"))]

    assert paths and all(p.startswith(elsewhere) for p in paths)


def test_without_rustup_home_the_default_under_the_user_profile_is_read() -> None:
    assert len(installs(tool_of(machine(), "rustc"))) == 2


def test_a_relative_rustup_home_is_ignored() -> None:
    system = machine()
    system.env["RUSTUP_HOME"] = r"rust\home"

    assert tool_of(system, "rustc")["installs"] == []


def test_a_proxy_on_path_stays_active_and_toolchains_are_added_after_it() -> None:
    system = machine()
    system.add_executable(rf"{CARGO_BIN}\rustc.exe", load_capture(RUSTC_WINDOWS))
    system.env["PATH"] += f";{CARGO_BIN}"

    rustc = tool_of(system, "rustc")

    assert rustc["active"]["path"] == rf"{CARGO_BIN}\rustc.exe"
    assert [i[2] for i in installs(rustc)] == ["path", "rustup", "rustup"]


def test_a_toolchain_that_is_also_on_path_is_listed_once() -> None:
    system = machine()
    system.env["PATH"] += rf";{STABLE}\bin"

    rustc = tool_of(system, "rustc")

    assert installs(rustc) == [
        ("1.99.1", rf"{STABLE}\bin\rustc.exe", "path"),
        ("1.99.1", rf"{PINNED}\bin\rustc.exe", "rustup"),
    ]
    assert system.runs.count((rf"{STABLE}\bin\rustc.exe", "--version")) == 1


def test_no_rustup_home_folder_adds_nothing_and_says_nothing() -> None:
    system = machine()
    system.env["RUSTUP_HOME"] = r"D:\missing"
    system.env.pop("USERPROFILE")

    rustc = tool_of(system, "rustc")

    assert rustc["installs"] == []
    assert rustc["notes"] == [RUSTC_NOT_FOUND]


def test_an_empty_toolchains_folder_adds_nothing() -> None:
    system = machine()
    system.env["RUSTUP_HOME"] = r"D:\empty"
    system.add_folder(r"D:\empty\toolchains")

    rustc = tool_of(system, "rustc")

    assert rustc["installs"] == []
    assert rustc["notes"] == [RUSTC_NOT_FOUND]


def test_an_unreadable_toolchains_folder_is_a_note_and_loses_nothing_else() -> None:
    system = machine()
    system.env["RUSTUP_HOME"] = r"D:\locked"
    system.add_unlistable(r"D:\locked\toolchains", "access denied")

    rustc = tool_of(system, "rustc")

    assert rustc["installs"] == []
    assert rustc["notes"][-1].startswith("rustup: could not list installs: ")


def test_a_toolchain_without_the_tool_is_a_note_and_the_other_still_counts() -> None:
    cargo = tool_of(machine(pinned_cargo=False), "cargo")

    assert installs(cargo) == [("1.99.1", rf"{STABLE}\bin\cargo.exe", "rustup")]
    assert cargo["notes"][-1] == f"rustup: {PINNED} has no bin\\cargo.exe, so it is not an install"


def test_rustup_is_listed_as_a_windows_provider_of_rustc_and_cargo() -> None:
    result = run_cli(machine(), "tools", "--json")

    [rustup] = [p for p in json.loads(result.stdout)["providers"] if p["id"] == "rustup"]
    assert (rustup["name"], rustup["os"], rustup["tools"]) == (
        "rustup",
        ["windows"],
        ["rustc", "cargo"],
    )
