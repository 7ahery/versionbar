"""`versionbar tools`: the catalog of every tool and provider, through the CLI seam."""

import json

from fakes import FakeSystem, run_cli, windows_with_git

# The custom tool format is a built-in definition's, so these are examples
# from docs/config.md rather than anything run: `tools` runs nothing.
SSH = """
[[tools]]
id = "ssh"
name = "OpenSSH"
os = ["windows"]
binaries = ["ssh"]
version_args = ["-V"]
version_regex = 'OpenSSH_(?:for_Windows_)?(?P<version>\\d+(?:\\.\\d+)*[a-z]*\\d*)'
"""

NODE_REPLACEMENT = """
[[tools]]
id = "node"
name = "Node (my build)"
os = ["linux"]
binaries = ["node"]
version_args = ["--version"]
version_regex = 'v(?P<version>\\d+\\S*)'
"""

NODE = {"id": "node", "name": "Node.js", "os": ["windows", "linux"], "custom": False}
NVM = {"id": "nvm", "name": "nvm-windows", "os": ["windows"], "tools": ["node"]}
UV = {"id": "uv", "name": "uv", "os": ["windows"], "tools": ["python"]}


def catalog(system: FakeSystem) -> dict:
    result = run_cli(system, "tools", "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_the_catalog_lists_every_built_in_tool_and_provider_without_running_anything() -> None:
    system = windows_with_git()

    tools = catalog(system)

    assert tools["schema_version"] == 1
    assert tools["platform"] == "windows"
    assert NODE in tools["tools"]
    assert {"id": "git", "name": "Git", "os": ["windows", "linux"], "custom": False} in tools[
        "tools"
    ]
    assert tools["providers"] == [NVM, UV]
    assert system.runs == []


def test_custom_tools_follow_the_built_ins_and_replacements_stay_in_place() -> None:
    system = windows_with_git()
    system.add_config('hidden = ["git"]\n' + SSH + NODE_REPLACEMENT)

    ids_by_file_order = [tool["id"] for tool in catalog(windows_with_git())["tools"]]
    tools = catalog(system)["tools"]

    # Hidden only affects `list`; a tool for another OS is still known.
    assert [tool["id"] for tool in tools] == [*ids_by_file_order, "ssh"]
    by_id = {tool["id"]: tool for tool in tools}
    assert by_id["node"] == {
        "id": "node",
        "name": "Node (my build)",
        "os": ["linux"],
        "custom": True,
    }
    assert by_id["ssh"] == {"id": "ssh", "name": "OpenSSH", "os": ["windows"], "custom": True}
    assert by_id["git"]["custom"] is False


def test_the_catalog_on_linux_still_names_windows_only_providers() -> None:
    tools = catalog(FakeSystem(os="linux", env={"PATH": "/usr/bin"}))

    assert tools["platform"] == "linux"
    assert tools["providers"] == [NVM, UV]


def test_an_invalid_config_stops_the_catalog_with_exit_code_3() -> None:
    system = windows_with_git()
    system.add_config('pinned = ["nod"]\n')

    result = run_cli(system, "tools", "--json")

    assert result.exit_code == 3
    assert result.stdout == ""
    assert 'pinned[0]: unknown tool "nod"' in result.stderr


def test_human_output_has_a_row_per_tool_and_per_provider(monkeypatch) -> None:
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    system = windows_with_git()
    system.add_config(SSH)

    rows = [line.split() for line in run_cli(system, "tools").stdout.splitlines()]

    assert ["node", "Node.js", "windows,", "linux"] in rows
    assert ["ssh", "OpenSSH", "windows", "custom"] in rows
    assert ["nvm", "nvm-windows", "windows", "node"] in rows
