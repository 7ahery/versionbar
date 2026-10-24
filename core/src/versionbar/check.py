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

from versionbar.models import (
    CheckResult,
    RequirementOutcome,
    RequirementResult,
    ScanResult,
    Tool,
)

SPEC_HELP = """\
A requirement is a tool id (the tool must be installed) or `tool@spec` (the
tool's active install must also satisfy the version spec).

A spec is one or more clauses joined by commas, and all must hold:
`>=`, `>`, `<=`, `<` or `==`, then a version of dot-separated numbers.
Quote requirements in the shell, where `>` and `<` redirect:
`versionbar check 'node@>=20' 'python@>=3.12,<4' git`.

Only the leading dot-separated numbers of the installed version take part, and
missing trailing parts count as 0. So git's `2.55.0.windows.2` is 2.55.0,
OpenSSH's `9.5p2` is 9.5, and `==2.55` matches `2.55.0` but not `2.55.1`
(write `>=2.55,<2.56` for "any 2.55.x"). Pre-release markers are ignored, so
`3.14.0rc1` counts as 3.14.0. A version with no leading number cannot be
compared: it still satisfies a presence-only requirement but fails any spec.

Only the active install (the one that runs when you type the command) is
tested. Exit codes: 0 when every requirement passes, 1 when any fails
(including a missing, broken or hanging tool), 2 when the request itself is
malformed or names an unknown tool."""

type Operator = Literal[">=", ">", "<=", "<", "=="]
type Release = tuple[int, ...]

_CLAUSE = re.compile(r"(>=|<=|==|>|<)\s*(\d+(?:\.\d+)*)")
_RELEASE = re.compile(r"\d+(?:\.\d+)*")


class RequirementError(ValueError):
    """The requirement text is malformed; the message says how and is shown to the user."""


@dataclass(frozen=True)
class Requirement:
    text: str
    tool: str
    spec: str | None
    clauses: tuple[tuple[Operator, Release], ...]


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
        clauses.append((cast(Operator, match[1]), _release(match[2])))
    return Requirement(text, tool, spec, tuple(clauses))


def _release(version: str) -> Release:
    parts = [int(part) for part in version.split(".")]
    # Trailing zeros carry no meaning (2.55 == 2.55.0), so drop them and let
    # tuple ordering do the rest.
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def installed_release(version: str) -> Release | None:
    match = _RELEASE.match(version)
    return _release(match[0]) if match else None


def _holds(installed: Release, operator: Operator, wanted: Release) -> bool:
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
            return result("missing", f"{tool.id} is not installed: {reason}")
        outcome = "timeout" if tool.status == "timeout" else "error"
        return result(outcome, f"{tool.id} has no usable install: {reason}")

    version = tool.active.version
    if requirement.spec is None:
        return result("passed", f"{tool.id} {version} is installed")
    installed = installed_release(version)
    if installed is None:
        return result(
            "not-comparable",
            f"{tool.id} version '{version}' cannot be compared with {requirement.spec}",
        )
    if all(_holds(installed, op, wanted) for op, wanted in requirement.clauses):
        return result("passed", f"{tool.id} {version} satisfies {requirement.spec}")
    return result("unmet", f"{tool.id} {version} does not satisfy {requirement.spec}")
