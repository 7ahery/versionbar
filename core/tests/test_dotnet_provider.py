r"""The .NET SDK provider, through the CLI seam.

`dotnet --list-sdks` answers with a real capture from the windows-latest runner
(eleven SDKs under `C:\Program Files\dotnet\sdk`); `dotnet --version` is the
real capture of the host (10.0.402). Machine state (PATH, environment) is
synthetic.
"""

import json

from versionbar.system import ProcessResult

from fakes import WINDOWS_PATHEXT, Capture, FakeSystem, load_capture, run_cli

HOST_DIR = r"C:\Program Files\dotnet"
HOST = rf"{HOST_DIR}\dotnet.exe"
SDK_DIR = rf"{HOST_DIR}\sdk"
LIST_ARGS = ("--list-sdks",)
LISTING = "dotnet/windows-dotnet-dotnet-listing.json"
VERSION = "dotnet/windows-dotnet-10.0.402.json"
CAPTURED_VERSIONS = [
    "8.0.132",
    "8.0.206",
    "8.0.319",
    "8.0.426",
    "9.0.122",
    "9.0.205",
    "9.0.319",
    "10.0.113",
    "10.0.204",
    "10.0.303",
    "10.0.402",
]


def machine(
    *,
    on_path: bool = True,
    env: dict[str, str] | None = None,
    listing: Capture | None = None,
    host: bool = True,
) -> FakeSystem:
    path = [r"C:\WINDOWS\system32"] + ([HOST_DIR] if on_path else [])
    system = FakeSystem(
        os="windows",
        env={"PATH": ";".join(path), "PATHEXT": WINDOWS_PATHEXT, **(env or {})},
    )
    if host:
        system.add_executable(HOST, load_capture(VERSION), listing or load_capture(LISTING))
    return system


def dotnet_of(system: FakeSystem) -> dict:
    result = run_cli(system, "show", "dotnet", "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["tools"][0]


def sdks(tool: dict) -> list[tuple[str, str, str]]:
    return [(i["version"], i["path"], i["source"]) for i in tool["installs"]]


def failing(result: ProcessResult, seconds: float = 0.0) -> Capture:
    return Capture(LIST_ARGS, result, seconds)


def test_every_sdk_is_listed_with_its_own_folder_and_the_path_host_stays_active() -> None:
    dotnet = dotnet_of(machine())

    # The host answers 10.0.402, so it stands for that SDK (PATH wins).
    assert dotnet["active"]["path"] == HOST
    assert dotnet["active"]["version"] == "10.0.402"
    assert sdks(dotnet) == [
        ("10.0.402", HOST, "path"),
        *[(v, rf"{SDK_DIR}\{v}", "dotnet") for v in CAPTURED_VERSIONS[:-1]],
    ]
    assert dotnet["notes"] == []


def test_sdks_are_reported_without_running_them() -> None:
    system = machine()

    dotnet_of(system)

    assert set(system.runs) == {(HOST, "--version"), (HOST, "--list-sdks")}


def test_the_host_is_found_through_dotnet_root_when_not_on_path() -> None:
    dotnet = dotnet_of(machine(on_path=False, env={"DOTNET_ROOT": HOST_DIR}))

    assert (dotnet["status"], dotnet["active"]) == ("missing", None)
    assert [i[0] for i in sdks(dotnet)] == CAPTURED_VERSIONS


def test_the_host_is_found_through_program_files_when_not_on_path() -> None:
    system = machine(on_path=False, env={"ProgramFiles": r"C:\Program Files"})

    assert [i[0] for i in sdks(dotnet_of(system))] == CAPTURED_VERSIONS


# A second host whose listing is empty: using it instead of the intended one
# would show as missing SDKs.
OTHER_DIR = r"D:\tools\dotnet"
OTHER = rf"{OTHER_DIR}\dotnet.exe"
NO_SDKS = Capture(LIST_ARGS, ProcessResult(exit_code=0, stdout=b"", stderr=b""))


def test_the_path_host_is_asked_before_dotnet_root() -> None:
    system = machine(env={"DOTNET_ROOT": OTHER_DIR})
    system.add_executable(OTHER, NO_SDKS)

    dotnet = dotnet_of(system)

    # Listing from another host would list the active SDK a second time.
    assert sdks(dotnet) == [
        ("10.0.402", HOST, "path"),
        *[(v, rf"{SDK_DIR}\{v}", "dotnet") for v in CAPTURED_VERSIONS[:-1]],
    ]
    assert OTHER not in {run[0] for run in system.runs}


def test_dotnet_root_is_asked_before_program_files() -> None:
    system = machine(
        on_path=False,
        env={"DOTNET_ROOT": HOST_DIR, "ProgramFiles": r"D:\tools"},
    )
    system.add_executable(OTHER, NO_SDKS)

    assert [i[0] for i in sdks(dotnet_of(system))] == CAPTURED_VERSIONS


def test_without_a_host_nothing_is_added_and_nothing_is_said() -> None:
    dotnet = dotnet_of(machine(on_path=False, host=False))

    assert dotnet["installs"] == []
    assert not any(note.startswith(".NET SDK") for note in dotnet["notes"])


def test_a_host_with_no_sdks_adds_nothing() -> None:
    # Unverified assumption: no real capture exists from a host with zero SDKs;
    # empty output with exit 0 is the transport-style stand-in for it.
    empty = failing(ProcessResult(exit_code=0, stdout=b"", stderr=b""))

    dotnet = dotnet_of(machine(listing=empty))

    assert sdks(dotnet) == [("10.0.402", HOST, "path")]
    assert dotnet["notes"] == []


def test_malformed_output_is_a_note_and_loses_nothing_else() -> None:
    # Real output of another tool (uv --version), which is not a listing.
    foreign = load_capture("uv/windows-uv-0.12.23.json").result.stdout
    garbled = failing(ProcessResult(exit_code=0, stdout=foreign, stderr=b""))

    dotnet = dotnet_of(machine(listing=garbled))

    assert sdks(dotnet) == [("10.0.402", HOST, "path")]
    assert dotnet["notes"][-1].startswith(".NET SDK: could not list installs: ")


def test_a_failing_listing_is_a_note_and_loses_nothing_else() -> None:
    for result in (
        ProcessResult(exit_code=1, stdout=b"", stderr=b""),
        ProcessResult(exit_code=None, stdout=b"", stderr=b"", launch_error="access denied"),
    ):
        dotnet = dotnet_of(machine(listing=failing(result)))

        assert sdks(dotnet) == [("10.0.402", HOST, "path")]
        assert dotnet["active"]["path"] == HOST
        assert dotnet["notes"][-1].startswith(".NET SDK: could not list installs: ")


def test_a_hanging_listing_gives_up_after_the_tools_timeout() -> None:
    hanging = failing(ProcessResult(0, b"", b""), seconds=60)

    dotnet = dotnet_of(machine(listing=hanging))

    assert dotnet["notes"][-1] == (
        ".NET SDK: could not list installs: dotnet --list-sdks did not answer within 5 s"
    )


def test_dotnet_is_listed_as_a_windows_only_provider() -> None:
    result = run_cli(machine(), "tools", "--json")

    [provider] = [p for p in json.loads(result.stdout)["providers"] if p["id"] == "dotnet"]
    assert (provider["name"], provider["os"], provider["tools"]) == (
        ".NET SDK",
        ["windows"],
        ["dotnet"],
    )
