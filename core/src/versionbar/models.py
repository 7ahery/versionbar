"""The JSON contract (ADR 0005). These models are the single source of truth;
bump SCHEMA_VERSION only for breaking changes.

Docstrings on models and fields become descriptions in the generated schema
and TS types, so they are written for consumers of the JSON.
"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from versionbar.system import OsName

SCHEMA_VERSION = 1

# Descriptions sit on the enum types, not the fields: a field description next
# to a `$ref` makes the TS generator inline the enum instead of naming it.
type ToolStatus = Annotated[
    Literal["found", "missing", "error", "timeout"],
    Field(
        description="More values may be added without a schema_version bump; handle unknown ones."
    ),
]


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
    """Absolute path of the executable that was run."""
    source: str
    """`path`, or the id of the provider that reported the install."""
    via: str | None = None
    """The manager whose shim serves this install, or null."""
    raw: str | None = None
    """Decoded version output the version was parsed from, or null."""


class Tool(StrictModel):
    """One tool and every install of it that was found."""

    id: str
    """Stable tool id, as used on the command line (e.g. `git`)."""
    name: str
    """Display name."""
    status: ToolStatus
    active: Install | None
    """The install that runs when you type the command, or null when there is none."""
    installs: list[Install]
    """Every install found, the active one first."""
    notes: list[str] = []
    """Human-readable explanations for the status (why missing, what failed); not for parsing."""


class ScanResult(StrictModel):
    """The result of one live scan: what `list --json` and `show --json` print.

    `platform` and `status` may gain values without a schema_version bump; handle
    unknown ones (for example with a default branch).
    """

    schema_version: int = SCHEMA_VERSION
    """Changes only on breaking changes to this format."""
    scanned_at: AwareDatetime
    """When the scan ran, RFC 3339 in UTC."""
    platform: OsName
    tools: list[Tool]
    """`list`: every tool known on this OS, missing ones included, except those the user config
    hides; its pinned and ordered tools come first. `show`: the requested ones, in request order."""


# As with ToolStatus, the description sits on the enum type.
type RequirementOutcome = Annotated[
    Literal["passed", "unmet", "not-comparable", "missing", "error", "timeout"],
    Field(
        description=(
            "`passed`: met. Every other value is a failure: `unmet` (the active version is "
            "outside the range), `not-comparable` (the active version has no leading number to "
            "compare), `missing`, `error` or `timeout` (the tool has no usable active install; "
            "same meaning as the tool status). "
            "More values may be added without a schema_version bump; handle unknown ones."
        )
    ),
]


class RequirementResult(StrictModel):
    """The verdict on one requirement given to `check`."""

    requirement: str
    """The requirement exactly as given, e.g. `node@>=20`."""
    tool: str
    """Tool id the requirement is about."""
    spec: str | None
    """The version spec after `@` (e.g. `>=20,<23`), or null for a presence-only requirement."""
    passed: bool
    """True when the outcome is `passed`."""
    outcome: RequirementOutcome
    version: str | None
    """Version of the active install as the tool prints it, or null when there is none."""
    path: str | None
    """Absolute path of the active install, or null when there is none."""
    message: str
    """Human-readable explanation of the verdict; not for parsing."""


class CheckResult(StrictModel):
    """The result of `check --json`: one live scan, then every requirement tested against the
    active install of its tool. The exit code is 0 exactly when `passed` is true."""

    schema_version: int = SCHEMA_VERSION
    """Changes only on breaking changes to this format; the same counter as ScanResult's."""
    scanned_at: AwareDatetime
    """When the scan ran, RFC 3339 in UTC."""
    platform: OsName
    passed: bool
    """True when every requirement passed."""
    requirements: list[RequirementResult]
    """One entry per requirement, in the order given."""


class ConfigProblem(StrictModel):
    """One thing wrong with the user config file."""

    key: str | None
    """Where in the file, as a dotted TOML key with list indexes (e.g. `tools[0].version_regex`;
    a part that is not a bare key is quoted, e.g. `timeouts."my.tool"`), or null when the
    problem is the whole file (unreadable, not UTF-8, not valid TOML)."""
    message: str
    """Human-readable description of the problem; not for parsing."""


class Preferences(StrictModel):
    """The preferences the app needs from the config file, defaults filled in."""

    update_check: bool
    """Whether the app may check for VersionBar updates. When false it must make no update
    requests."""
    pinned: list[str]
    """Tool ids to show first, in this order. Each id appears at most once in `pinned` and
    `order` together; ids of tools that are not in a scan are allowed and are skipped."""
    order: list[str]
    """Tool ids to show after the pinned ones, in this order."""


class ConfigResult(StrictModel):
    """The result of `config --json`, the preferences query: where the user config file is
    and the preferences it sets. Read live; nothing is run.

    Exit code 0 when the config is usable (absent counts: defaults apply), 3 when it is not,
    in which case `problems` says why and `preferences` is null.
    """

    schema_version: int = SCHEMA_VERSION
    """Changes only on breaking changes to this format; the same counter as ScanResult's."""
    config_path: str
    """Absolute path of the user config file, whether or not it exists."""
    config_exists: bool
    """Whether there is a file at `config_path`. False means every default applies."""
    problems: list[ConfigProblem]
    """Everything wrong with the file; empty when it is usable."""
    preferences: Preferences | None
    """The preferences in effect, or null when the file is unusable (see `problems`)."""
