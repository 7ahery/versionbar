"""Smoke test at the real install seam: install the built wheel and sdist (a fresh `uv build`,
or the release artifacts named by VERSIONBAR_DIST_DIR) with `uv tool install` from outside the
checkout and run the installed command, so packaging, shipped resources, the entry point and
import-time dependencies are all exercised."""

import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from versionbar.models import ScanResult

CORE_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = CORE_DIR.parent


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """The wheel and sdist to install: CI's own release artifacts when VERSIONBAR_DIST_DIR
    names them (so the exact files about to be published are the ones tested), else a fresh
    `uv build` of the checkout."""
    given = os.environ.get("VERSIONBAR_DIST_DIR")
    if given:
        dist = Path(given)
    else:
        uv = shutil.which("uv")
        assert uv, "uv is a hard prerequisite"
        dist = tmp_path_factory.mktemp("dist")
        subprocess.run([uv, "build", str(CORE_DIR), "--out-dir", str(dist)], check=True)
    wheels = list(dist.glob("versionbar-*.whl"))
    sdists = list(dist.glob("versionbar-*.tar.gz"))
    assert len(wheels) == 1 and len(sdists) == 1, f"expected one wheel and one sdist in {dist}"
    return {"wheel": wheels[0], "sdist": sdists[0]}


@pytest.fixture(scope="module", params=["wheel", "sdist"])
def installed_command(
    request: pytest.FixtureRequest,
    artifacts: dict[str, Path],
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    uv = shutil.which("uv")
    assert uv, "uv is a hard prerequisite"
    root = tmp_path_factory.mktemp("uv-tool")
    env = {
        **os.environ,
        "UV_TOOL_DIR": str(root / "tools"),
        "UV_TOOL_BIN_DIR": str(root / "bin"),
        # The core must run on a uv-managed Python, never a system one.
        "UV_PYTHON_PREFERENCE": "only-managed",
    }
    # Needs network: uv resolves typer and rich from PyPI. Runs from outside the checkout so
    # nothing is picked up from the working tree.
    subprocess.run(
        [uv, "tool", "install", str(artifacts[request.param])], env=env, cwd=root, check=True
    )
    suffix = ".exe" if sys.platform == "win32" else ""
    return root / "bin" / f"versionbar{suffix}"


# platformdirs asks Windows for the Roaming folder itself and ignores APPDATA, so a throwaway
# config folder is only possible elsewhere; the fake-system tests cover the same behaviour.
no_windows_redirect = pytest.mark.skipif(
    sys.platform == "win32", reason="the config folder cannot be redirected on Windows"
)


def _run(command: Path, *args: str, env: dict[str, str] | None = None):
    return subprocess.run(
        [str(command), *args],
        capture_output=True,
        encoding="utf-8",
        cwd=command.parent,
        env={**os.environ, **(env or {})},
        check=False,
    )


def test_installed_help_works(installed_command: Path) -> None:
    result = _run(installed_command, "--help")
    assert result.returncode == 0
    assert "versionbar" in result.stdout.lower()


def test_installed_list_json_finds_git_on_the_real_machine(installed_command: Path) -> None:
    # git is preinstalled on contributor machines and both CI runner images.
    # Python reports every import on stderr, so the real `--json` path can be
    # checked for staying clear of Rich.
    result = _run(installed_command, "list", "--json", env={"PYTHONPROFILEIMPORTTIME": "1"})
    assert result.returncode == 0, result.stderr
    imported = [line.rsplit("|", 1)[-1].strip() for line in result.stderr.splitlines()]
    assert "versionbar.cli" in imported
    assert not [name for name in imported if name.split(".")[0] == "rich"]
    output = json.loads(result.stdout)
    schema = json.loads((REPO_DIR / "schema" / "output.schema.json").read_text("utf-8"))
    assert [error.message for error in Draft202012Validator(schema).iter_errors(output)] == []
    scan = ScanResult.model_validate(output)
    git = next(tool for tool in scan.tools if tool.id == "git")
    assert git.status == "found"
    assert git.active is not None
    assert Path(git.active.path).is_file()


def test_installed_bare_command_prints_a_table(installed_command: Path) -> None:
    result = _run(installed_command)
    assert result.returncode == 0, result.stderr
    assert any(line.startswith("git") for line in result.stdout.splitlines())


def test_installed_version_matches_the_built_artifact(
    installed_command: Path, artifacts: dict[str, Path]
) -> None:
    # The wheel filename carries the PEP 440 version (0.1.0rc1), which is what the installed
    # metadata reports; pyproject holds release-please's semver spelling (0.1.0-rc.1) for
    # prereleases, so comparing with it would fail every prerelease.
    expected = artifacts["wheel"].name.split("-")[1]
    result = _run(installed_command, "--version")
    assert result.returncode == 0
    assert result.stdout.strip() == expected


def test_installed_package_ships_the_starter_config(installed_command: Path) -> None:
    tools = installed_command.parent.parent / "tools"
    shipped = list(tools.rglob("versionbar/starter_config.toml"))

    assert len(shipped) == 1
    assert (
        shipped[0].read_bytes()
        == (CORE_DIR / "src" / "versionbar" / "starter_config.toml").read_bytes()
    )


def test_installed_config_query_answers_as_json(installed_command: Path) -> None:
    result = _run(installed_command, "config", "--json")
    # This machine's own config decides 0 or 3; either way the document is JSON.
    assert result.returncode in (0, 3), result.stderr
    assert json.loads(result.stdout)["config_path"].endswith("config.toml")


def test_installed_package_ships_every_definition(installed_command: Path) -> None:
    tools = installed_command.parent.parent / "tools"
    shipped = {p.name for p in next(tools.rglob("versionbar/definitions")).glob("*.toml")}
    source = {p.name for p in (CORE_DIR / "src" / "versionbar" / "definitions").glob("*.toml")}

    assert source
    assert shipped == source


def test_installed_package_carries_the_licence(installed_command: Path) -> None:
    tools = installed_command.parent.parent / "tools"
    licences = list(tools.rglob("versionbar-*.dist-info/licenses/LICENSE"))

    assert len(licences) == 1
    assert licences[0].read_bytes() == (REPO_DIR / "LICENSE").read_bytes()


def test_sdist_carries_the_licence(artifacts: dict[str, Path]) -> None:
    with tarfile.open(artifacts["sdist"]) as archive:
        names = archive.getnames()
    assert any(name.endswith("/LICENSE") for name in names)


def test_installed_tools_and_schema_commands(installed_command: Path) -> None:
    tools = _run(installed_command, "tools", "--json")
    assert tools.returncode == 0, tools.stderr
    assert "git" in [tool["id"] for tool in json.loads(tools.stdout)["tools"]]

    schema = _run(installed_command, "schema")
    assert schema.returncode == 0, schema.stderr
    committed = json.loads((REPO_DIR / "schema" / "output.schema.json").read_text("utf-8"))
    assert json.loads(schema.stdout) == committed


def test_installed_show_and_check_find_git(installed_command: Path) -> None:
    show = _run(installed_command, "show", "git", "--json")
    assert show.returncode == 0, show.stderr
    assert json.loads(show.stdout)["tools"][0]["id"] == "git"

    check = _run(installed_command, "check", "git")
    assert check.returncode == 0, check.stdout + check.stderr


def test_installed_debug_capture_writes_a_fixture(installed_command: Path, tmp_path: Path) -> None:
    result = _run(installed_command, "debug", "capture", "git", "--out", str(tmp_path))

    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir())


@no_windows_redirect
def test_installed_config_query_names_the_resolved_path(
    installed_command: Path, tmp_path: Path
) -> None:
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    result = _run(installed_command, "config", "--json", env=env)

    assert result.returncode == 0, result.stderr
    assert Path(json.loads(result.stdout)["config_path"]) == tmp_path / "versionbar" / "config.toml"


@no_windows_redirect
def test_installed_config_custom_and_hidden_tools_take_effect(
    installed_command: Path, tmp_path: Path
) -> None:
    folder = tmp_path / "versionbar"
    folder.mkdir()
    (folder / "config.toml").write_text(
        'hidden = ["uv"]\n\n[[tools]]\nid = "mygit"\nname = "My git"\n'
        'os = ["windows", "linux"]\nbinaries = ["git"]\nversion_args = ["--version"]\n'
        "version_regex = 'git version (?P<version>\\d+(?:\\.\\d+)*)'\n",
        encoding="utf-8",
    )
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    result = _run(installed_command, "list", "--json", env=env)

    assert result.returncode == 0, result.stderr
    tools = {t["id"]: t for t in json.loads(result.stdout)["tools"]}
    assert "uv" not in tools
    assert tools["mygit"]["status"] == "found"
