"""Which manager's shim serves an install (`via`), decided from definition rules.

Written against `System` primitives, like executable resolution, so the rules
run under the fake in tests and Windows path rules apply on Linux CI too.
"""

import ntpath
import posixpath
import re

from versionbar.definition import CONTENT_LIMIT_BYTES, ViaRule
from versionbar.system import System

_VARIABLE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def via_for(system: System, rules: list[ViaRule], path: str) -> str | None:
    """The manager named by the first rule that matches the install at `path`."""
    paths = ntpath if system.os == "windows" else posixpath
    folder = paths.normcase(paths.dirname(path))
    # Read at most once, and only if a rule gets as far as needing it.
    head: bytes | None = None
    for rule in rules:
        if rule.dirs is not None:
            folders = {paths.normcase(f) for f in _expand(system, rule.dirs)}
            if folder not in folders:
                continue
        if rule.content_regex is not None:
            if head is None:
                head = system.read_file_head(path, CONTENT_LIMIT_BYTES) or b""
            # Shim markers are ASCII path fragments; replacement keeps a binary
            # or oddly encoded file from failing the scan.
            if re.search(rule.content_regex, head.decode("utf-8", errors="replace")) is None:
                continue
        return rule.manager
    return None


def _expand(system: System, templates: list[str]) -> list[str]:
    paths = ntpath if system.os == "windows" else posixpath
    folders = []
    for template in templates:
        missing = False

        def value(match: re.Match[str]) -> str:
            nonlocal missing
            # Quotes and spaces are how such values commonly arrive from setup
            # scripts; PATH entries are cleaned the same way.
            found = (system.getenv(match[1]) or "").strip().strip('"')
            missing = missing or not found
            return found

        expanded = _VARIABLE.sub(value, template)
        # An unset manager variable means that manager is not installed (or not
        # where it says), so the folder names nothing; a relative one would be
        # relative to a cwd the scan does not have.
        if not missing and paths.isabs(expanded):
            folders.append(paths.normpath(expanded))
    return folders
