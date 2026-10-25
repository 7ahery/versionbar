"""Installs a provider reports finished (version and path, nothing to run), through the CLI seam.

A test-only provider stands in for a manager like the .NET host, which lists
several SDKs that all run through one executable. Its folders and versions are
synthetic machine state; the only command output is the real `dotnet --version`
capture of the PATH host.
"""

import json

import pytest

from versionbar import cli, providers
from versionbar.provider import Located, ProvidedInstall, Provider
from versionbar.system import System

from fakes import WINDOWS_PATHEXT, FakeSystem, load_capture, run_cli

HOST_DIR = r"C:\Program Files\dotnet"
HOST = rf"{HOST_DIR}\dotnet.exe"
# What the real host on PATH answers `dotnet --version` with.
HOST_VERSION = "10.0.402"
SDK_10 = rf"{HOST_DIR}\sdk\10.0.402"
SDK_9 = rf"{HOST_DIR}\sdk\9.0.300"
SDK_9_PREVIEW = rf"{HOST_DIR}\sdk\9.0.300-preview.1"


class SdkKit(Provider):
    """A made-up manager that knows its installs' versions without running them."""

    id = "sdkkit"
    name = "SDK kit"
    os = ("windows",)
    tools = ("dotnet",)
    reports: tuple[ProvidedInstall, ...] = ()

    def locate(self, system: System, tool: str, timeout: float) -> Located:
        return Located(installs=self.reports)


def with_kit(monkeypatch: pytest.MonkeyPatch, *reports: ProvidedInstall) -> None:
    kit = SdkKit()
    kit.reports = reports
    monkeypatch.setattr(cli, "builtin_providers", lambda: [*providers.builtin_providers(), kit])


def machine(*, host_on_path: bool) -> FakeSystem:
    path = [r"C:\WINDOWS\system32"] + ([HOST_DIR] if host_on_path else [])
    system = FakeSystem(os="windows", env={"PATH": ";".join(path), "PATHEXT": WINDOWS_PATHEXT})
    if host_on_path:
        system.add_executable(HOST, load_capture("dotnet/windows-dotnet-10.0.402.json"))
    return system


def dotnet_of(system: FakeSystem) -> dict:
    result = run_cli(system, "show", "dotnet", "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["tools"][0]


def installs(tool: dict) -> list[tuple[str, str, str]]:
    return [(i["version"], i["path"], i["source"]) for i in tool["installs"]]


def test_provided_installs_are_reported_as_they_are_without_running_anything(
    monkeypatch,
) -> None:
    with_kit(monkeypatch, ProvidedInstall("10.0.402", SDK_10), ProvidedInstall("9.0.300", SDK_9))
    system = machine(host_on_path=False)

    dotnet = dotnet_of(system)

    assert (dotnet["status"], dotnet["active"]) == ("missing", None)
    assert dotnet["installs"] == [
        {"version": "10.0.402", "path": SDK_10, "source": "sdkkit", "via": None, "raw": None},
        {"version": "9.0.300", "path": SDK_9, "source": "sdkkit", "via": None, "raw": None},
    ]
    assert system.runs == []


def test_the_path_host_stands_for_the_install_of_its_own_version_in_its_folder(
    monkeypatch,
) -> None:
    with_kit(monkeypatch, ProvidedInstall("10.0.402", SDK_10), ProvidedInstall("9.0.300", SDK_9))

    dotnet = dotnet_of(machine(host_on_path=True))

    # PATH wins: the host is what typing `dotnet` runs, and it runs that SDK.
    assert dotnet["active"]["path"] == HOST
    assert installs(dotnet) == [(HOST_VERSION, HOST, "path"), ("9.0.300", SDK_9, "sdkkit")]
    assert dotnet["notes"] == []


def test_distinct_versions_under_one_host_and_a_same_version_elsewhere_all_stay(
    monkeypatch,
) -> None:
    elsewhere = r"D:\sdks\dotnet\sdk\10.0.402"
    with_kit(
        monkeypatch,
        ProvidedInstall("9.0.300", SDK_9),
        ProvidedInstall("9.0.300-preview.1", SDK_9_PREVIEW),
        ProvidedInstall("10.0.402", elsewhere),
    )

    dotnet = dotnet_of(machine(host_on_path=True))

    assert installs(dotnet) == [
        (HOST_VERSION, HOST, "path"),
        ("9.0.300", SDK_9, "sdkkit"),
        ("9.0.300-preview.1", SDK_9_PREVIEW, "sdkkit"),
        ("10.0.402", elsewhere, "sdkkit"),
    ]


def test_one_path_is_one_install_whoever_names_it(monkeypatch) -> None:
    with_kit(
        monkeypatch,
        ProvidedInstall("9.0.300", SDK_9),
        ProvidedInstall("9.0.301", SDK_9.upper() + "\\"),
        ProvidedInstall("1.0.0", HOST.lower()),
    )

    dotnet = dotnet_of(machine(host_on_path=True))

    # Paths fold as PATH hits do; the first to name one keeps it, and a PATH
    # hit is always its own PATH install.
    assert installs(dotnet) == [(HOST_VERSION, HOST, "path"), ("9.0.300", SDK_9, "sdkkit")]


def test_malformed_provider_data_is_a_note_and_loses_nothing_else(monkeypatch) -> None:
    with_kit(monkeypatch, ProvidedInstall("9.0.300", SDK_9), None)  # type: ignore[arg-type]

    dotnet = dotnet_of(machine(host_on_path=True))

    assert installs(dotnet) == [(HOST_VERSION, HOST, "path")]
    [note] = dotnet["notes"]
    assert note.startswith("SDK kit: could not list installs: ")


class ShimKit(Provider):
    """Takes nvm's id, so the node definition's shim rule names it as the manager."""

    id = "nvm"
    name = "Shim kit"
    os = ("windows",)
    tools = ("node",)

    def locate(self, system: System, tool: str, timeout: float) -> Located:
        return Located(
            installs=[
                ProvidedInstall("24.21.0", r"D:\kit\node-24.21.0"),
                ProvidedInstall("24.22.1", r"D:\kit\node-24.22.1"),
            ]
        )


def test_a_managers_shim_on_path_stands_for_the_version_it_serves(monkeypatch) -> None:
    monkeypatch.setattr(cli, "builtin_providers", lambda: [ShimKit()])
    home = r"C:\nvm"
    shim = rf"{home}\.nodejs\node.exe"
    system = FakeSystem(
        os="windows",
        env={"PATH": rf"{home}\.nodejs", "PATHEXT": WINDOWS_PATHEXT, "NVM_HOME": home},
    )
    system.add_executable(shim, load_capture("node/windows-node-24.21.0.json"))

    result = run_cli(system, "show", "node", "--json")

    node = json.loads(result.stdout)["tools"][0]
    assert installs(node) == [("24.21.0", shim, "path"), ("24.22.1", r"D:\kit\node-24.22.1", "nvm")]
