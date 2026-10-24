"""Declarative tool definitions (ADR 0003): the data the generic engine runs on.

Built-ins are the TOML files in `versionbar/definitions/`. Per-OS overrides
replace top-level detection fields on that OS only.
"""

import re
import tomllib
from importlib.resources import files
from typing import Annotated

from pydantic import AfterValidator, Field, WithJsonSchema

from versionbar.models import StrictModel
from versionbar.system import OsName


def _check_regex(pattern: str) -> str:
    if "version" not in re.compile(pattern).groupindex:
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

# A definition that names no OS or no binary can never detect anything, so it
# is a typo to reject, not a tool to report missing.
NonEmptyOs = Annotated[list[OsName], Field(min_length=1)]
NonEmptyBinaries = Annotated[list[str], Field(min_length=1)]


class Detection(StrictModel):
    """The fields an OS override may replace."""

    binaries: NonEmptyBinaries | None = None
    version_args: list[str] | None = None
    version_regex: VersionRegex | None = None


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
    overrides: dict[OsName, Detection] = {}
    """Per-OS replacements for `binaries`, `version_args` or `version_regex`."""

    def for_os(self, os: OsName) -> ToolDefinition:
        override = self.overrides.get(os)
        if override is None:
            return self
        return self.model_copy(update=override.model_dump(exclude_none=True))


def builtin_definitions() -> list[ToolDefinition]:
    folder = files("versionbar") / "definitions"
    entries = sorted(
        (entry for entry in folder.iterdir() if entry.name.endswith(".toml")),
        key=lambda entry: entry.name,
    )
    return [
        ToolDefinition.model_validate(tomllib.loads(entry.read_text("utf-8"))) for entry in entries
    ]
