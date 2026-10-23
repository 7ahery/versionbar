"""Smoke test at the real install seam: build the checkout the way a user would
(`uv tool install`) and run the installed command, so packaging, the entry point
and import-time dependencies are all exercised."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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
    subprocess.run([uv, "tool", "install", str(CORE_DIR)], env=env, check=True)
    suffix = ".exe" if sys.platform == "win32" else ""
    return root / "bin" / f"versionbar{suffix}"


def test_installed_help_works(installed_command: Path) -> None:
    result = subprocess.run(
        [str(installed_command), "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert "versionbar" in result.stdout.lower()
