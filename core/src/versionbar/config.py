"""The user config file: one TOML file in the platform's config folder, shared by
the CLI and the app. Read live on every invocation that needs it (the core never
caches); absence means defaults. Format: docs/config.md.
"""

import ntpath
import posixpath
import tomllib
from dataclasses import dataclass
from typing import Annotated

from pydantic import Field, ValidationError
from pydantic_core import ErrorDetails

from versionbar.definition import ToolDefinition
from versionbar.models import ConfigProblem, Preferences, StrictModel
from versionbar.scan import DEFAULT_TIMEOUT_SECONDS
from versionbar.system import OsName, System

CONFIG_FILE_NAME = "config.toml"


# Finite and positive: TOML allows `inf` and `nan`, which would make a hung
# tool stall the scan forever or time out every tool at once.
type Seconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class _ConfigModel(StrictModel):
    # Strict: TOML already has real booleans and numbers, so `update_check = 1`
    # or `timeout = "5"` is a mistake to report, not a value to coerce.
    model_config = StrictModel.model_config | {"strict": True}


class AppSettings(_ConfigModel):
    """Settings only the tray app uses; the CLI ignores them."""

    update_check: bool = True
    """Whether the app checks for VersionBar updates. False means it never asks."""


class ConfigFile(_ConfigModel):
    """The config file's content. Every key is optional."""

    timeout: Seconds = DEFAULT_TIMEOUT_SECONDS
    """Seconds each version command may run before its tool is reported as `timeout`."""
    timeouts: dict[str, Seconds] = {}
    """Per-tool timeouts by tool id; each wins over `timeout` for its tool."""

    pinned: list[str] = []
    """Tool ids listed first, in this order."""
    order: list[str] = []
    """Tool ids listed after the pinned ones, in this order. The rest follow in default order."""
    hidden: list[str] = []
    """Tool ids left out of `list`. `show` and `check` still find them when asked for by id."""
    tools: list[ToolDefinition] = []
    """Custom tool definitions, in the same format as the built-in ones."""
    app: AppSettings = AppSettings()


@dataclass(frozen=True)
class Registry:
    """Every tool definition known to this invocation, on every OS: the built-ins
    in their order, then the config's custom tools in file order.

    A custom tool with a built-in's id replaces that built-in in its place, so a
    built-in added in a later release never breaks a config that already
    defined a tool by that id.
    """

    definitions: tuple[ToolDefinition, ...]
    custom_ids: frozenset[str] = frozenset()
    """Ids whose definition comes from the config file."""

    @classmethod
    def of(cls, builtins: list[ToolDefinition], custom: list[ToolDefinition]) -> Registry:
        by_id = {definition.id: definition for definition in builtins}
        # Assigning an existing key keeps its position: replacement in place.
        by_id.update((definition.id, definition) for definition in custom)
        return cls(tuple(by_id.values()), frozenset(definition.id for definition in custom))

    def on(self, os: OsName) -> list[ToolDefinition]:
        return [definition for definition in self.definitions if os in definition.os]


@dataclass(frozen=True)
class Settings:
    """The config in effect for one invocation."""

    path: str
    exists: bool
    file: ConfigFile
    registry: Registry

    def preferences(self) -> Preferences:
        app, file = self.file.app, self.file
        return Preferences(update_check=app.update_check, pinned=file.pinned, order=file.order)

    def timeout_for(self, tool_id: str) -> float:
        return self.file.timeouts.get(tool_id, self.file.timeout)

    def listed(self, os: OsName) -> list[ToolDefinition]:
        """What `list` scans on `os`: every known tool except the hidden ones, pinned
        ones first, then ordered ones, then the rest in registry order."""
        hidden = set(self.file.hidden)
        rank = {id: index for index, id in enumerate([*self.file.pinned, *self.file.order])}
        shown = [definition for definition in self.registry.on(os) if definition.id not in hidden]
        # sorted() is stable, so unranked tools keep their registry order.
        return sorted(shown, key=lambda definition: rank.get(definition.id, len(rank)))


def config_path(system: System) -> str:
    paths = ntpath if system.os == "windows" else posixpath
    return paths.join(system.config_dir, CONFIG_FILE_NAME)


class InvalidConfig(Exception):
    """The config file exists but cannot be used. Every problem found is listed."""

    def __init__(self, path: str, problems: list[ConfigProblem]) -> None:
        super().__init__(path)
        self.path = path
        self.problems = problems

    def describe(self) -> str:
        lines = [f"invalid config file {self.path}"]
        lines += [
            f"  {problem.key}: {problem.message}" if problem.key else f"  {problem.message}"
            for problem in self.problems
        ]
        return "\n".join(lines)


def load_settings(system: System, builtins: list[ToolDefinition]) -> Settings:
    """The config in effect, read from the machine now.

    Raises InvalidConfig when the file exists but is unreadable or invalid.
    """
    path = config_path(system)
    try:
        data = system.read_file(path)
    except FileNotFoundError:
        return Settings(path, False, ConfigFile(), Registry.of(builtins, []))
    except OSError as error:
        raise _whole_file(path, f"cannot read it: {error}") from error
    file = _parse(path, data)
    registry = Registry.of(builtins, file.tools)
    problems = _id_problems(file, {definition.id for definition in registry.definitions})
    if problems:
        raise InvalidConfig(path, problems)
    return Settings(path, True, file, registry)


def _id_problems(file: ConfigFile, known: set[str]) -> list[ConfigProblem]:
    """Tool ids the file refers to must exist (on some OS: one config can serve
    several machines) and appear in at most one of pinned, order and hidden."""
    problems: list[ConfigProblem] = []
    seen_custom: set[str] = set()
    for index, definition in enumerate(file.tools):
        if definition.id in seen_custom:
            message = f'"{definition.id}" is already a custom tool'
            problems.append(ConfigProblem(key=f"tools[{index}].id", message=message))
        seen_custom.add(definition.id)

    for id in file.timeouts:
        if id not in known:
            problems.append(ConfigProblem(key=f"timeouts.{id}", message=f'unknown tool "{id}"'))

    placed: dict[str, str] = {}
    for name in ("pinned", "order", "hidden"):
        for index, id in enumerate(getattr(file, name)):
            key = f"{name}[{index}]"
            if id not in known:
                problems.append(ConfigProblem(key=key, message=f'unknown tool "{id}"'))
            elif id in placed:
                where = "listed" if placed[id] == name else f"in {placed[id]}"
                problems.append(ConfigProblem(key=key, message=f'"{id}" is already {where}'))
            else:
                placed[id] = name
    return problems


def _whole_file(path: str, message: str) -> InvalidConfig:
    return InvalidConfig(path, [ConfigProblem(key=None, message=message)])


def _parse(path: str, data: bytes) -> ConfigFile:
    try:
        # A BOM is tolerated: older Notepad versions write one.
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise _whole_file(path, f"not UTF-8: {error}") from error
    try:
        return ConfigFile.model_validate(tomllib.loads(text))
    except tomllib.TOMLDecodeError as error:
        raise _whole_file(path, f"not valid TOML: {error}") from error
    except ValidationError as error:
        raise InvalidConfig(path, [_problem(detail) for detail in error.errors()]) from None


# Pydantic's wording for the commonest mistakes, in config-file terms.
_MESSAGES = {"extra_forbidden": "unknown key", "missing": "missing required key"}


def _problem(detail: ErrorDetails) -> ConfigProblem:
    key = ""
    for part in detail["loc"]:
        key += f"[{part}]" if isinstance(part, int) else f".{part}" if key else str(part)
    message = _MESSAGES.get(detail["type"]) or detail["msg"].removeprefix("Value error, ")
    return ConfigProblem(key=key or None, message=message)
