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
from typing import Literal

from pydantic import AwareDatetime, Base64Bytes

from versionbar import __version__
from versionbar.decoding import detect_encoding
from versionbar.definition import ToolDefinition
from versionbar.models import StrictModel
from versionbar.scan import DEFAULT_TIMEOUT_SECONDS
from versionbar.system import OsName, System
from versionbar.system.resolve import path_hits

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


type FailureOutcome = Literal[
    "unknown-tool", "unsupported-os", "not-found", "timeout", "launch-error", "write-failed"
]


class CaptureError(Exception):
    """A capture that could not be recorded. `outcome` is the stable machine-readable reason."""

    def __init__(self, outcome: FailureOutcome, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.message = message


class CaptureOutcome(StrictModel):
    outcome: Literal["captured"] = "captured"
    tool: str
    destination: str
    exit_code: int


class CaptureFailure(StrictModel):
    """What `debug capture --json` prints when nothing was recorded."""

    outcome: FailureOutcome
    tool: str
    message: str


def capture_tool(
    system: System, definitions: list[ToolDefinition], tool_id: str, out_dir: str
) -> CaptureOutcome:
    matching = [d for d in definitions if d.id == tool_id]
    if not matching:
        known = ", ".join(sorted(d.id for d in definitions))
        raise CaptureError("unknown-tool", f"unknown tool {tool_id!r} (known tools: {known})")
    definition = matching[0]
    if system.os not in definition.os:
        raise CaptureError("unsupported-os", f"{tool_id} is not available on {system.os}")
    definition = definition.for_os(system.os)

    path = next((hit for binary in definition.binaries for hit in path_hits(system, binary)), None)
    if path is None:
        names = ", ".join(definition.binaries)
        raise CaptureError("not-found", f"{tool_id} not found on PATH (looked for: {names})")

    argv = [path, *definition.version_args]
    process = system.run(argv, DEFAULT_TIMEOUT_SECONDS)
    # Without an exit status there is nothing true to record, and a fixture
    # that looks like a success would mislead whoever replays it.
    if process.timed_out:
        raise CaptureError("timeout", f"{path} did not answer within {DEFAULT_TIMEOUT_SECONDS:g} s")
    if process.launch_error is not None or process.exit_code is None:
        reason = process.launch_error or "no exit status"
        raise CaptureError("launch-error", f"could not run {path}: {reason}")

    encoding = _guess_encoding(process.stdout, process.stderr)
    stdout_text = process.stdout.decode(encoding, errors="replace")
    stderr_text = process.stderr.decode(encoding, errors="replace")
    record = CaptureFile(
        tool=tool_id,
        args=definition.version_args,
        exit_code=process.exit_code,
        # The field validates base64 input, so hand it base64 and it holds the raw bytes.
        stdout_b64=base64.b64encode(process.stdout),
        stderr_b64=base64.b64encode(process.stderr),
        encoding=encoding,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        provenance=Provenance(
            method="versionbar debug capture",
            versionbar_version=__version__,
            os_id=system.os,
            os_description=system.platform_description,
            resolved_path=path,
            command=argv,
            captured_at=system.now(),
            runner=_runner(system),
        ),
    )

    version = _file_version(definition, stdout_text + "\n" + stderr_text)
    join = ntpath.join if system.os == "windows" else posixpath.join
    destination = join(out_dir, f"{system.os}-{tool_id}-{version}.json")
    try:
        system.write_file(destination, record.model_dump_json(indent=2).encode("utf-8") + b"\n")
    except OSError as error:
        raise CaptureError("write-failed", f"could not write {destination}: {error}") from error
    return CaptureOutcome(tool=tool_id, destination=destination, exit_code=process.exit_code)


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
