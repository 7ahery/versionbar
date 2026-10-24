"""`versionbar check` over a fake system, through the CLI seam.

Versions come from real captures: git 2.55.0.windows.2 (Windows), git 2.43.0
(Linux), OpenSSH 9.5p2. Tools without a built-in definition yet use draft
definitions, as test_scan_robustness does.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from versionbar import cli, definition
from versionbar.definition import ToolDefinition
from versionbar.system import ProcessResult

from fakes import GIT_LINUX, Capture, FakeSystem, load_capture, run_cli, windows_with_git

SSH_PATH = r"C:\WINDOWS\System32\OpenSSH\ssh.exe"
GIT_PATH = r"C:\Program Files\Git\cmd\git.exe"

SSH = ToolDefinition(
    id="ssh",
    name="OpenSSH",
    os=["windows"],
    binaries=["ssh"],
    version_args=["-V"],
    version_regex=r"OpenSSH_(?:for_Windows_)?(?P<version>\d+(?:\.\d+)*[a-z]*\d*)",
)
# Real ssh output, but a pattern that captures text with no version number in it.
SSH_NO_NUMBER = SSH.model_copy(
    update={"id": "ssh-name", "version_regex": r"(?P<version>OpenSSH_for_Windows)"}
)
LINUX_ONLY = ToolDefinition(
    id="linuxy",
    name="Linux only",
    os=["linux"],
    binaries=["linuxy"],
    version_args=["--version"],
    version_regex=r"(?P<version>\d+(?:\.\d+)*)",
)


@pytest.fixture(autouse=True)
def drafts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "builtin_definitions",
        lambda: [*definition.builtin_definitions(), SSH, SSH_NO_NUMBER, LINUX_ONLY],
    )


def machine() -> FakeSystem:
    system = windows_with_git()
    system.env["PATH"] += r";C:\WINDOWS\System32\OpenSSH"
    system.add_executable(SSH_PATH, load_capture("ssh/windows-ssh-9.5p2.json"))
    return system


def check(*args: str, system: FakeSystem | None = None):
    return run_cli(system or machine(), "check", *args)


def check_json(*args: str, system: FakeSystem | None = None) -> tuple[int, dict]:
    result = check(*args, "--json", system=system)
    return result.exit_code, json.loads(result.stdout)


@pytest.mark.parametrize(
    ("requirement", "passes"),
    [
        # git reports 2.55.0.windows.2: the vendor suffix never takes part.
        ("git@>=2.55.0", True),
        ("git@>=2.55", True),
        ("git@>=2.56", False),
        ("git@>2.55.0", False),
        ("git@>2.54.9", True),
        ("git@<=2.55.0", True),
        ("git@<=2.54", False),
        ("git@<2.55.0", False),
        ("git@<2.55.1", True),
        ("git@==2.55.0", True),
        ("git@==2.55", True),
        ("git@==2.55.1", False),
        # Numeric, not text, comparison: 2.55 is above 2.9 and 2.100 above 2.55.
        ("git@>2.9", True),
        ("git@<2.100", True),
        ("git@>=2.50,<3", True),
        ("git@>=2.50,<2.55", False),
        ("git@>=2.56,<3", False),
        ("git@ >= 2.50 , < 3 ", True),
        ("git", True),
    ],
)
def test_version_specs_are_evaluated_against_the_active_install(requirement, passes) -> None:
    code, doc = check_json(requirement)

    assert (code, doc["passed"]) == ((0 if passes else 1), passes)
    [result] = doc["requirements"]
    assert result["requirement"] == requirement
    assert result["passed"] is passes
    assert result["outcome"] == ("passed" if passes else "unmet")
    assert result["version"] == "2.55.0.windows.2"


def test_json_explains_every_requirement() -> None:
    code, doc = check_json("git", "git@>=2.50,<3", "ssh@>=10", "git@>=3")

    assert code == 1
    assert doc["passed"] is False
    assert doc["platform"] == "windows"
    assert doc["schema_version"] == 1
    assert list(doc)[0] == "schema_version"
    assert doc["scanned_at"] == "2026-10-23T21:04:52Z"
    assert [
        (r["requirement"], r["tool"], r["spec"], r["outcome"]) for r in doc["requirements"]
    ] == [
        ("git", "git", None, "passed"),
        ("git@>=2.50,<3", "git", ">=2.50,<3", "passed"),
        ("ssh@>=10", "ssh", ">=10", "unmet"),
        ("git@>=3", "git", ">=3", "unmet"),
    ]
    ssh = doc["requirements"][2]
    assert ssh["version"] == "9.5p2"
    assert ssh["path"] == SSH_PATH
    assert ssh["message"] == "ssh 9.5p2 does not satisfy >=10"
    assert doc["requirements"][0]["message"] == "git 2.55.0.windows.2 is installed"


def test_the_readme_example_over_real_node_python_and_git_captures() -> None:
    system = machine()
    system.env["PATH"] += r";C:\tools"
    system.add_executable(r"C:\tools\node.exe", load_capture("node/windows-node-24.21.0.json"))
    system.add_executable(r"C:\tools\python.exe", load_capture("python/windows-python-3.14.8.json"))

    ok = check("git", "node@>=20", "python@>=3.12,<4", system=system)
    assert ok.exit_code == 0, ok.output
    assert len(ok.stdout.splitlines()) == 3

    too_old = check_json("node@>=20,<24", "python@>=3.15", "git", system=system)
    assert too_old[0] == 1
    assert [(r["tool"], r["version"], r["outcome"]) for r in too_old[1]["requirements"]] == [
        ("node", "24.21.0", "unmet"),
        ("python", "3.14.8", "unmet"),
        ("git", "2.55.0.windows.2", "passed"),
    ]


@pytest.mark.parametrize(
    ("printed", "requirement", "passes"),
    [
        ("3.14.0rc1", "python@>=3.14", False),
        ("3.14.0rc1", "python@>=3.13", True),
        ("3.14.0rc1", "python@<3.14", True),
        ("3.14.0rc1", "python@==3.14", False),
        ("3.15.0a2", "python@>=3.15", False),
        ("3.15.0a2", "python@<3.15", True),
        ("3.14.0-beta.1", "python@<3.14", True),
        ("3.14.0B2", "python@>=3.14", False),
        ("3.14.0.dev", "python@>=3.14", False),
        # Not pre-release markers: ignored like any other suffix.
        ("3.14.0abc", "python@>=3.14", True),
        ("3.14.0p2", "python@==3.14", True),
        ("3.14.0+local", "python@>=3.14", True),
    ],
)
def test_a_prerelease_ranks_just_below_its_release(printed, requirement, passes) -> None:
    # No real pre-release capture exists on this machine, so the stdout is the
    # shape the python definition parses; this is a transport-style stand-in.
    system = FakeSystem(os="linux", env={"PATH": "/usr/bin"})
    output = ProcessResult(exit_code=0, stdout=f"Python {printed}\n".encode(), stderr=b"")
    system.add_executable("/usr/bin/python", Capture(("--version",), output))

    result = check(requirement, "--json", system=system)

    assert result.exit_code == (0 if passes else 1), result.output
    assert json.loads(result.stdout)["requirements"][0]["version"] == printed


def test_multiple_requirements_pass_only_when_all_pass() -> None:
    assert check("git@>=2", "ssh@>=9").exit_code == 0
    assert check("git@>=2", "ssh@>=10").exit_code == 1
    assert check("ssh@>=10", "git@>=2").exit_code == 1


def test_a_missing_tool_fails_presence_and_version_requirements() -> None:
    system = machine()
    system.env["PATH"] = r"C:\WINDOWS\system32"

    for requirement in ("git", "git@>=1"):
        code, doc = check_json(requirement, system=system)
        assert code == 1
        [result] = doc["requirements"]
        assert (result["outcome"], result["version"], result["path"]) == ("missing", None, None)
        assert result["message"].startswith("git is not installed: not found on PATH")


def test_a_hanging_tool_fails_with_timeout() -> None:
    system = machine()
    hang = ProcessResult(exit_code=None, stdout=b"", stderr=b"", timed_out=True)
    system.add_executable(SSH_PATH, Capture(("-V",), hang))

    code, doc = check_json("ssh", "git", system=system)

    assert code == 1
    assert [r["outcome"] for r in doc["requirements"]] == ["timeout", "passed"]
    assert "did not answer within 5 s" in doc["requirements"][0]["message"]


def test_a_tool_that_cannot_report_its_version_fails_with_error() -> None:
    system = machine()
    # Real output of a command rejecting its argument, replayed as ssh's answer.
    failing = load_capture("git/windows-git-badflag-unknown-version.json")
    system.add_executable(SSH_PATH, Capture(("-V",), failing.result))

    code, doc = check_json("ssh", system=system)

    assert code == 1
    [result] = doc["requirements"]
    assert result["outcome"] == "error"
    assert "unknown option: --no-such-flag" in result["message"]


def test_only_the_active_install_counts() -> None:
    # Two gits on PATH: the first (2.55.0) is active, the second (2.43.0) is not.
    system = windows_with_git()
    system.add_executable(r"C:\Users\dev\bin\git.exe", load_capture(GIT_LINUX))

    code, doc = check_json("git@<2.50", system=system)

    # 2.43.0 would satisfy <2.50, but it is shadowed by the active 2.55.0.
    assert code == 1
    assert doc["requirements"][0]["outcome"] == "unmet"
    assert doc["requirements"][0]["version"] == "2.55.0.windows.2"
    assert check("git@>=2.55", system=system).exit_code == 0


def test_linux_version_from_a_real_capture() -> None:
    system = FakeSystem(os="linux", env={"PATH": "/usr/bin"})
    system.add_executable("/usr/bin/git", load_capture(GIT_LINUX))

    assert check("git@>=2.43,<2.44", system=system).exit_code == 0
    assert check("git@>2.43.0", system=system).exit_code == 1


def test_a_version_without_a_number_cannot_satisfy_a_range_but_satisfies_presence() -> None:
    assert check("ssh-name").exit_code == 0

    code, doc = check_json("ssh-name@>=1")
    assert code == 1
    [result] = doc["requirements"]
    assert result["outcome"] == "not-comparable"
    assert result["version"] == "OpenSSH_for_Windows"
    assert "cannot be compared" in result["message"]


def test_only_the_requested_tools_are_scanned_once() -> None:
    system = machine()

    check("git", "git@>=1", "git@<9", system=system)

    assert system.runs == [(GIT_PATH, "--version")]


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("nosuchtool",),
        ("nosuchtool@>=1",),
        ("git", "nosuchtool"),
        ("linuxy",),
        ("@>=1",),
        ("git@",),
        ("git@2",),
        ("git@>=",),
        ("git@>=x",),
        ("git@>=1.",),
        ("git@>=1.2.x",),
        ("git@=2",),
        ("git@~=2",),
        ("git@>=1,",),
        ("git@,<3",),
        ("git@>=1;<3",),
        ("git@>=2@3",),
        ("git@>=2.55.0.windows.2",),
        ("git@>=-1",),
    ],
)
def test_malformed_or_unknown_requests_are_usage_errors(args) -> None:
    system = machine()

    result = check(*args, system=system)

    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr.strip()
    # Nothing was scanned: a bad request must not look like an unmet one.
    assert system.runs == []


def test_usage_errors_stay_plain_text_with_json() -> None:
    result = check("git@2", "--json")

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "git@2" in result.stderr


def test_usage_errors_name_the_problem() -> None:
    unknown = check("nosuchtool").stderr
    assert "Unknown tool: nosuchtool" in unknown
    assert "known tools:" in unknown
    assert "linuxy is not available on windows" in check("linuxy").stderr
    assert "needs an operator" in check("git@2").stderr
    assert "at least one requirement" in check().stderr


def test_every_usage_error_is_reported_together() -> None:
    stderr = check("nosuchtool", "git@2", "linuxy").stderr

    assert "nosuchtool" in stderr
    assert "git@2" in stderr
    assert "linuxy" in stderr


def test_human_output_marks_each_requirement() -> None:
    result = check("git@>=2.50", "ssh@>=10", "git")

    assert result.exit_code == 1
    lines = result.stdout.splitlines()
    assert len(lines) == 3
    assert lines[0].split()[:2] == ["pass", "git@>=2.50"]
    assert lines[1].split()[:2] == ["FAIL", "ssh@>=10"]
    assert "ssh 9.5p2 does not satisfy >=10" in lines[1]
    assert lines[2].split()[:2] == ["pass", "git"]


def test_json_runs_never_load_rich() -> None:
    program = (
        "import sys\n"
        "import fakes\n"
        "from versionbar.cli import main\n"
        "sys.argv = ['versionbar', 'check', 'git@>=2', '--json']\n"
        "try:\n"
        "    main(fakes.windows_with_git())\n"
        "except SystemExit:\n"
        "    pass\n"
        "finally:\n"
        "    sys.stderr.write('rich imported' if 'rich' in sys.modules else 'rich absent')\n"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parent)}
    done = subprocess.run([sys.executable, "-c", program], capture_output=True, env=env)

    assert done.stderr.decode() == "rich absent"
    assert json.loads(done.stdout)["passed"] is True
