"""`check`: test requirements such as `node@>=20,<23` against a scan.

Version comparison is deliberately small and in-house instead of PEP 440 or
semver: the versions tools print are neither (git prints `2.55.0.windows.2`,
OpenSSH `9.5p2`), and a library would reject or reorder them in ways a user
cannot predict. The rules are written down in `SPEC_HELP` and tested through
the CLI.
"""

import re
from dataclasses import dataclass
from typing import Literal, cast

from versionbar import PROG
from versionbar.models import (
    SCHEMA_VERSION,
    CheckResult,
    RequirementOutcome,
    RequirementResult,
    ScanResult,
    Tool,
)

SPEC_HELP = f"""\
A requirement is a tool id (the tool must be installed) or `tool@spec` (the
tool's active install must also satisfy the version spec).

A spec is one or more clauses joined by commas, and all must hold:
`>=`, `>`, `<=`, `<` or `==`, then a version of dot-separated numbers.
Quote requirements in the shell, where `>` and `<` redirect:
`{PROG} check 'node@>=20' 'python@>=3.12,<4' git`.

Only the leading dot-separated numbers of the installed version take part, and
missing trailing parts count as 0. So git's `2.55.0.windows.2` is 2.55.0,
OpenSSH's `9.5p2` is 9.5, and `==2.55` matches `2.55.0` but not `2.55.1`
(write `>=2.55,<2.56` for "any 2.55.x"). A pre-release marker straight after
the numbers (`a`, `alpha`, `b`, `beta`, `c`, `rc`, `pre`, `preview`, `dev`,
any case, optionally after `-` or `.` and followed by digits) ranks just below
that release: `3.14.0rc1` fails `>=3.14` but passes `>=3.13` and `<3.14`.
Two pre-releases of the same numbers compare equal. Any other suffix is
ignored. A version with no leading number cannot be
compared: it still satisfies a presence-only requirement but fails any spec.

Only the active install (the one that runs when you type the command) is
tested. Exit codes: 0 when every requirement passes, 1 when any fails
(including a missing, broken or hanging tool), 2 when the request itself is
malformed or names an unknown tool."""

type Operator = Literal[">=", ">", "<=", "<", "=="]
type Release = tuple[int, ...]
# (release, 0 for a pre-release or 1 for a final release).
type Key = tuple[Release, int]

_CLAUSE = re.compile(r"(>=|<=|==|>|<)\s*(\d+(?:\.\d+)*)")
_RELEASE = re.compile(r"\d+(?:\.\d+)*")
# Directly after the numbers: 3.14.0rc1, 3.15.0a2, 1.0.0-beta.1. The lookahead
# keeps words that merely start with a marker (`1.0.0abc`) from counting.
_PRERELEASE = re.compile(r"[-.]?(?:alpha|beta|preview|pre|dev|rc|a|b|c)\d*(?![a-z])", re.IGNORECASE)


class RequirementError(ValueError):
    """The requirement text is malformed; the message says how and is shown to the user."""


@dataclass(frozen=True)
class Requirement:
    text: str
    tool: str
    spec: str | None
    clauses: tuple[tuple[Operator, Key], ...]


def parse_requirement(text: str) -> Requirement:
    tool, at, spec = text.partition("@")
    if not tool:
        raise RequirementError(f"{text}: missing the tool id before '@'")
    if not at:
        return Requirement(text, tool, None, ())
    spec = spec.strip()
    if not spec:
        raise RequirementError(f"{text}: nothing after '@'; write e.g. {tool}@>=1.2")
    clauses = []
    for part in spec.split(","):
        part = part.strip()
        match = _CLAUSE.fullmatch(part)
        if match is None:
            if _RELEASE.fullmatch(part):
                reason = f"'{part}' needs an operator (>=, >, <=, <, ==)"
            else:
                reason = f"'{part}' is not an operator (>=, >, <=, <, ==) and a dotted number"
            raise RequirementError(f"{text}: {reason}")
        # The pattern admits exactly the Operator values.
        clauses.append((cast(Operator, match[1]), (_release(match[2]), 1)))
    return Requirement(text, tool, spec, tuple(clauses))


def _release(version: str) -> Release:
    parts = [int(part) for part in version.split(".")]
    # Trailing zeros carry no meaning (2.55 == 2.55.0), so drop them and let
    # tuple ordering do the rest.
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def installed_key(version: str) -> Key | None:
    match = _RELEASE.match(version)
    if match is None:
        return None
    # Tuples order the release first; a pre-release (0) then sorts below the
    # final release (1) of the same numbers, so 3.14.0rc1 is below 3.14.
    final = 0 if _PRERELEASE.match(version, match.end()) else 1
    return _release(match[0]), final


def _holds(installed: Key, operator: Operator, wanted: Key) -> bool:
    match operator:
        case ">=":
            return installed >= wanted
        case ">":
            return installed > wanted
        case "<=":
            return installed <= wanted
        case "<":
            return installed < wanted
        case "==":
            return installed == wanted


def evaluate(requirements: list[Requirement], scan: ScanResult) -> CheckResult:
    tools = {tool.id: tool for tool in scan.tools}
    results = [_evaluate_one(requirement, tools[requirement.tool]) for requirement in requirements]
    return CheckResult(
        schema_version=SCHEMA_VERSION,
        scanned_at=scan.scanned_at,
        platform=scan.platform,
        passed=all(result.passed for result in results),
        requirements=results,
    )


def _evaluate_one(requirement: Requirement, tool: Tool) -> RequirementResult:
    def result(outcome: RequirementOutcome, message: str) -> RequirementResult:
        active = tool.active
        return RequirementResult(
            requirement=requirement.text,
            tool=requirement.tool,
            spec=requirement.spec,
            passed=outcome == "passed",
            outcome=outcome,
            version=active.version if active else None,
            path=active.path if active else None,
            message=message,
        )

    # The scan's own first note already says why (not on PATH, Store
    # placeholder, exit code and output, timeout), so it is not paraphrased.
    reason = tool.notes[0] if tool.notes else tool.status
    if tool.active is None:
        if tool.status == "missing":
            if tool.installs:
                # A version manager holds installs, but nothing runs when the
                # command is typed; "not installed" would be wrong.
                count = len(tool.installs)
                noun = "install" if count == 1 else "installs"
                return result(
                    "missing",
                    f"{tool.id} is not active: {reason} ({count} {noun} found off PATH)",
                )
            return result("missing", f"{tool.id} is not installed: {reason}")
        outcome = "timeout" if tool.status == "timeout" else "error"
        return result(outcome, f"{tool.id} has no usable install: {reason}")

    version = tool.active.version
    if requirement.spec is None:
        return result("passed", f"{tool.id} {version} is installed")
    installed = installed_key(version)
    if installed is None:
        return result(
            "not-comparable",
            f"{tool.id} version '{version}' cannot be compared with {requirement.spec}",
        )
    if all(_holds(installed, op, wanted) for op, wanted in requirement.clauses):
        return result("passed", f"{tool.id} {version} satisfies {requirement.spec}")
    return result("unmet", f"{tool.id} {version} does not satisfy {requirement.spec}")
