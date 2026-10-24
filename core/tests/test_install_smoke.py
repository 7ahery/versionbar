"""Smoke test at the real install seam: build the checkout the way a user would
(`uv tool install`) and run the installed command, so packaging, the entry point
and import-time dependencies are all exercised."""

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from versionbar.models import ScanResult

CORE_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def installed_command(tmp_path_factory: pytest.TempPathFactory) -> Path:
    uv = shutil.which("uv")
    assert uv, "uv is a hard prerequisite"
    root = tmp_path_factory.mktemp("uv-tool")
    env = {
        **os.environ,
        "UV_TOOL_DIR": str(root / "tools"),
        "UV_TOOL_BIN_DIR": str(root / "bin"),
    }
    # Needs network: uv resolves typer and rich from PyPI.
    subprocess.run([uv, "tool", "install", str(CORE_DIR)], env=env, check=True)
    suffix = ".exe" if sys.platform == "win32" else ""
    return root / "bin" / f"versionbar{suffix}"


def test_installed_help_works(installed_command: Path) -> None:
    result = subprocess.run(
        [str(installed_command), "--help"], capture_output=True, encoding="utf-8", check=False
    )
    assert result.returncode == 0
    assert "versionbar" in result.stdout.lower()


def test_installed_list_json_finds_git_on_the_real_machine(installed_command: Path) -> None:
    # git is preinstalled on contributor machines and both CI runner images.
    result = subprocess.run(
        [str(installed_command), "list", "--json"],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    scan = ScanResult.model_validate_json(result.stdout)
    git = next(tool for tool in scan.tools if tool.id == "git")
    assert git.status == "found"
    assert git.active is not None
    assert Path(git.active.path).is_file()


def test_installed_bare_command_prints_a_table(installed_command: Path) -> None:
    result = subprocess.run(
        [str(installed_command)], capture_output=True, encoding="utf-8", check=False
    )
    assert result.returncode == 0, result.stderr
    assert any(line.startswith("git") for line in result.stdout.splitlines())


def test_installed_version_matches_package_metadata(installed_command: Path) -> None:
    expected = tomllib.loads((CORE_DIR / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    result = subprocess.run(
        [str(installed_command), "--version"], capture_output=True, encoding="utf-8", check=False
    )
    assert result.returncode == 0
    assert result.stdout.strip() == expected
