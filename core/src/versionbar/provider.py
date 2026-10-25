"""The provider seam (ADR 0003): Python code that finds a version manager's
installs, including ones that are not on PATH. Built-ins live in
`versionbar.providers`; authoring guide: docs/providers.md.

A provider usually only says where the installs are: the engine runs each one
with its tool's own version command (definition, timeout, decoding, notes).
A manager that already knows its installs' versions without running them (the
.NET host lists its SDKs, which all run through one `dotnet.exe`) reports them
finished instead. Either way the engine merges them with the PATH installs and
keeps one provider's failure from touching anything else, so a new provider
needs no engine change: subclass `Provider` and add it to
`versionbar.providers.builtin_providers`.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from versionbar.system import OsName, System


@dataclass(frozen=True)
class ProvidedInstall:
    """An install the manager itself reported, version included: nothing is run."""

    version: str
    """The exact version, as the manager names it."""
    path: str
    """Absolute path of the install itself (an SDK's own folder, say), never a
    host executable several installs share: installs are told apart by it."""


@dataclass(frozen=True)
class Located:
    """What a provider found for one tool."""

    executables: Sequence[str] = ()
    """Absolute paths of the installs' executables, in the order to report them.
    The engine runs each one to learn its version."""
    notes: Sequence[str] = ()
    """Human-readable problems with the manager's data (an entry that should
    hold an install but does not), reported on the tool."""
    installs: Sequence[ProvidedInstall] = ()
    """Finished installs, reported as they are after `executables`."""


class Provider(ABC):
    id: ClassVar[str]
    """The `source` of the installs it reports, e.g. `nvm`. Also the `via`
    manager name that definitions use for this manager's shims, so the engine
    can tell a PATH shim and the install it serves apart from two installs."""
    name: ClassVar[str]
    """Display name, e.g. `nvm-windows`."""
    os: ClassVar[tuple[OsName, ...]]
    """The operating systems it runs on; elsewhere it is never called."""
    tools: ClassVar[tuple[str, ...]]
    """Ids of the tools it reports installs for."""

    @abstractmethod
    def locate(self, system: System, tool: str, timeout: float) -> Located:
        """Where this manager's installs of `tool` (one of `tools`) are.

        Finds the manager through its environment variables, never fixed
        paths, and only through `system`. A manager that is not there returns
        an empty `Located`. Runs on the scan's thread pool; any command it
        runs must use `timeout`. An exception becomes a note on the tool and
        loses nothing else.
        """
