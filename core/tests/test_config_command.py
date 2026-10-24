"""`versionbar config`: the preferences query, through the CLI seam.

The app runs `config --json` as its second fixed core invocation (ADR 0011),
so the JSON here is a contract like the scan's.
"""

import json

from fakes import FakeSystem, run_cli, windows_with_git

WINDOWS_PATH = r"C:\Users\dev\AppData\Roaming\versionbar\config.toml"


def query(system: FakeSystem) -> tuple[int, dict]:
    result = run_cli(system, "config", "--json")
    return result.exit_code, json.loads(result.stdout)


def with_config(text: str) -> FakeSystem:
    system = windows_with_git()
    system.add_config(text)
    return system


def test_without_a_config_file_the_query_reports_its_path_and_the_defaults() -> None:
    assert query(windows_with_git()) == (
        0,
        {
            "schema_version": 1,
            "config_path": WINDOWS_PATH,
            "config_exists": False,
            "problems": [],
            "preferences": {"update_check": True, "pinned": [], "order": []},
        },
    )


def test_the_query_reports_the_configured_preferences() -> None:
    system = with_config('pinned = ["uv", "git"]\norder = ["node"]\n[app]\nupdate_check = false\n')

    code, document = query(system)

    assert code == 0
    assert document["config_exists"] is True
    assert document["preferences"] == {
        "update_check": False,
        "pinned": ["uv", "git"],
        "order": ["node"],
    }


def test_the_config_path_follows_the_platform_config_folder() -> None:
    system = FakeSystem(os="linux", env={"PATH": "/usr/bin"})

    assert query(system)[1]["config_path"] == "/home/dev/.config/versionbar/config.toml"


def test_an_invalid_config_still_reports_its_path_with_the_problems_and_no_preferences() -> None:
    code, document = query(with_config("[app]\nupdate_check = false\ncolour = 1\n"))

    assert code == 3
    assert document == {
        "schema_version": 1,
        "config_path": WINDOWS_PATH,
        "config_exists": True,
        "problems": [{"key": "app.colour", "message": "unknown key"}],
        "preferences": None,
    }


def test_human_output_shows_the_path_and_every_setting_in_effect() -> None:
    system = with_config('hidden = ["uv"]\n[timeouts]\ngit = 12.5\n[app]\nupdate_check = false\n')

    result = run_cli(system, "config")

    assert result.exit_code == 0
    lines = [" ".join(line.split()) for line in result.stdout.splitlines()]
    assert lines == [
        f"Config file {WINDOWS_PATH}",
        "Update check off",
        "Pinned none",
        "Order none",
        "Hidden uv",
        "Timeout 5 s",
        "Timeouts git 12.5 s",
        "Custom tools none",
    ]


def test_human_output_says_when_the_file_does_not_exist_yet() -> None:
    result = run_cli(windows_with_git(), "config")

    assert "not created yet; every default applies" in result.stdout


def test_human_output_of_an_invalid_config_lists_the_problems() -> None:
    result = run_cli(with_config("timeout = 0\n"), "config")

    assert result.exit_code == 3
    assert WINDOWS_PATH in result.stdout
    assert "timeout: Input should be greater than 0" in result.stdout


def test_the_query_never_runs_a_tool() -> None:
    system = windows_with_git()

    run_cli(system, "config", "--json")

    assert system.runs == []
