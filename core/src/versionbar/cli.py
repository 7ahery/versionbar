import io
import sys

import typer

from versionbar import __version__
from versionbar.definition import builtin_definitions
from versionbar.models import ScanResult
from versionbar.scan import scan
from versionbar.system import System

# Rich must stay out of this module: `--json` runs must never import it, so the
# human renderer is imported only on the human path.

app = typer.Typer(
    name="versionbar",
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


def _list(ctx: typer.Context, json_output: bool) -> None:
    system = _system(ctx)
    result = scan(system, builtin_definitions())
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
        _print_human(system, result)


def _print_human(system: System, result: ScanResult) -> None:
    from versionbar.human import print_list

    # Styling and width are decided here, from the system seam and stdout,
    # rather than by Rich reading the process environment on its own.
    def is_set(name: str) -> bool:
        return system.getenv(name) not in (None, "")

    terminal = sys.stdout.isatty()
    color = (terminal or is_set("FORCE_COLOR")) and not is_set("NO_COLOR")
    print_list(result, terminal=terminal, color=color)


def main(system: System | None = None) -> None:
    """Console-script entry point. `system` lets tests run the real entry point over a fake."""
    # Output is UTF-8 for every command. Windows otherwise encodes redirected
    # output with the ANSI code page (cp1252), which cannot represent many
    # real install paths and would crash mid-print.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    app(obj=system)
