"""`versionbar debug capture <tool>` over a fake system, through the CLI seam."""

import base64
import json

from typer.testing import CliRunner

from versionbar.cli import app
from versionbar.definition import ToolDefinition
from versionbar.system import ProcessResult

from fakes import (
    GIT_LINUX,
    NODE_WINDOWS,
    PYTHON_314_WINDOWS,
    STORE_PYTHON_PLACEHOLDER,
    WINDOWS_PATHEXT,
    Capture,
    FakeSystem,
    capture_from_bytes,
    load_capture,
    run_cli,
    windows_with_git,
)

OUT = r"C:\captures"
GIT_FILE = OUT + r"\windows-git-2.55.0.windows.2.json"
GIT_PATH = r"C:\Program Files\Git\cmd\git.exe"


def capture(system: FakeSystem, tool: str = "git", *extra: str):
    return run_cli(system, "debug", "capture", tool, "--out", OUT, *extra)


def written(system: FakeSystem, path: str = GIT_FILE) -> dict:
    return json.loads(system.files[path])


def test_capture_records_raw_bytes_exit_code_and_provenance() -> None:
    system = windows_with_git()
    system.env["ImageOS"] = "win22"
    system.env["ImageVersion"] = "20260401.1.0"

    result = capture(system, "git", "--json")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "outcome": "captured",
        "tool": "git",
        "destination": GIT_FILE,
        "exit_code": 0,
    }
    record = written(system)
    assert record["tool"] == "git"
    assert record["args"] == ["--version"]
    assert record["exit_code"] == 0
    assert base64.b64decode(record["stdout_b64"]) == b"git version 2.55.0.windows.2\n"
    assert record["stderr_b64"] == ""
    assert record["encoding"] == "utf-8"
    provenance = record["provenance"]
    assert provenance["command"] == [GIT_PATH, "--version"]
    assert provenance["resolved_path"] == GIT_PATH
    assert provenance["os_id"] == "windows"
    assert provenance["os_description"] == "Windows-11-10.0.26200-SP0"
    assert provenance["captured_at"] == "2026-10-23T21:04:52Z"
    assert provenance["runner"] == {
        "image_os": "win22",
        "image_version": "20260401.1.0",
        "run_url": None,
    }


def test_human_output_names_the_destination() -> None:
    result = capture(windows_with_git())

    assert result.exit_code == 0, result.output
    assert GIT_FILE in result.stdout


def test_a_capture_replays_through_the_fake_system_unchanged() -> None:
    recorded = windows_with_git()
    capture(recorded)
    replay = FakeSystem(os="windows", env=dict(recorded.env))
    replay.add_executable(GIT_PATH, capture_from_bytes(recorded.files[GIT_FILE]))

    result = run_cli(replay, "list", "--json")

    git = next(t for t in json.loads(result.stdout)["tools"] if t["id"] == "git")
    assert git["active"]["version"] == "2.55.0.windows.2"
    assert git["active"]["raw"] == "git version 2.55.0.windows.2"


def add_tool(system: FakeSystem, process: ProcessResult) -> None:
    # Transport-level behaviour (failure statuses, UTF-16 bytes) needs outputs
    # no captured fixture holds yet. These bytes only exercise the recorder and
    # are never stored as fixtures.
    system.add_executable(GIT_PATH, Capture(args=("--version",), result=process))


def test_a_failing_command_is_captured_with_its_true_exit_status() -> None:
    system = windows_with_git()
    add_tool(system, ProcessResult(exit_code=129, stdout=b"", stderr=b"usage: boom\n"))

    result = capture(system, "git", "--json")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["exit_code"] == 129
    record = written(system, OUT + r"\windows-git-unknown-version.json")
    assert record["exit_code"] == 129
    assert base64.b64decode(record["stderr_b64"]) == b"usage: boom\n"


TEXT = "git version 9.9.9\r\n"
UTF16_FILE = OUT + r"\windows-git-9.9.9.json"


def test_utf16_output_is_preserved_as_bytes() -> None:
    system = windows_with_git()
    raw = b"\xff\xfe" + TEXT.encode("utf-16-le")
    add_tool(system, ProcessResult(exit_code=0, stdout=raw, stderr=b""))

    capture(system)

    record = written(system, UTF16_FILE)
    assert base64.b64decode(record["stdout_b64"]) == raw
    assert record["encoding"] == "utf-16"
    assert record["stdout_text"] == TEXT
    assert capture_from_bytes(system.files[UTF16_FILE]).result.stdout == raw


def test_bom_less_utf16_output_is_preserved_as_bytes() -> None:
    system = windows_with_git()
    raw = TEXT.encode("utf-16-le")
    add_tool(system, ProcessResult(exit_code=0, stdout=raw, stderr=b""))

    capture(system)

    record = written(system, UTF16_FILE)
    assert record["encoding"] == "utf-16-le"
    assert record["stdout_text"] == TEXT
    assert capture_from_bytes(system.files[UTF16_FILE]).result.stdout == raw


def test_utf16_on_stderr_alone_is_preserved_as_bytes() -> None:
    system = windows_with_git()
    raw = TEXT.encode("utf-16-le")
    add_tool(system, ProcessResult(exit_code=1, stdout=b"", stderr=raw))

    capture(system)

    record = written(system, UTF16_FILE)
    assert record["encoding"] == "utf-16-le"
    assert record["stderr_text"] == TEXT
    replayed = capture_from_bytes(system.files[UTF16_FILE]).result
    assert (replayed.stdout, replayed.stderr, replayed.exit_code) == (b"", raw, 1)


def test_unknown_tool_is_a_usage_error_and_writes_nothing() -> None:
    system = windows_with_git()

    result = capture(system, "nosuchtool", "--json")

    assert result.exit_code == 2
    failure = json.loads(result.stdout)
    assert failure["outcome"] == "unknown-tool"
    assert "nosuchtool" in failure["message"]
    assert system.files == {}


def test_tool_without_a_definition_for_this_os_is_a_usage_error(monkeypatch) -> None:
    windows_only = ToolDefinition(
        id="winonly",
        name="Win only",
        os=["windows"],
        binaries=["winonly"],
        version_args=["--version"],
        version_regex=r"(?P<version>\d+)",
    )
    monkeypatch.setattr("versionbar.cli.builtin_definitions", lambda: [windows_only])
    system = FakeSystem(os="linux", env={"PATH": "/usr/bin"})

    result = run_cli(system, "debug", "capture", "winonly", "--out", "/tmp/caps", "--json")

    assert result.exit_code == 2
    failure = json.loads(result.stdout)
    assert failure["outcome"] == "unsupported-os"
    assert failure["message"] == "winonly is not available on linux"
    assert system.files == {}


def test_missing_exit_status_is_not_reported_as_none() -> None:
    system = windows_with_git()
    add_tool(system, ProcessResult(exit_code=None, stdout=b"", stderr=b""))

    result = capture(system, "git", "--json")

    assert result.exit_code == 1
    failure = json.loads(result.stdout)
    assert failure["outcome"] == "launch-error"
    assert "None" not in failure["message"]
    assert "no exit status" in failure["message"]


def test_tool_missing_from_path_fails_without_writing_a_fixture() -> None:
    system = FakeSystem(os="windows", env={"PATH": r"C:\WINDOWS", "PATHEXT": WINDOWS_PATHEXT})

    result = capture(system)

    assert result.exit_code == 1
    assert "not-found" in result.stderr
    assert system.files == {}


def test_the_user_profile_folder_is_redacted_from_provenance() -> None:
    # Capture files are attached to public issues and committed as fixtures,
    # so the account name in the profile path must not travel with them.
    system = windows_with_git(r"c:\users\Jane.Doe\scoop\shims")
    # Different case from the PATH spelling: Windows paths are case-insensitive.
    system.env["USERPROFILE"] = r"C:\Users\jane.doe"

    result = capture(system, "git", "--json")

    assert result.exit_code == 0, result.output
    provenance = written(system)["provenance"]
    redacted = r"%USERPROFILE%\scoop\shims\git.exe"
    assert provenance["resolved_path"] == redacted
    assert provenance["command"] == [redacted, "--version"]
    assert "jane" not in system.files[GIT_FILE].decode().lower()


def test_a_profile_at_a_drive_root_redacts_nothing() -> None:
    # A drive root holds no account name, and treating it as the profile
    # would rewrite every path on that drive.
    for profile in ("C:\\", "C:", "c:\\."):
        system = windows_with_git()
        system.env["USERPROFILE"] = profile

        capture(system, "git", "--json")

        assert written(system)["provenance"]["resolved_path"] == GIT_PATH, profile


def test_a_folder_that_only_starts_like_the_profile_is_kept() -> None:
    system = windows_with_git(r"C:\Users\jane.doe2\bin")
    system.env["USERPROFILE"] = r"C:\Users\jane.doe"

    capture(system, "git", "--json")

    provenance = written(system)["provenance"]
    assert provenance["resolved_path"] == r"C:\Users\jane.doe2\bin\git.exe"


def test_store_placeholders_are_never_run_or_captured() -> None:
    apps = r"C:\Users\dev\AppData\Local\Microsoft\WindowsApps"
    system = FakeSystem(
        os="windows", env={"PATH": rf"{apps};C:\Python314", "PATHEXT": WINDOWS_PATHEXT}
    )
    system.add_app_execution_alias(rf"{apps}\python.exe", STORE_PYTHON_PLACEHOLDER)
    system.add_executable(r"C:\Python314\python.exe", load_capture(PYTHON_314_WINDOWS))

    result = capture(system, "python", "--json")

    assert result.exit_code == 0, result.output
    assert system.runs == [(r"C:\Python314\python.exe", "--version")]


def test_only_store_placeholders_is_not_found() -> None:
    apps = r"C:\Users\dev\AppData\Local\Microsoft\WindowsApps"
    system = FakeSystem(os="windows", env={"PATH": apps, "PATHEXT": WINDOWS_PATHEXT})
    system.add_app_execution_alias(rf"{apps}\python.exe", STORE_PYTHON_PLACEHOLDER)

    result = capture(system, "python", "--json")

    assert result.exit_code == 1
    assert json.loads(result.stdout)["outcome"] == "not-found"
    assert system.runs == []


def test_timeout_and_launch_failure_are_errors_not_fixtures() -> None:
    for process, outcome in [
        (ProcessResult(exit_code=None, stdout=b"", stderr=b"", timed_out=True), "timeout"),
        (
            ProcessResult(exit_code=None, stdout=b"", stderr=b"", launch_error="denied"),
            "launch-error",
        ),
    ]:
        system = windows_with_git()
        add_tool(system, process)

        result = capture(system, "git", "--json")

        assert result.exit_code == 1
        assert json.loads(result.stdout)["outcome"] == outcome
        assert system.files == {}


def test_unwritable_destination_is_an_error() -> None:
    system = windows_with_git()
    system.write_error = "disk full"

    result = capture(system, "git", "--json")

    assert result.exit_code == 1
    failure = json.loads(result.stdout)
    assert failure["outcome"] == "write-failed"
    assert "disk full" in failure["message"]


def test_linux_capture_uses_posix_paths() -> None:
    system = FakeSystem(os="linux", env={"PATH": "/usr/bin"}, os_description="Ubuntu 24.04")
    system.add_executable("/usr/bin/git", load_capture(GIT_LINUX))

    result = run_cli(system, "debug", "capture", "git", "--out", "/tmp/caps")

    assert result.exit_code == 0, result.output
    assert "/tmp/caps/linux-git-2.43.0.json" in system.files


def test_debug_is_hidden_from_help_but_still_runs() -> None:
    root = CliRunner().invoke(app, ["--help"])
    group = CliRunner().invoke(app, ["debug", "--help"])

    assert "debug" not in root.stdout
    assert group.exit_code == 0
    assert "capture" in group.stdout


NVM_HOME = r"C:\Users\dev\AppData\Local\Author Software\nvm"
NVM_NODE = rf"{NVM_HOME}\installs\v24.21.0\node.exe"


def nvm_machine() -> FakeSystem:
    # node is not on PATH: only the provider can find this install.
    system = FakeSystem(
        os="windows",
        env={"PATH": r"C:\WINDOWS", "PATHEXT": WINDOWS_PATHEXT, "NVM_HOME": NVM_HOME},
    )
    system.add_executable(NVM_NODE, load_capture(NODE_WINDOWS))
    return system


def test_source_captures_an_install_a_provider_reports() -> None:
    system = nvm_machine()

    result = capture(system, "node", "--source", "nvm", "--json")

    assert result.exit_code == 0, result.output
    destination = OUT + r"\windows-node-24.21.0.json"
    assert json.loads(result.stdout)["destination"] == destination
    provenance = written(system, destination)["provenance"]
    assert provenance["command"] == [NVM_NODE, "--version"]
    assert provenance["resolved_path"] == NVM_NODE
    assert provenance["notes"] == "reported by the nvm-windows provider (source nvm), not from PATH"


def test_source_must_be_a_provider_of_that_tool() -> None:
    system = nvm_machine()

    unknown = capture(system, "node", "--source", "nosuch", "--json")
    wrong_tool = capture(system, "git", "--source", "nvm", "--json")

    assert (unknown.exit_code, wrong_tool.exit_code) == (2, 2)
    assert json.loads(unknown.stdout)["outcome"] == "unknown-source"
    assert json.loads(wrong_tool.stdout) == {
        "outcome": "unknown-source",
        "tool": "git",
        "message": "provider nvm reports no git installs (it reports: node)",
    }
    assert system.files == {}


def test_source_with_no_install_is_not_found() -> None:
    system = FakeSystem(os="windows", env={"PATH": r"C:\WINDOWS", "PATHEXT": WINDOWS_PATHEXT})

    result = capture(system, "node", "--source", "nvm", "--json")

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "outcome": "not-found",
        "tool": "node",
        "message": "nvm-windows reports no node install",
    }
