"""Decoding, failures, timeouts and parallelism of a scan, through the CLI seam."""

import json
import threading

import pytest
from typer.testing import CliRunner

from versionbar import cli, definition
from versionbar.cli import app
from versionbar.definition import ToolDefinition
from versionbar.system import ProcessResult

from fakes import GIT_WINDOWS, WINDOWS_PATHEXT, Capture, FakeSystem, load_capture

WSL_PATH = r"C:\WINDOWS\system32\wsl.exe"
GIT_EXE = r"C:\Program Files\Git\cmd\git.exe"

# Draft definitions for tools with no built-in yet; their output is real
# (see the fixtures). Replace WSL with the built-in once ticket 15 (#17) ships it.
WSL = ToolDefinition(
    id="wsl",
    name="WSL",
    os=["windows"],
    binaries=["wsl"],
    version_args=["--version"],
    version_regex=r"WSL[^:\r\n]*:\s*(?P<version>\d+(?:\.\d+)+)",
)


def run_cli(system: FakeSystem, *args: str):
    return CliRunner().invoke(app, list(args), obj=system)


def windows(*directories: str) -> FakeSystem:
    return FakeSystem(
        os="windows",
        env={"PATH": ";".join([r"C:\WINDOWS\system32", *directories]), "PATHEXT": WINDOWS_PATHEXT},
    )


def with_definitions(monkeypatch: pytest.MonkeyPatch, *extra: ToolDefinition) -> None:
    monkeypatch.setattr(
        cli, "builtin_definitions", lambda: [*definition.builtin_definitions(), *extra]
    )


def tools_of(result) -> dict[str, dict]:
    assert result.exit_code == 0, result.output
    return {tool["id"]: tool for tool in json.loads(result.stdout)["tools"]}


def test_wsl_utf16_version_output_is_decoded(monkeypatch) -> None:
    with_definitions(monkeypatch, WSL)
    system = windows()
    system.add_executable(WSL_PATH, load_capture("wsl/windows-wsl-2.7.12.0.json"))

    wsl = tools_of(run_cli(system, "list", "--json"))["wsl"]

    assert wsl["status"] == "found"
    assert wsl["active"]["version"] == "2.7.12.0"
    assert wsl["active"]["raw"].splitlines()[:2] == [
        "WSL version: 2.7.12.0",
        "Kernel version: 6.18.33.2-2",
    ]
    # wsl.exe ends lines with CRLF; `raw` is normalised to LF.
    assert "\r" not in wsl["active"]["raw"]


# Not a v1 tool: OpenSSH is here because it is a real tool that prints its
# version on stderr only.
SSH = ToolDefinition(
    id="ssh",
    name="OpenSSH client",
    os=["windows", "linux"],
    binaries=["ssh"],
    version_args=["-V"],
    version_regex=r"OpenSSH_(?:for_Windows_)?(?P<version>\d+\.\d+\S*?),",
)


def test_version_printed_on_stderr_is_read(monkeypatch) -> None:
    with_definitions(monkeypatch, SSH)
    system = windows(r"C:\WINDOWS\System32\OpenSSH")
    system.add_executable(
        r"C:\WINDOWS\System32\OpenSSH\ssh.exe", load_capture("ssh/windows-ssh-9.5p2.json")
    )

    ssh = tools_of(run_cli(system, "list", "--json"))["ssh"]

    assert ssh["status"] == "found"
    assert ssh["active"]["version"] == "9.5p2"
    assert ssh["active"]["raw"] == "OpenSSH_for_Windows_9.5p2, LibreSSL 3.8.2"


def git_and_wsl(monkeypatch: pytest.MonkeyPatch) -> FakeSystem:
    with_definitions(monkeypatch, WSL)
    system = windows(r"C:\Program Files\Git\cmd")
    system.add_executable(GIT_EXE, load_capture(GIT_WINDOWS))
    system.add_executable(WSL_PATH, load_capture("wsl/windows-wsl-2.7.12.0.json"))
    return system


def test_tools_are_probed_in_parallel(monkeypatch) -> None:
    system = git_and_wsl(monkeypatch)
    # Each command waits until the other has started too, so a scan that ran
    # them one after another would break the barrier. The timeout only bounds
    # how long a failing run takes; it is not a performance threshold.
    barrier = threading.Barrier(2, timeout=10)
    system.before_run = lambda argv: barrier.wait()

    tools = tools_of(run_cli(system, "list", "--json"))

    assert (tools["git"]["status"], tools["wsl"]["status"]) == ("found", "found")


def replace_wsl(system: FakeSystem, process: ProcessResult) -> None:
    # Failure transports have no output to capture: these results are what the
    # real system reports when a command hangs or cannot start.
    system.add_executable(WSL_PATH, Capture(args=("--version",), result=process))


def test_a_hanging_tool_times_out_and_the_others_still_complete(monkeypatch) -> None:
    system = git_and_wsl(monkeypatch)
    replace_wsl(system, ProcessResult(exit_code=None, stdout=b"", stderr=b"", timed_out=True))

    tools = tools_of(run_cli(system, "list", "--json"))

    assert tools["git"]["status"] == "found"
    wsl = tools["wsl"]
    assert (wsl["status"], wsl["active"], wsl["installs"]) == ("timeout", None, [])
    # The note states the 5-second default per-command timeout.
    assert wsl["notes"] == [rf"{WSL_PATH} did not answer within 5 s"]


def test_a_timeout_note_keeps_what_was_printed_before_the_hang(monkeypatch) -> None:
    system = git_and_wsl(monkeypatch)
    # Real WSL bytes as the partial output: what it printed before being killed.
    printed = load_capture("wsl/windows-wsl-2.7.12.0.json").result.stdout
    replace_wsl(system, ProcessResult(exit_code=None, stdout=printed, stderr=b"", timed_out=True))

    wsl = tools_of(run_cli(system, "list", "--json"))["wsl"]

    assert wsl["status"] == "timeout"
    [note] = wsl["notes"]
    assert note.startswith(rf"{WSL_PATH} did not answer within 5 s: WSL version: 2.7.12.0" + "\n")


def test_a_tool_that_cannot_start_is_an_error_with_the_reason(monkeypatch) -> None:
    system = git_and_wsl(monkeypatch)
    reason = "[WinError 5] Access is denied"
    replace_wsl(system, ProcessResult(exit_code=None, stdout=b"", stderr=b"", launch_error=reason))

    tools = tools_of(run_cli(system, "list", "--json"))

    assert tools["git"]["status"] == "found"
    assert tools["wsl"]["status"] == "error"
    assert tools["wsl"]["notes"] == [rf"could not run {WSL_PATH}: {reason}"]


def test_a_failing_version_command_is_an_error_with_its_captured_message(monkeypatch) -> None:
    system = git_and_wsl(monkeypatch)
    failing = load_capture("git/windows-git-badflag-unknown-version.json")
    # The real output of git rejecting an argument, replayed as wsl's answer.
    replace_wsl(system, failing.result)

    tools = tools_of(run_cli(system, "list", "--json"))

    assert tools["git"]["status"] == "found"
    wsl = tools["wsl"]
    assert (wsl["status"], wsl["active"]) == ("error", None)
    [note] = wsl["notes"]
    assert note.startswith(rf"{WSL_PATH} exited with code 129: unknown option: --no-such-flag")
    assert "usage: git" in note


def test_output_without_a_version_is_an_error_quoting_the_output(monkeypatch) -> None:
    system = git_and_wsl(monkeypatch)
    # Real ssh output: exit code 0, but nothing the WSL pattern recognises.
    replace_wsl(system, load_capture("ssh/windows-ssh-9.5p2.json").result)

    tools = tools_of(run_cli(system, "list", "--json"))

    assert tools["git"]["status"] == "found"
    assert tools["wsl"]["status"] == "error"
    assert tools["wsl"]["notes"] == [
        rf"{WSL_PATH} printed no version: OpenSSH_for_Windows_9.5p2, LibreSSL 3.8.2"
    ]
