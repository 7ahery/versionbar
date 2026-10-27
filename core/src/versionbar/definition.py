"""Declarative tool definitions (ADR 0003): the data the generic engine runs on.

Built-ins are the TOML files in `versionbar/definitions/`. Per-OS overrides
replace top-level detection fields on that OS only.
"""

import re
import tomllib
from importlib.resources import files
from typing import Annotated

from pydantic import AfterValidator, Field, WithJsonSchema, model_validator

from versionbar.models import StrictModel
from versionbar.system import OsName


def _check_regex(pattern: str) -> str:
    if "version" not in re.compile(_check_compiles(pattern)).groupindex:
        raise ValueError("version_regex needs a named group `(?P<version>...)`")
    return pattern


# The schema can only look for the group's syntax; the loader compiles the
# pattern and checks the group really exists.
type VersionRegex = Annotated[
    str,
    AfterValidator(_check_regex),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": r"\(\?P<version>",
            "description": "Python regex with a named group `(?P<version>...)`.",
        }
    ),
]

# `{NAME}` is replaced by environment variable NAME. A folder must start with
# one, because managers are found through their environment variables, never
# at fixed paths (a manager installed somewhere unusual is still recognised).
_FOLDER_TEMPLATE = r"^\{[A-Za-z_][A-Za-z0-9_]*\}([^{}]|\{[A-Za-z_][A-Za-z0-9_]*\})*$"
type FolderTemplate = Annotated[
    str,
    Field(
        pattern=_FOLDER_TEMPLATE,
        description="A folder starting with `{NAME}`, an environment variable, e.g."
        " `{PYENV_ROOT}/shims`. Use `/`; it becomes `\\` on Windows.",
    ),
]


def _check_compiles(pattern: str) -> str:
    # re.error is not a ValueError, so pydantic would let it escape the loader
    # as a crash instead of a validation error naming the field.
    try:
        re.compile(pattern)
    except re.error as error:
        raise ValueError(f"not a valid regex: {error}") from error
    return pattern


# How much of a file `content_regex` sees. Generated shim scripts are a few
# hundred bytes; the cap keeps a rule from reading whole executables.
CONTENT_LIMIT_BYTES = 16 * 1024


class ViaRule(StrictModel):
    """Recognises installs served by a manager's shim. Every condition given must match."""

    # A rule with no condition would tag every install, which is never meant.
    model_config = StrictModel.model_config | {
        "json_schema_extra": {"anyOf": [{"required": ["dirs"]}, {"required": ["content_regex"]}]}
    }

    manager: Annotated[str, Field(min_length=1)]
    """Reported as the install's `via`, e.g. `pyenv`."""
    dirs: Annotated[list[FolderTemplate], Field(min_length=1)] | None = None
    """The install's folder is one of these. A folder naming an unset or empty
    variable, or not absolute once expanded, is ignored."""
    content_regex: Annotated[str, Field(min_length=1), AfterValidator(_check_compiles)] | None = (
        None
    )
    """Python regex searched for in the first 16 KiB of the install's file
    (decoded as UTF-8), for shims recognisable only by what their manager wrote
    into them. The file is read, never run."""

    @model_validator(mode="after")
    def _has_a_condition(self) -> ViaRule:
        if self.dirs is None and self.content_regex is None:
            raise ValueError("a via rule needs `dirs`, `content_regex` or both")
        return self


type EnvName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]

# A definition that names no OS or no binary can never detect anything, so it
# is a typo to reject, not a tool to report missing.
NonEmptyOs = Annotated[list[OsName], Field(min_length=1)]
NonEmptyBinaries = Annotated[list[str], Field(min_length=1)]


class Detection(StrictModel):
    """The fields an OS override may replace."""

    binaries: NonEmptyBinaries | None = None
    version_args: list[str] | None = None
    version_regex: VersionRegex | None = None
    via: list[ViaRule] | None = None


class ToolDefinition(StrictModel):
    """A declarative tool definition: one TOML file, detected by the generic engine."""

    id: str
    """Stable id used on the command line and in the JSON, e.g. `git`."""
    name: str
    """Display name."""
    os: NonEmptyOs
    """The operating systems the tool is detected on."""
    binaries: NonEmptyBinaries
    """Command names to look up on PATH, in order; PATHEXT applies on Windows."""
    version_args: list[str]
    """Arguments that make the tool print its version."""
    version_regex: VersionRegex
    via: list[ViaRule] = []
    """Shim rules, tried in order; the first that matches an install names its `via`."""
    env: dict[EnvName, str] = {}
    """Environment variables set for this tool's version command only, laid over
    VersionBar's own, e.g. to stop the tool installing something when probed."""
    overrides: dict[OsName, Detection] = {}
    """Per-OS replacements for `binaries`, `version_args`, `version_regex` or `via`."""

    def for_os(self, os: OsName) -> ToolDefinition:
        override = self.overrides.get(os)
        if override is None:
            return self
        # Attributes, not model_dump(): the copy is not re-validated, so nested
        # rules must stay models rather than become dicts.
        replaced = {
            name: value
            for name in Detection.model_fields
            if (value := getattr(override, name)) is not None
        }
        return self.model_copy(update=replaced)


def builtin_definitions() -> list[ToolDefinition]:
    folder = files("versionbar") / "definitions"
    entries = sorted(
        (entry for entry in folder.iterdir() if entry.name.endswith(".toml")),
        key=lambda entry: entry.name,
    )
    return [
        ToolDefinition.model_validate(tomllib.loads(entry.read_text("utf-8"))) for entry in entries
    ]
