"""Declarative tool definitions (ADR 0003): the data the generic engine runs on.

Built-ins are the TOML files in `versionbar/definitions/`. Per-OS overrides
replace top-level detection fields on that OS only.
"""

import re
import tomllib
from importlib.resources import files

from pydantic import BaseModel, ConfigDict, field_validator

from versionbar.system import OsName


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_regex(pattern: str | None) -> str | None:
    if pattern is not None and "version" not in re.compile(pattern).groupindex:
        raise ValueError("version_regex needs a named group `(?P<version>...)`")
    return pattern


class Detection(_Strict):
    """The fields an OS override may replace."""

    binaries: list[str] | None = None
    version_args: list[str] | None = None
    version_regex: str | None = None

    _regex = field_validator("version_regex")(_check_regex)


class ToolDefinition(_Strict):
    id: str
    name: str
    os: list[OsName]
    binaries: list[str]
    version_args: list[str]
    version_regex: str
    overrides: dict[OsName, Detection] = {}

    _regex = field_validator("version_regex")(_check_regex)

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
