"""`versionbar schema` and the committed contracts under `schema/`, through the CLI seam.

The committed files are what consumers (the UI, scripts, agents) read, so the
tests check them directly: the command must print exactly the committed
output schema, and real command output must validate against it.
"""

import json
import tomllib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.protocols import Validator
from pydantic import ValidationError

from versionbar.definition import ToolDefinition

from fakes import FakeSystem, run_cli, windows_with_git

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"


def committed(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text("utf-8"))


def output_validator() -> Validator:
    return Draft202012Validator(committed("output.schema.json"))


def errors(validator: Validator, instance: object) -> list[str]:
    return [error.message for error in validator.iter_errors(instance)]


@pytest.mark.parametrize("args", [["schema"], ["schema", "--json"]])
def test_schema_prints_the_committed_output_schema(args: list[str]) -> None:
    result = run_cli(windows_with_git(), *args)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == committed("output.schema.json")


def test_schema_is_a_valid_draft_2020_12_schema() -> None:
    Draft202012Validator.check_schema(committed("output.schema.json"))


@pytest.mark.parametrize("args", [["list", "--json"], ["show", "git", "--json"], ["--json"]])
def test_scan_output_validates_against_the_schema(args: list[str]) -> None:
    result = run_cli(windows_with_git(), *args)

    assert result.exit_code == 0, result.output
    assert errors(output_validator(), json.loads(result.stdout)) == []


@pytest.mark.parametrize(
    ("system", "tool", "exit_code"),
    [
        (windows_with_git(), "git", 0),
        (FakeSystem(os="windows", env={"PATH": r"C:\WINDOWS\system32"}), "git", 1),
        (windows_with_git(), "nosuchtool", 2),
    ],
    ids=["captured", "not found", "unknown tool"],
)
def test_capture_output_validates_against_the_schema(
    system: FakeSystem, tool: str, exit_code: int
) -> None:
    result = run_cli(system, "debug", "capture", tool, "--out", r"C:\captures", "--json")

    assert result.exit_code == exit_code, result.output
    assert errors(output_validator(), json.loads(result.stdout)) == []


def scan_output() -> dict:
    return json.loads(run_cli(windows_with_git(), "list", "--json").stdout)


@pytest.mark.parametrize(
    "field", ["schema_version", "tools.0.notes", "tools.0.active.via", "tools.0.active.raw"]
)
def test_fields_the_cli_always_prints_are_required(field: str) -> None:
    # The UI can rely on every field being present (`via`/`raw` as explicit null,
    # `notes` as a list), so a document without one must not validate.
    document = scan_output()
    *parents, last = field.split(".")
    target = document
    for key in parents:
        target = target[int(key)] if key.isdigit() else target[key]
    del target[last]

    assert errors(output_validator(), document) != []


def test_unknown_fields_and_platforms_are_rejected() -> None:
    with_extra = scan_output()
    with_extra["tools"][0]["colour"] = "red"
    other_os = scan_output()
    other_os["platform"] = "macos"

    assert errors(output_validator(), with_extra) != []
    assert errors(output_validator(), other_os) != []


DEFINITIONS = Path(__file__).resolve().parents[1] / "src" / "versionbar" / "definitions"
SCHEMA_DIRECTIVE = "#:schema ../../../../schema/definition.schema.json"

VALID_DEFINITION = {
    "id": "git",
    "name": "Git",
    "os": ["windows", "linux"],
    "binaries": ["git"],
    "version_args": ["--version"],
    "version_regex": r"git version (?P<version>\d+\.\d+\.\d+\S*)",
    "overrides": {"windows": {"binaries": ["git.exe"]}},
}


def definition_validator() -> Validator:
    return Draft202012Validator(committed("definition.schema.json"))


def without(key: str) -> dict:
    return {k: v for k, v in VALID_DEFINITION.items() if k != key}


def changed(**changes: object) -> dict:
    return {**VALID_DEFINITION, **changes}


def test_definition_schema_is_a_valid_draft_2020_12_schema() -> None:
    Draft202012Validator.check_schema(committed("definition.schema.json"))


def test_every_built_in_definition_validates_against_the_definition_schema() -> None:
    files = sorted(DEFINITIONS.glob("*.toml"))

    assert files
    for file in files:
        text = file.read_text("utf-8")
        assert errors(definition_validator(), tomllib.loads(text)) == [], file.name
        # taplo (`npm run lint`) and TOML editors find the schema through this
        # directive; taplo 0.9.3 ignores `[[rule]]` include globs, so the
        # config file cannot attach it.
        assert text.splitlines()[0] == SCHEMA_DIRECTIVE, file.name


# The definition tests use ToolDefinition directly rather than the CLI: the TOML
# definition format is itself a contract (built-ins now, user config later),
# and ToolDefinition is the loader that enforces it.
def test_a_well_formed_definition_validates_and_loads() -> None:
    assert errors(definition_validator(), VALID_DEFINITION) == []
    ToolDefinition.model_validate(VALID_DEFINITION)


WITH_VIA = changed(
    via=[
        {"manager": "pyenv", "dirs": ["{PYENV_ROOT}/shims", "{HOME}/.pyenv/shims"]},
        {"manager": "corepack", "content_regex": r"corepack[\\/]dist"},
        {"manager": "volta", "dirs": ["{VOLTA_HOME}/bin"], "content_regex": "volta"},
    ],
    overrides={"windows": {"via": [{"manager": "pyenv", "dirs": ["{PYENV}/shims"]}]}},
)


def test_a_definition_with_via_rules_validates_and_loads() -> None:
    assert errors(definition_validator(), WITH_VIA) == []
    loaded = ToolDefinition.model_validate(WITH_VIA)
    assert [rule.manager for rule in loaded.via] == ["pyenv", "corepack", "volta"]
    assert [rule.manager for rule in loaded.for_os("windows").via] == ["pyenv"]


def test_a_content_regex_that_does_not_compile_is_rejected_by_the_loader() -> None:
    # Like version_regex, only the loader can compile the pattern.
    with pytest.raises(ValidationError, match="content_regex"):
        ToolDefinition.model_validate(changed(via=[{"manager": "x", "content_regex": "(unclosed"}]))


INVALID_DEFINITIONS = {
    "unknown key": changed(encoding="utf-16"),
    "misspelt key": {**without("binaries"), "binary": ["git"]},
    "missing key": without("version_regex"),
    "unknown os": changed(os=["windows", "macos"]),
    "no os": changed(os=[]),
    "no binaries": changed(binaries=[]),
    "regex without a version group": changed(version_regex=r"git version (\S+)"),
    "override for an unknown os": changed(overrides={"macos": {"binaries": ["git"]}}),
    "override of a field it may not replace": changed(overrides={"windows": {"name": "G"}}),
    "override with no binaries": changed(overrides={"windows": {"binaries": []}}),
    "override regex without a version group": changed(
        overrides={"linux": {"version_regex": r"(\S+)"}}
    ),
    "via rule without a condition": changed(via=[{"manager": "pyenv"}]),
    "via rule with no folders": changed(via=[{"manager": "pyenv", "dirs": []}]),
    "via rule without a manager": changed(via=[{"dirs": ["{PYENV}/shims"]}]),
    "via rule with an empty manager": changed(via=[{"manager": "", "dirs": ["{PYENV}"]}]),
    "via rule with an unknown key": changed(via=[{"manager": "volta", "env": "VOLTA_HOME"}]),
    "via folder at a fixed path": changed(via=[{"manager": "volta", "dirs": ["C:/volta/bin"]}]),
    "via folder not starting with a variable": changed(
        via=[{"manager": "pyenv", "dirs": ["~/{PYENV}/shims"]}]
    ),
    "via folder with an unclosed variable": changed(
        via=[{"manager": "pyenv", "dirs": ["{PYENV/shims"]}]
    ),
    "override via rule without a condition": changed(
        overrides={"windows": {"via": [{"manager": "pyenv"}]}}
    ),
}


@pytest.mark.parametrize("definition", INVALID_DEFINITIONS.values(), ids=INVALID_DEFINITIONS)
def test_malformed_definitions_are_rejected_by_schema_and_loader(definition: dict) -> None:
    # The schema (what taplo and editors check) and the loader (what the core
    # enforces at runtime) must agree on every rule.
    assert errors(definition_validator(), definition) != []
    with pytest.raises(ValidationError):
        ToolDefinition.model_validate(definition)
