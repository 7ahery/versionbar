"""Providers (nvm-windows) and how their installs merge with PATH, through the CLI seam.

Folder layouts and environment are synthetic machine state, modelled on a real
nvm-windows 2.0.1 install (`NVM_HOME` with versions under `installs\\`, the
`.nodejs` shim folder on PATH, no `NVM_SYMLINK`). Version output is always a
real capture: the nvm-held 24.21.0 and the shim from that machine, and a
second real Node.js (24.22.1) placed in nvm's folders as another version.
"""

import json
from dataclasses import replace

import pytest

from versionbar import cli, providers
from versionbar.provider import Located, Provider
from versionbar.system import System

from fakes import (
    GIT_WINDOWS,
    NODE_24_22_WINDOWS,
    NODE_WINDOWS,
    NVM_NODE_WINDOWS,
    WINDOWS_PATHEXT,
    Capture,
    FakeSystem,
    load_capture,
    run_cli,
)

# The space is real: nvm-windows 2 installs under "Author Software".
NVM_HOME = r"C:\Users\dev\AppData\Local\Author Software\nvm"
NVM_24_21 = rf"{NVM_HOME}\installs\v24.21.0\node.exe"
NVM_24_22 = rf"{NVM_HOME}\installs\v24.22.1\node.exe"
# What nvm-windows 2 puts on PATH: a junction to its shim folder, whose
# node.exe forwards to the selected version.
SHIM = rf"{NVM_HOME}\.nodejs\node.exe"


def windows(path: list[str], **env: str) -> FakeSystem:
    return FakeSystem(os="windows", env={"PATH": ";".join(path), "PATHEXT": WINDOWS_PATHEXT, **env})


def nvm_machine(*, on_path: bool = True) -> FakeSystem:
    """nvm-windows 2 holding 24.21.0 (selected) and 24.22.1."""
    path = [r"C:\WINDOWS\system32", NVM_HOME]
    if on_path:
        path.append(rf"{NVM_HOME}\.nodejs")
        system = windows(path, NVM_HOME=NVM_HOME)
        system.add_executable(SHIM, load_capture(NODE_WINDOWS))
    else:
        system = windows(path, NVM_HOME=NVM_HOME)
    # Added oldest last on purpose: the listing order is not the report order.
    system.add_executable(NVM_24_21, load_capture(NVM_NODE_WINDOWS))
    system.add_executable(NVM_24_22, load_capture(NODE_24_22_WINDOWS))
    return system


def node_of(system: FakeSystem) -> dict:
    result = run_cli(system, "show", "node", "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["tools"][0]


def listed(system: FakeSystem) -> dict[str, dict]:
    result = run_cli(system, "list", "--json")
    assert result.exit_code == 0, result.output
    return {tool["id"]: tool for tool in json.loads(result.stdout)["tools"]}


def installs(tool: dict) -> list[tuple[str, str, str, str | None]]:
    return [(i["version"], i["path"], i["source"], i["via"]) for i in tool["installs"]]


def test_nvm_installs_off_path_are_listed_with_source_nvm() -> None:
    node = node_of(nvm_machine(on_path=False))

    # Nothing runs when `node` is typed, so nothing is active; the held
    # versions are still reported, newest first, as ones you could switch to.
    assert node["status"] == "missing"
    assert node["active"] is None
    assert installs(node) == [
        ("24.22.1", NVM_24_22, "nvm", None),
        ("24.21.0", NVM_24_21, "nvm", None),
    ]


def test_the_nvm_shim_and_the_version_it_serves_are_one_install() -> None:
    node = node_of(nvm_machine())

    # The shim is what typing `node` runs, so it stays the active install;
    # nvm's copy of the version it serves is not counted a second time, and
    # nvm's newer version does not take over as active.
    assert node["status"] == "found"
    assert node["active"]["path"] == SHIM
    assert installs(node) == [
        ("24.21.0", SHIM, "path", "nvm"),
        ("24.22.1", NVM_24_22, "nvm", None),
    ]


def test_an_nvm_folder_on_path_is_one_install_found_on_path() -> None:
    system = nvm_machine(on_path=False)
    system.env["PATH"] += rf";{NVM_HOME}\installs\v24.21.0"

    node = node_of(system)

    assert node["active"]["path"] == NVM_24_21
    assert installs(node) == [
        ("24.21.0", NVM_24_21, "path", None),
        ("24.22.1", NVM_24_22, "nvm", None),
    ]
    assert system.runs.count((NVM_24_21, "--version")) == 1


def test_nvm_1_layout_with_nvm_symlink_and_a_quoted_unusual_home() -> None:
    # nvm-windows 1 keeps versions in its root and links NVM_SYMLINK to the
    # selected one. The root here is nowhere a default would look.
    home = r"D:\tools\node versions"
    link = r"C:\Program Files\nodejs"
    system = windows([r"C:\WINDOWS\system32", link], NVM_HOME=f'"{home}\\"', NVM_SYMLINK=link)
    system.add_executable(rf"{link}\node.exe", load_capture(NODE_WINDOWS))
    system.add_executable(rf"{home}\v24.21.0\node.exe", load_capture(NVM_NODE_WINDOWS))
    system.add_executable(rf"{home}\v24.22.1\node.exe", load_capture(NODE_24_22_WINDOWS))
    system.add_executable(rf"{home}\nvm.exe")

    node = node_of(system)

    assert installs(node) == [
        ("24.21.0", rf"{link}\node.exe", "path", "nvm"),
        ("24.22.1", rf"{home}\v24.22.1\node.exe", "nvm", None),
    ]


def test_without_nvm_nothing_is_added_and_nothing_is_said() -> None:
    unset = nvm_machine()
    del unset.env["NVM_HOME"]
    stale = nvm_machine()
    stale.env["NVM_HOME"] = r"C:\Users\dev\AppData\Roaming\nvm"

    for system in (unset, stale):
        node = node_of(system)
        assert installs(node) == [("24.21.0", SHIM, "path", None)]
        assert node["notes"] == []


# Real output of git rejecting an argument (exit code 129), replayed as a
# broken nvm-held node.exe.
FAILING = load_capture("git/windows-git-badflag-unknown-version.json").result


def test_a_version_folder_without_node_is_a_note_and_the_rest_still_count() -> None:
    system = nvm_machine()
    broken = rf"{NVM_HOME}\installs\v25.0.0"
    system.add_folder(broken)

    node = node_of(system)

    assert installs(node)[1:] == [("24.22.1", NVM_24_22, "nvm", None)]
    assert node["notes"] == [f"nvm-windows: {broken} has no node.exe, so it is not an install"]


def test_failing_and_hanging_nvm_installs_are_notes_and_lose_nothing_else() -> None:
    system = nvm_machine()
    system.add_executable(NVM_24_22, Capture(("--version",), FAILING))
    hung = rf"{NVM_HOME}\installs\v24.10.0\node.exe"
    system.add_executable(hung, replace(load_capture(NODE_24_22_WINDOWS), seconds=60))

    node = listed(system)["node"]
    assert node["status"] == "found"
    assert installs(node) == [("24.21.0", SHIM, "path", "nvm")]
    [failed, timed_out] = node["notes"]
    assert failed.startswith(f"nvm-windows: {NVM_24_22} exited with code 129: unknown option")
    assert timed_out == f"nvm-windows: {hung} did not answer within 5 s"


def test_an_unreadable_nvm_folder_is_a_note_and_path_installs_stay() -> None:
    system = nvm_machine()
    system.add_unlistable(rf"{NVM_HOME}\installs", "[WinError 5] Access is denied")

    node = node_of(system)

    assert installs(node) == [("24.21.0", SHIM, "path", "nvm")]
    assert node["notes"] == ["nvm-windows: could not list installs: [WinError 5] Access is denied"]


# The seam itself, with test-only providers registered next to the built-ins:
# adding one changes nothing in the engine.
KIT_GIT = r"C:\Users\dev\kit\git\2.55\cmd\git.exe"


class GitKit(Provider):
    """A made-up manager holding git installs off PATH."""

    id = "kit"
    name = "Git kit"
    os = ("windows",)
    tools = ("git",)

    def locate(self, system: System, tool: str, timeout: float) -> Located:
        return Located([KIT_GIT])


class Crashing(GitKit):
    id = "crash"
    name = "Crashing kit"
    tools = ("git", "node")

    def locate(self, system: System, tool: str, timeout: float) -> Located:
        raise RuntimeError("unexpected layout")


class Twin(GitKit):
    """Names a file nvm already reported."""

    id = "twin"
    tools = ("node",)

    def locate(self, system: System, tool: str, timeout: float) -> Located:
        return Located([NVM_24_22.upper()])


class LinuxOnly(GitKit):
    id = "linuxkit"
    os = ("linux",)
    calls: list[str] = []

    def locate(self, system: System, tool: str, timeout: float) -> Located:
        self.calls.append(tool)
        return super().locate(system, tool, timeout)


def with_providers(monkeypatch: pytest.MonkeyPatch, *extra: Provider) -> None:
    monkeypatch.setattr(cli, "builtin_providers", lambda: [*providers.builtin_providers(), *extra])


def git_and_nvm() -> FakeSystem:
    system = nvm_machine()
    system.add_executable(KIT_GIT, load_capture(GIT_WINDOWS))
    return system


def test_another_provider_adds_its_installs_with_its_own_source(monkeypatch) -> None:
    with_providers(monkeypatch, GitKit())

    tools = listed(git_and_nvm())

    assert installs(tools["git"]) == [("2.55.0.windows.2", KIT_GIT, "kit", None)]
    assert tools["git"]["notes"] == ["not found on PATH (looked for: git)"]
    assert installs(tools["node"]) == installs(node_of(nvm_machine()))


def test_a_file_two_providers_name_is_one_install_from_the_first(monkeypatch) -> None:
    with_providers(monkeypatch, Twin())
    system = nvm_machine()

    node = node_of(system)

    assert [i[2] for i in installs(node)] == ["path", "nvm"]
    assert system.runs.count((NVM_24_22, "--version")) == 1


def test_a_crashing_provider_is_a_note_on_each_of_its_tools_only(monkeypatch) -> None:
    with_providers(monkeypatch, Crashing(), GitKit())

    tools = listed(git_and_nvm())

    note = "Crashing kit: could not list installs: unexpected layout"
    assert tools["git"]["notes"] == ["not found on PATH (looked for: git)", note]
    assert installs(tools["git"]) == [("2.55.0.windows.2", KIT_GIT, "kit", None)]
    assert tools["node"]["notes"] == [note]
    assert len(tools["node"]["installs"]) == 2
    assert tools["python"]["notes"] == ["not found on PATH (looked for: python, python3)"]


def test_a_provider_for_another_os_is_never_asked(monkeypatch) -> None:
    LinuxOnly.calls = []
    with_providers(monkeypatch, LinuxOnly())

    git = json.loads(run_cli(git_and_nvm(), "show", "git", "--json").stdout)["tools"][0]

    assert (git["status"], git["installs"], LinuxOnly.calls) == ("missing", [], [])


def test_human_output_never_calls_a_held_install_active(monkeypatch) -> None:
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    system = nvm_machine(on_path=False)

    shown = [line.split() for line in run_cli(system, "show", "node").stdout.splitlines()]
    listed_row = next(
        line for line in run_cli(system, "list").stdout.splitlines() if "node" in line
    )

    status, *held = [line for line in shown if line and line[0] in ("node", "other")]
    assert status == ["node", "missing"]
    assert [(line[0], line[1], line[-1]) for line in held] == [
        ("other", "24.22.1", "nvm"),
        ("other", "24.21.0", "nvm"),
    ]
    # Not active, so both count as other installs.
    assert listed_row.split() == ["node", "missing", "2"]


def test_an_inactive_nvm_install_never_satisfies_check() -> None:
    off_path = run_cli(nvm_machine(on_path=False), "check", "node", "node@>=20", "--json")
    newer_held = run_cli(nvm_machine(), "check", "node@>=24.22", "--json")

    assert (off_path.exit_code, newer_held.exit_code) == (1, 1)
    assert [r["outcome"] for r in json.loads(off_path.stdout)["requirements"]] == [
        "missing",
        "missing",
    ]
    [requirement] = json.loads(newer_held.stdout)["requirements"]
    assert (requirement["outcome"], requirement["version"], requirement["path"]) == (
        "unmet",
        "24.21.0",
        SHIM,
    )
