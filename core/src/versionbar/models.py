"""The JSON contract (ADR 0005). These models are the single source of truth;
bump SCHEMA_VERSION only for breaking changes."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from versionbar.system import OsName

SCHEMA_VERSION = 1

type ToolStatus = Literal["found", "missing", "error", "timeout"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Install(_Model):
    version: str
    path: str
    # `path`, or the id of the Provider that reported the install.
    source: str
    via: str | None = None
    # Decoded version output, kept so consumers can see what the version was parsed from.
    raw: str | None = None


class Tool(_Model):
    id: str
    name: str
    status: ToolStatus
    active: Install | None
    # Every install found, the active one included.
    installs: list[Install]
    # Human-readable explanations for a status (why missing, what failed).
    notes: list[str] = []


class ScanResult(_Model):
    schema_version: int = SCHEMA_VERSION
    scanned_at: AwareDatetime
    platform: OsName
    tools: list[Tool]
