"""The user config file, through the CLI seam.

The custom tool is OpenSSH: there is no built-in definition for it yet, and a
real capture of Windows `ssh -V` exists, so a config-defined tool is tested
against real output.
"""

import json
from dataclasses import replace

import pytest

from fakes import GIT_WINDOWS, FakeSystem, load_capture, run_cli, windows_with_git

GIT_PATH = r"C:\Program Files\Git\cmd\git.exe"
SSH_PATH = r"C:\WINDOWS\System32\OpenSSH\ssh.exe"

SSH_TOOL = """
[[tools]]
id = "ssh"
name = "OpenSSH"
os = ["windows"]
binaries = ["ssh"]
version_args = ["-V"]
version_regex = 'OpenSSH_(?:for_Windows_)?(?P<version>\\d+(?:\\.\\d+)*[a-z]*\\d*)'
"""


def machine(config: str | None = None) -> FakeSystem:
    system = windows_with_git()
    system.env["PATH"] += r";C:\WINDOWS\System32\OpenSSH"
    system.add_executable(SSH_PATH, load_capture("ssh/windows-ssh-9.5p2.json"))
    if config is not None:
        system.add_config(config)
    return system


def tools(system: FakeSystem, *args: str) -> list[dict]:
    result = run_cli(system, *args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["tools"]


def test_a_custom_tool_from_the_config_is_listed_with_its_real_version() -> None:
    listed = {tool["id"]: tool for tool in tools(machine(SSH_TOOL), "list")}

    assert listed["ssh"]["name"] == "OpenSSH"
    assert listed["ssh"]["status"] == "found"
    assert listed["ssh"]["active"]["version"] == "9.5p2"
    assert listed["ssh"]["active"]["path"] == SSH_PATH


def test_show_and_check_resolve_a_custom_tool() -> None:
    system = machine(SSH_TOOL)

    shown = tools(system, "show", "ssh")
    checked = run_cli(system, "check", "ssh@>=9.5", "--json")

    assert [tool["id"] for tool in shown] == ["ssh"]
    assert shown[0]["active"]["version"] == "9.5p2"
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.stdout)["requirements"][0]["outcome"] == "passed"


def test_hidden_tools_are_left_out_of_list() -> None:
    system = machine('hidden = ["git", "ssh"]\n' + SSH_TOOL)

    listed = [tool["id"] for tool in tools(system, "list")]
    bare = [tool["id"] for tool in tools(system)]

    assert "git" not in listed
    assert "ssh" not in listed
    assert listed == bare
    assert listed  # the other tools are still there


def test_show_and_check_still_resolve_hidden_tools_when_asked_for() -> None:
    system = machine('hidden = ["git", "ssh"]\n' + SSH_TOOL)

    shown = tools(system, "show", "git", "ssh")
    checked = run_cli(system, "check", "git", "ssh@>=10", "--json")

    assert [(tool["id"], tool["status"]) for tool in shown] == [("git", "found"), ("ssh", "found")]
    report = json.loads(checked.stdout)["requirements"]
    assert [(item["tool"], item["outcome"]) for item in report] == [
        ("git", "passed"),
        ("ssh", "unmet"),
    ]
    assert checked.exit_code == 1


def test_list_order_without_config_is_built_ins_by_id_then_custom_tools_in_file_order() -> None:
    second = SSH_TOOL.replace('id = "ssh"', 'id = "openssh"')

    assert [tool["id"] for tool in tools(machine(SSH_TOOL + second), "list")] == [
        "cargo",
        "composer",
        "dotnet",
        "git",
        "go",
        "java",
        "node",
        "php",
        "python",
        "ruby",
        "rustc",
        "rustup",
        "uv",
        "ssh",
        "openssh",
    ]


def test_pinned_tools_come_first_then_ordered_ones_then_the_rest_in_default_order() -> None:
    config = 'pinned = ["uv", "ssh"]\norder = ["python"]\n' + SSH_TOOL

    assert [tool["id"] for tool in tools(machine(config), "list")] == [
        "uv",
        "ssh",
        "python",
        "cargo",
        "composer",
        "dotnet",
        "git",
        "go",
        "java",
        "node",
        "php",
        "ruby",
        "rustc",
        "rustup",
    ]


def test_show_keeps_the_requested_order_whatever_the_pins() -> None:
    system = machine('pinned = ["uv"]\n')

    assert [tool["id"] for tool in tools(system, "show", "git", "uv")] == ["git", "uv"]


def slow_git_machine(config: str, seconds: float) -> FakeSystem:
    system = machine(config)
    system.add_executable(GIT_PATH, replace(load_capture(GIT_WINDOWS), seconds=seconds))
    return system


def git_status(system: FakeSystem) -> tuple[str, list[str]]:
    git = next(tool for tool in tools(system, "list") if tool["id"] == "git")
    return git["status"], git["notes"]


def test_without_config_a_command_slower_than_5_s_times_out() -> None:
    assert git_status(slow_git_machine("", 5.5)) == (
        "timeout",
        [rf"{GIT_PATH} did not answer within 5 s"],
    )


def test_the_global_timeout_applies_to_every_tool() -> None:
    assert git_status(slow_git_machine("timeout = 8\n", 7))[0] == "found"
    assert git_status(slow_git_machine("timeout = 2.5\n", 3)) == (
        "timeout",
        [rf"{GIT_PATH} did not answer within 2.5 s"],
    )


def test_a_per_tool_timeout_wins_over_the_global_one() -> None:
    config = "timeout = 2\n[timeouts]\ngit = 10\nnode = 1\n"

    assert git_status(slow_git_machine(config, 9))[0] == "found"
    assert git_status(slow_git_machine("timeout = 20\n[timeouts]\ngit = 1\n", 2))[1] == [
        rf"{GIT_PATH} did not answer within 1 s"
    ]


CONFIG_PATH = r"C:\Users\dev\AppData\Roaming\versionbar\config.toml"


def config_error(config: str, *args: str) -> str:
    """stderr of a command run over an invalid config, after checking it failed as one."""
    result = run_cli(machine(config), *(args or ("list", "--json")))
    assert result.exit_code == 3, result.output
    assert result.stdout == ""
    assert result.stderr.startswith(f"invalid config file {CONFIG_PATH}\n"), result.stderr
    return result.stderr


def test_a_toml_syntax_error_names_the_file_and_line() -> None:
    assert "line 2" in config_error('pinned = ["git"]\nhidden = git\n')


@pytest.mark.parametrize(
    ("config", "problem"),
    [
        ("colour = true\n", "  colour: unknown key"),
        ("[app]\nupdate = false\n", "  app.update: unknown key"),
        ('timeout = "fast"\n', "  timeout: "),
        ("timeout = 0\n", "  timeout: "),
        ("timeout = inf\n", "  timeout: "),
        ("[timeouts]\ngit = -1\n", "  timeouts.git: "),
        ('[timeouts]\n"my tool" = "x"\n', '  timeouts."my tool": Input should be a valid number'),
        ('pinned = "git"\n', "  pinned: "),
        ("[app]\nupdate_check = 1\n", "  app.update_check: "),
        (SSH_TOOL.replace("(?P<version>", "(?P<v>"), "  tools[0].version_regex: "),
        (SSH_TOOL.replace("(?:", "(?"), "  tools[0].version_regex: not a valid regex"),
        (SSH_TOOL.replace('name = "OpenSSH"\n', ""), "  tools[0].name: missing"),
        (SSH_TOOL + "colour = 1\n", "  tools[0].colour: unknown key"),
    ],
)
def test_an_invalid_value_names_its_key_and_the_problem(config: str, problem: str) -> None:
    assert f"\n{problem}" in config_error(config)


def test_every_problem_is_reported_at_once() -> None:
    lines = config_error("colour = true\ntimeout = 0\n").splitlines()

    assert sorted(line.split(":")[0] for line in lines[1:]) == ["  colour", "  timeout"]


@pytest.mark.parametrize(
    ("config", "problem"),
    [
        ('pinned = ["git", "nod"]\n', '  pinned[1]: unknown tool "nod"'),
        ('order = ["nod"]\n', '  order[0]: unknown tool "nod"'),
        ('hidden = ["nod"]\n', '  hidden[0]: unknown tool "nod"'),
        ("[timeouts]\nnod = 3\n", '  timeouts.nod: unknown tool "nod"'),
        # Quoted, as TOML writes them, so the dot is not read as a nested table.
        ('[timeouts]\n"my.tool" = 3\n', '  timeouts."my.tool": unknown tool "my.tool"'),
        ('pinned = ["git", "uv", "git"]\n', '  pinned[2]: "git" is already listed'),
        ('pinned = ["git"]\norder = ["uv", "git"]\n', '  order[1]: "git" is already in pinned'),
        ('pinned = ["git"]\nhidden = ["git"]\n', '  hidden[0]: "git" is already in pinned'),
        ('order = ["git"]\nhidden = ["git"]\n', '  hidden[0]: "git" is already in order'),
        (SSH_TOOL + SSH_TOOL, '  tools[1].id: "ssh" is already a custom tool'),
    ],
)
def test_tool_ids_in_the_config_must_be_known_and_listed_once(config: str, problem: str) -> None:
    assert f"\n{problem}\n" in config_error(config)


@pytest.mark.parametrize("args", [["list"], ["show", "git"], ["check", "git"], ["--json"]])
def test_every_scanning_command_refuses_an_invalid_config(args: list[str]) -> None:
    result = run_cli(machine("colour = true\n"), *args)

    assert result.exit_code == 3
    assert "colour: unknown key" in result.stderr


def test_an_unreadable_config_file_is_an_error_not_defaults() -> None:
    system = machine()
    system.add_unreadable(system.config_path, "[WinError 5] Access is denied")

    result = run_cli(system, "list")

    assert result.exit_code == 3
    assert result.stderr == (
        f"invalid config file {CONFIG_PATH}\n  cannot read it: [WinError 5] Access is denied\n"
    )


def test_a_config_file_must_be_utf_8_but_may_start_with_a_bom() -> None:
    system = machine()
    system.add_content(system.config_path, 'hidden = ["g\xeft"]\n'.encode("latin-1"))
    with_bom = machine()
    with_bom.add_content(with_bom.config_path, b'\xef\xbb\xbfhidden = ["git"]\n')

    assert "not UTF-8" in run_cli(system, "list").stderr
    assert "git" not in [tool["id"] for tool in tools(with_bom, "list")]


def test_show_and_check_use_the_configured_timeouts() -> None:
    system = slow_git_machine("[timeouts]\ngit = 1\n", 2)

    shown = tools(system, "show", "git")
    checked = json.loads(run_cli(system, "check", "git", "--json").stdout)

    assert (shown[0]["status"], shown[0]["notes"]) == (
        "timeout",
        [rf"{GIT_PATH} did not answer within 1 s"],
    )
    assert checked["requirements"][0]["outcome"] == "timeout"


def test_preferences_may_name_a_tool_of_another_os() -> None:
    linux_only = SSH_TOOL.replace('id = "ssh"', 'id = "lssh"').replace('"windows"', '"linux"')
    config = 'pinned = ["lssh"]\nhidden = ["ssh"]\n' + SSH_TOOL + linux_only

    listed = [tool["id"] for tool in tools(machine(config), "list")]

    assert "lssh" not in listed
    assert "ssh" not in listed
    assert listed[0] == "cargo"


def test_a_custom_tool_with_a_built_in_id_replaces_the_built_in_in_its_place() -> None:
    custom_git = """
[[tools]]
id = "git"
name = "Git (mine)"
os = ["windows"]
binaries = ["git"]
version_args = ["--version"]
version_regex = 'git version (?P<version>\\d+\\.\\d+)'
"""
    listed = tools(machine(custom_git), "list")

    ids = [tool["id"] for tool in listed]
    assert ids.count("git") == 1
    # Replaced in the built-in's own place, not appended.
    assert ids[:5] == ["cargo", "composer", "dotnet", "git", "go"]
    mine = listed[ids.index("git")]
    assert (mine["name"], mine["active"]["version"]) == ("Git (mine)", "2.55")
