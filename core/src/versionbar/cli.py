import io
import json
import sys

import typer

from versionbar import __version__
from versionbar.capture import DEFAULT_OUT_DIR, CaptureError, capture_tool
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
            failure = {"outcome": error.outcome, "tool": tool, "message": error.message}
            typer.echo(json.dumps(failure, indent=2))
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
