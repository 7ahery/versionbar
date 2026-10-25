"""The rustup toolchain provider, through the CLI seam.

`rustup toolchain list -v` answers with a real capture (rustup 1.29.1, holding
the toolchains `stable` and `1.99.1`). Machine state (PATH, environment) is
synthetic; version output is the real rustc and cargo captures.
"""

import json

from versionbar.system import ProcessResult

from fakes import (
    CARGO_WINDOWS,
    RUSTC_WINDOWS,
    RUSTUP_TOOLCHAIN_LIST_WINDOWS,
    RUSTUP_WINDOWS,
    WINDOWS_PATHEXT,
    Capture,
    FakeSystem,
    load_capture,
    run_cli,
)

CARGO_HOME = r"C:\Users\dev\.cargo"
CARGO_BIN = rf"{CARGO_HOME}\bin"
RUSTUP = rf"{CARGO_BIN}\rustup.exe"
TOOLCHAINS = r"C:\Users\dev\.rustup\toolchains"
STABLE = rf"{TOOLCHAINS}\stable-x86_64-pc-windows-msvc"
PINNED = rf"{TOOLCHAINS}\1.99.1-x86_64-pc-windows-msvc"
LIST_ARGS = ("toolchain", "list", "-v")
RUSTC_NOT_FOUND = "not found on PATH (looked for: rustc)"


def machine(
    *, rustup_on_path: bool = True, listing: Capture | None = None, pinned_cargo: bool = True
) -> FakeSystem:
    """Two rustup toolchains; the proxies in the cargo bin folder are not on PATH."""
    path = [r"C:\WINDOWS\system32"] + ([CARGO_BIN] if rustup_on_path else [])
    system = FakeSystem(os="windows", env={"PATH": ";".join(path), "PATHEXT": WINDOWS_PATHEXT})
    system.add_executable(
        RUSTUP, load_capture(RUSTUP_WINDOWS), listing or load_capture(RUSTUP_TOOLCHAIN_LIST_WINDOWS)
    )
    for toolchain in (STABLE, PINNED):
        system.add_executable(rf"{toolchain}\bin\rustc.exe", load_capture(RUSTC_WINDOWS))
    system.add_executable(rf"{STABLE}\bin\cargo.exe", load_capture(CARGO_WINDOWS))
    if pinned_cargo:
        system.add_executable(rf"{PINNED}\bin\cargo.exe", load_capture(CARGO_WINDOWS))
    else:
        system.add_folder(rf"{PINNED}\bin")
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

    assert rustc["active"] is None
    assert installs(rustc) == [
        ("1.99.1", rf"{STABLE}\bin\rustc.exe", "rustup"),
        ("1.99.1", rf"{PINNED}\bin\rustc.exe", "rustup"),
    ]
    assert installs(cargo) == [
        ("1.99.1", rf"{STABLE}\bin\cargo.exe", "rustup"),
        ("1.99.1", rf"{PINNED}\bin\cargo.exe", "rustup"),
    ]


def test_a_proxy_on_path_stays_active_and_toolchains_are_added_after_it() -> None:
    system = machine()
    system.add_executable(rf"{CARGO_BIN}\rustc.exe", load_capture(RUSTC_WINDOWS))

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


def test_rustup_found_through_cargo_home_when_not_on_path() -> None:
    system = machine(rustup_on_path=False)
    system.env["CARGO_HOME"] = f'"{CARGO_HOME}"'

    assert [i[2] for i in installs(tool_of(system, "rustc"))] == ["rustup", "rustup"]


def test_without_rustup_nothing_is_added_and_nothing_is_said() -> None:
    rustc = tool_of(machine(rustup_on_path=False), "rustc")

    assert rustc["installs"] == []
    assert rustc["notes"] == [RUSTC_NOT_FOUND]


def test_no_toolchains_adds_nothing() -> None:
    empty = ProcessResult(exit_code=0, stdout=b"", stderr=b"")

    rustc = tool_of(machine(listing=Capture(LIST_ARGS, empty)), "rustc")

    assert rustc["installs"] == []
    assert rustc["notes"] == [RUSTC_NOT_FOUND]


def test_a_failing_listing_is_a_note_and_loses_nothing_else() -> None:
    for result in (
        ProcessResult(exit_code=1, stdout=b"", stderr=b""),
        ProcessResult(exit_code=0, stdout=b"\xff\xfe garbage \x00", stderr=b""),
        ProcessResult(exit_code=0, stdout=b"this is not a listing\n", stderr=b""),
        ProcessResult(exit_code=None, stdout=b"", stderr=b"", launch_error="access denied"),
        ProcessResult(exit_code=None, stdout=b"", stderr=b"", timed_out=True),
    ):
        rustc = tool_of(machine(listing=Capture(LIST_ARGS, result)), "rustc")

        assert rustc["installs"] == []
        assert rustc["notes"][0] == RUSTC_NOT_FOUND
        assert rustc["notes"][-1].startswith("rustup: could not list installs: ")


def test_a_hanging_listing_gives_up_after_the_tools_timeout() -> None:
    system = machine(listing=Capture(LIST_ARGS, ProcessResult(0, b"", b""), seconds=60))

    rustc = tool_of(system, "rustc")

    assert (
        rustc["notes"][-1]
        == "rustup: could not list installs: rustup toolchain list did not answer within 5 s"
    )


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
