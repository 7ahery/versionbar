"""Raw-output capture: record what a tool's version command really printed so
the same evidence can be replayed through the fake system (ADR 0004).

The capture file is the shared currency of every detector: contributors and
bug reporters attach one, tests replay one. It stores the raw bytes rather
than decoded text because decoding is itself under test (WSL prints UTF-16).
"""

import base64
import ntpath
import posixpath
import re
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import AwareDatetime, Base64Bytes, Field

from versionbar import PROG, __version__
from versionbar.config import DEFAULT_TIMEOUT_SECONDS
from versionbar.decoding import detect_encoding
from versionbar.definition import ToolDefinition
from versionbar.models import StrictModel
from versionbar.provider import Provider
from versionbar.system import OsName, System
from versionbar.system.resolve import ToolHits

CAPTURE_FORMAT = 1
DEFAULT_OUT_DIR = "versionbar-captures"


class RunnerInfo(StrictModel):
    """Where a CI capture ran; all fields come from the GitHub-hosted runner's environment."""

    image_os: str | None = None
    image_version: str | None = None
    run_url: str | None = None


class Provenance(StrictModel):
    # How the file came to exist: `versionbar debug capture`, or a note for hand-made seeds.
    method: str
    versionbar_version: str
    os_id: OsName
    os_description: str
    resolved_path: str
    # The exact argv that ran, so a reader can repeat it by hand.
    command: list[str]
    captured_at: AwareDatetime
    runner: RunnerInfo | None = None
    notes: str | None = None


class CaptureFile(StrictModel):
    format: Literal[1] = CAPTURE_FORMAT
    tool: str
    # Arguments after the executable; this is what the fake system matches on.
    args: list[str]
    exit_code: int
    # The raw bytes are authoritative: the engine decodes them itself
    # (versionbar.decoding) and never trusts the `encoding` guess below.
    stdout_b64: Base64Bytes
    stderr_b64: Base64Bytes
    # Capture-time best guess, used only for the readable *_text fields below.
    encoding: str
    # For humans reading the file or a bug report; never read back by the fake.
    stdout_text: str
    stderr_text: str
    provenance: Provenance


type FailureOutcome = Annotated[
    Literal[
        "unknown-tool",
        "unknown-source",
        "unsupported-os",
        "not-found",
        "timeout",
        "launch-error",
        "write-failed",
    ],
    Field(
        description="Why nothing was captured. More values may be added without a breaking"
        " change; handle unknown ones."
    ),
]


class CaptureError(Exception):
    """A capture that could not be recorded. `outcome` is the stable machine-readable reason."""

    def __init__(self, outcome: FailureOutcome, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.message = message


class CaptureOutcome(StrictModel):
    """What `debug capture --json` prints after writing a capture file."""

    outcome: Literal["captured"] = "captured"
    tool: str
    """The tool id that was captured."""
    destination: str
    """Path of the capture file that was written."""
    exit_code: int
    """Exit code of the captured command, the tool's version command or a provider's listing
    command (recorded even when non-zero)."""


class CaptureFailure(StrictModel):
    """What `debug capture --json` prints when nothing was recorded."""

    outcome: FailureOutcome
    tool: str
    """The tool id that was asked for."""
    message: str
    """Human-readable explanation."""


def capture_tool(
    system: System,
    definitions: list[ToolDefinition],
    tool_id: str,
    out_dir: str,
    *,
    providers: Sequence[Provider] = (),
    source: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> CaptureOutcome:
    """Capture the install a scan would make active. With `source`, the
    listing command that provider reads, or if it declares none here the first
    install it reports (its own order), wherever it is. Commands get `timeout`
    seconds."""
    matching = [d for d in definitions if d.id == tool_id]
    if not matching:
        known = ", ".join(sorted(d.id for d in definitions))
        raise CaptureError("unknown-tool", f"unknown tool {tool_id!r} (known tools: {known})")
    definition = matching[0]
    if system.os not in definition.os:
        raise CaptureError("unsupported-os", f"{tool_id} is not available on {system.os}")
    definition = definition.for_os(system.os)

    notes = None
    listing = None
    if source is None:
        # The install a scan would report as active, by the scan's own rules
        # (so a Store placeholder, which could open the Store, is never run).
        path = next(iter(ToolHits.of(system, definition.binaries).paths), None)
        if path is None:
            names = ", ".join(definition.binaries)
            raise CaptureError("not-found", f"{tool_id} not found on PATH (looked for: {names})")
        argv = [path, *definition.version_args]
    else:
        provider = _provider(system, providers, source, tool_id)
        # As in a scan, a provider's failure is reported, not a crash.
        try:
            listing = provider.listing(system, tool_id)
            if listing is not None and not listing:
                raise ValueError("the command is empty")
        except Exception as error:
            message = f"{provider.name} could not name its listing command: {error}"
            raise CaptureError("launch-error", message) from error
        if listing is not None:
            argv = list(listing)
            notes = (
                f"listing command of the {provider.name} provider (source {provider.id}),"
                f" whose output it reads {tool_id} installs from; not a version command"
            )
        else:
            try:
                located = provider.locate(system, tool_id, timeout)
            except Exception as error:
                message = f"{provider.name} could not list installs: {error}"
                raise CaptureError("launch-error", message) from error
            path = next(iter(located.executables), None)
            if path is None:
                raise CaptureError("not-found", f"{provider.name} reports no {tool_id} install")
            argv = [path, *definition.version_args]
            notes = (
                f"reported by the {provider.name} provider (source {provider.id}), not from PATH"
            )

    path = argv[0]
    # The definition's env guards its version command, as in a scan; a
    # provider's listing command is the provider's, not the definition's.
    process = system.run(argv, timeout, definition.env if listing is None else None)
    # Without an exit status there is nothing true to record, and a fixture
    # that looks like a success would mislead whoever replays it.
    if process.timed_out:
        raise CaptureError("timeout", f"{path} did not answer within {timeout:g} s")
    if process.launch_error is not None or process.exit_code is None:
        reason = process.launch_error or "no exit status"
        raise CaptureError("launch-error", f"could not run {path}: {reason}")

    encoding = _guess_encoding(process.stdout, process.stderr)
    stdout_text = process.stdout.decode(encoding, errors="replace")
    stderr_text = process.stderr.decode(encoding, errors="replace")
    record = CaptureFile(
        tool=tool_id,
        args=argv[1:],
        exit_code=process.exit_code,
        # The field validates base64 input, so hand it base64 and it holds the raw bytes.
        stdout_b64=base64.b64encode(process.stdout),
        stderr_b64=base64.b64encode(process.stderr),
        encoding=encoding,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        provenance=Provenance(
            method=f"{PROG} debug capture",
            versionbar_version=__version__,
            os_id=system.os,
            os_description=system.platform_description,
            resolved_path=_redact_profile(system, path),
            command=[_redact_profile(system, argv[0]), *argv[1:]],
            captured_at=system.now(),
            runner=_runner(system),
            notes=notes,
        ),
    )

    if listing is None:
        version = _file_version(definition, stdout_text + "\n" + stderr_text)
        name = f"{system.os}-{tool_id}-{version}.json"
    else:
        # A listing names many versions, or none, so no one version fits.
        name = f"{system.os}-{tool_id}-{source}-listing.json"
    join = ntpath.join if system.os == "windows" else posixpath.join
    destination = join(out_dir, name)
    try:
        system.write_file(destination, record.model_dump_json(indent=2).encode("utf-8") + b"\n")
    except OSError as error:
        raise CaptureError("write-failed", f"could not write {destination}: {error}") from error
    return CaptureOutcome(tool=tool_id, destination=destination, exit_code=process.exit_code)


def _provider(system: System, providers: Sequence[Provider], source: str, tool_id: str) -> Provider:
    matching = [provider for provider in providers if provider.id == source]
    if not matching:
        known = ", ".join(provider.id for provider in providers)
        raise CaptureError(
            "unknown-source", f"unknown source {source!r} (known providers: {known})"
        )
    provider = matching[0]
    if tool_id not in provider.tools:
        reports = ", ".join(provider.tools)
        message = f"provider {source} reports no {tool_id} installs (it reports: {reports})"
        raise CaptureError("unknown-source", message)
    if system.os not in provider.os:
        raise CaptureError("unsupported-os", f"provider {source} is not available on {system.os}")
    return provider


def _redact_profile(system: System, path: str) -> str:
    # Capture files end up in public issues and committed fixtures; the
    # profile folder carries the account name, which is not evidence.
    if system.os != "windows":
        return path
    profile = ntpath.normpath(system.getenv("USERPROFILE") or "").rstrip("\\")
    # Only a real folder below a drive or share root: a root such as `C:\`
    # names no account and would rewrite every path on the drive.
    _, rest = ntpath.splitdrive(profile)
    if not rest.strip("\\.") or not ntpath.isabs(profile):
        return path
    # Whole folder names only: `C:\Users\jane2` is not inside `C:\Users\jane`.
    if path.casefold().startswith(profile.casefold() + "\\"):
        return "%USERPROFILE%" + path[len(profile) :]
    return path


def _guess_encoding(*streams: bytes) -> str:
    # Only a hint for the readable text fields, so one name covers the file:
    # the first stream that is not plain UTF-8 decides.
    guesses = [detect_encoding(data) for data in streams if data]
    return next((guess for guess in guesses if guess != "utf-8"), "utf-8")


def _runner(system: System) -> RunnerInfo | None:
    image_os = system.getenv("ImageOS")
    image_version = system.getenv("ImageVersion")
    server = system.getenv("GITHUB_SERVER_URL")
    repository = system.getenv("GITHUB_REPOSITORY")
    run_id = system.getenv("GITHUB_RUN_ID")
    run_url = (
        f"{server}/{repository}/actions/runs/{run_id}" if server and repository and run_id else None
    )
    if image_os is None and image_version is None and run_url is None:
        return None
    return RunnerInfo(image_os=image_os, image_version=image_version, run_url=run_url)


def _file_version(definition: ToolDefinition, text: str) -> str:
    # Named by version so captures from different releases sit side by side as
    # fixtures; unparseable output still gets recorded, under a placeholder.
    match = re.search(definition.version_regex, text)
    if match is None:
        return "unknown-version"
    return re.sub(r"[^A-Za-z0-9._+-]", "_", match["version"])
