"""The JSON contract (ADR 0005). These models are the single source of truth;
bump SCHEMA_VERSION only for breaking changes.

Docstrings on models and fields become descriptions in the generated schema
and TS types, so they are written for consumers of the JSON.
"""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from versionbar.system import OsName

SCHEMA_VERSION = 1

type ToolStatus = Literal["found", "missing", "error", "timeout"]


class StrictModel(BaseModel):
    # Output always carries every field, defaults included, so the generated
    # output schema marks them required and consumers need no fallbacks.
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_serialization_defaults_required=True,
        use_attribute_docstrings=True,
    )


class Install(StrictModel):
    """One installation of a tool."""

    version: str
    """The version as the tool prints it, vendor suffixes included."""
    path: str
    source: str
    """`path`, or the id of the provider that reported the install."""
    via: str | None = None
    """The manager whose shim serves this install, or null."""
    raw: str | None = None
    """Decoded version output the version was parsed from, or null."""


class Tool(StrictModel):
    """One tool and every install of it that was found."""

    id: str
    name: str
    status: ToolStatus
    active: Install | None
    """The install that runs when you type the command, or null when there is none."""
    installs: list[Install]
    """Every install found, the active one first."""
    notes: list[str] = []
    """Human-readable explanations for the status (why missing, what failed); not for parsing."""


class ScanResult(StrictModel):
    """The result of one live scan: what `list --json` and `show --json` print."""

    schema_version: int = SCHEMA_VERSION
    """Changes only on breaking changes to this format."""
    scanned_at: AwareDatetime
    platform: OsName
    tools: list[Tool]
