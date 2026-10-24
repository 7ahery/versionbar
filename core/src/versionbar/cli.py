import io
import json
import sys
from typing import Annotated

import typer

from versionbar import PROG, __version__
from versionbar.capture import DEFAULT_OUT_DIR, CaptureError, CaptureFailure, capture_tool
from versionbar.check import (
    SPEC_HELP,
    Requirement,
    RequirementError,
    evaluate,
    parse_requirement,
)
from versionbar.config import InvalidConfig, Registry, Settings, load_settings
from versionbar.contract import output_schema
from versionbar.definition import ToolDefinition, builtin_definitions
from versionbar.models import ConfigResult, ScanResult
from versionbar.scan import scan
from versionbar.system import System

# Rich must stay out of this module: `--json` runs must never import it, so the
# human renderer is imported only on the human path.

app = typer.Typer(
    name=PROG,
    help="Inventory the dev tools installed on this machine. With no command, runs `list`.",
    add_completion=False,
    rich_markup_mode=None,
)

_JSON_HELP = "Print the result as JSON (stable, versioned; no colour or decoration)."


def _system(ctx: typer.Context) -> System:
    # Tests inject a fake through the Click context object; real runs get the
    # local machine. Imported lazily so nothing touches the machine at import.
    if ctx.obj is None:
        from versionbar.system.real import local_system

        return local_system()
    return ctx.obj


def _show_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help=_JSON_HELP),
    _version: bool = typer.Option(
        False, "--version", callback=_show_version, is_eager=True, help="Show the version and exit."
    ),
) -> None:
    if ctx.invoked_subcommand is None:
        _list(ctx, json_output)


@app.command("list")
def list_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help=_JSON_HELP),
) -> None:
    """Scan the machine live and show every known tool's active version and path."""
    _list(ctx, json_output)


@app.command("show")
def show_command(
    ctx: typer.Context,
    tools: Annotated[
        list[str],
        typer.Argument(metavar="TOOL...", help="Tool ids, such as git, node, python or uv."),
    ],
    json_output: bool = typer.Option(False, "--json", help=_JSON_HELP),
) -> None:
    """Show every install of the given tools found on PATH.

    The active install (the one that runs when you type the command) comes
    first; the rest are other installs it shadows.
    """
    system = _system(ctx)
    settings = _settings(system)
    _emit(
        system,
        scan(
            system,
            _requested_definitions(system, settings.registry, tools),
            settings.timeout_for,
        ),
        json_output,
        show=True,
    )


def _usage_error(lines: list[str]) -> typer.Exit:
    # Usage-error exit code, plain stderr: Click's own error box would pull
    # Rich into a `--json` run.
    typer.echo("\n".join(lines), err=True)
    return typer.Exit(2)


# Distinct from usage errors (2) and check failures (1), so a caller (the app
# included) can tell "fix your config file" apart without parsing text.
INVALID_CONFIG_EXIT_CODE = 3


def _read_settings(system: System) -> Settings | InvalidConfig:
    """The config in effect, or why the file cannot be used. The one place the CLI reads it."""
    try:
        return load_settings(system, builtin_definitions())
    except InvalidConfig as error:
        return error


def _settings(system: System) -> Settings:
    """The config in effect, or exit with the invalid-config code."""
    settings = _read_settings(system)
    if isinstance(settings, InvalidConfig):
        # Plain stderr, as with usage errors, so `--json` never prints half a document.
        typer.echo(settings.describe(), err=True)
        raise typer.Exit(INVALID_CONFIG_EXIT_CODE)
    return settings


def _requested_definitions(
    system: System, registry: Registry, names: list[str]
) -> list[ToolDefinition]:
    """Definitions for tool ids given on the command line, in request order, each once.

    Exits with the usage-error code on ids that are unknown or belong to another OS.
    """
    known = registry.known_on(system.os)
    wanted = list(dict.fromkeys(names))
    problems = [
        registry.unknown_tool_problem(system.os, name) for name in wanted if name not in known
    ]
    if problems:
        raise _usage_error([*problems, f"known tools: {', '.join(known)}"])
    return [known[name] for name in wanted]


@app.command(
    "check",
    help="Test requirements against the active install of each tool.\n\n" + SPEC_HELP,
)
def check_command(
    ctx: typer.Context,
    requirements: Annotated[
        list[str] | None,
        typer.Argument(metavar="TOOL[@SPEC]...", help="Requirements; quote any containing > or <."),
    ] = None,
    json_output: bool = typer.Option(False, "--json", help=_JSON_HELP),
) -> None:
    system = _system(ctx)
    settings = _settings(system)
    registry = settings.registry
    known = registry.known_on(system.os)
    parsed: list[Requirement] = []
    problems: list[str] = []
    for text in requirements or []:
        try:
            requirement = parse_requirement(text)
        except RequirementError as error:
            problems.append(str(error))
            continue
        if requirement.tool not in known:
            problems.append(f"{text}: {registry.unknown_tool_problem(system.os, requirement.tool)}")
        parsed.append(requirement)
    if not requirements:
        problems.append("check needs at least one requirement, e.g. check 'node@>=20' git")
    if problems:
        hint = f"see `{PROG} check --help` for the syntax"
        raise _usage_error([*problems, hint, f"known tools: {', '.join(known)}"])

    wanted = [known[tool] for tool in dict.fromkeys(r.tool for r in parsed)]
    result = evaluate(parsed, scan(system, wanted, settings.timeout_for))
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
        from versionbar.human import print_check

        terminal, color = _output_style(system)
        print_check(result, terminal=terminal, color=color)
    if not result.passed:
        raise typer.Exit(1)


def _list(ctx: typer.Context, json_output: bool) -> None:
    system = _system(ctx)
    settings = _settings(system)
    _emit(
        system,
        scan(system, settings.listed(system.os), settings.timeout_for),
        json_output,
        show=False,
    )


def _emit(system: System, result: ScanResult, json_output: bool, *, show: bool) -> None:
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
        _print_human(system, result, show=show)


def _output_style(system: System) -> tuple[bool, bool]:
    """(terminal, color), decided from the system seam and stdout rather than by
    Rich reading the process environment on its own."""

    def is_set(name: str) -> bool:
        return system.getenv(name) not in (None, "")

    terminal = sys.stdout.isatty()
    return terminal, (terminal or is_set("FORCE_COLOR")) and not is_set("NO_COLOR")


def _print_human(system: System, result: ScanResult, *, show: bool) -> None:
    from versionbar.human import print_list, print_show

    terminal, color = _output_style(system)
    (print_show if show else print_list)(result, terminal=terminal, color=color)


@app.command("config")
def config_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help=_JSON_HELP),
) -> None:
    """Show where the config file is and the settings it sets. Runs no tool.

    Exits with code 3 when the config file cannot be used, naming each problem.
    """
    system = _system(ctx)
    settings = _read_settings(system)
    if isinstance(settings, InvalidConfig):
        # Still a full answer: the app needs the path to open the file for fixing.
        result = ConfigResult(
            config_path=settings.path,
            config_exists=True,
            problems=settings.problems,
            preferences=None,
        )
    else:
        result = ConfigResult(
            config_path=settings.path,
            config_exists=settings.exists,
            problems=[],
            preferences=settings.preferences(),
        )
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
        from versionbar.human import print_config

        terminal, color = _output_style(system)
        valid = None if isinstance(settings, InvalidConfig) else settings
        print_config(result, valid, terminal=terminal, color=color)
    if result.problems:
        raise typer.Exit(INVALID_CONFIG_EXIT_CODE)


@app.command("schema")
def schema_command(
    json_output: bool = typer.Option(
        False, "--json", help="Accepted for consistency; the schema is always JSON."
    ),
) -> None:
    """Print the JSON Schema of every `--json` output (JSON Schema draft 2020-12)."""
    typer.echo(json.dumps(output_schema(), indent=2))


# Contributor tooling, not product surface: hidden from help so the public
# command list stays `list` (and what later tickets add).
debug_app = typer.Typer(hidden=True, help="Contributor diagnostics.", rich_markup_mode=None)
app.add_typer(debug_app, name="debug")


@debug_app.command("capture")
def debug_capture(
    ctx: typer.Context,
    tool: str = typer.Argument(help="Tool id, e.g. git."),
    out: str = typer.Option(DEFAULT_OUT_DIR, "--out", help="Folder to write the capture file to."),
    json_output: bool = typer.Option(False, "--json", help=_JSON_HELP),
) -> None:
    """Run a tool's version command and record its raw output as a replayable fixture."""
    try:
        outcome = capture_tool(_system(ctx), builtin_definitions(), tool, out)
    except CaptureError as error:
        if json_output:
            failure = CaptureFailure(outcome=error.outcome, tool=tool, message=error.message)
            typer.echo(failure.model_dump_json(indent=2))
        else:
            typer.echo(f"capture failed ({error.outcome}): {error.message}", err=True)
        # Asking for a tool this build cannot capture is a usage error (2),
        # like `show`; a capture that was attempted and failed is exit 1.
        usage_error = error.outcome in ("unknown-tool", "unsupported-os")
        raise typer.Exit(2 if usage_error else 1) from error
    if json_output:
        typer.echo(outcome.model_dump_json(indent=2))
    else:
        typer.echo(
            f"captured {outcome.tool} (exit code {outcome.exit_code}) to {outcome.destination}"
        )


def main(system: System | None = None) -> None:
    """Console-script entry point. `system` lets tests run the real entry point over a fake."""
    # Output is UTF-8 for every command. Windows otherwise encodes redirected
    # output with the ANSI code page (cp1252), which cannot represent many
    # real install paths and would crash mid-print.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    app(obj=system)
