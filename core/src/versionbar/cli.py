import typer

from versionbar import __version__

app = typer.Typer(
    name="versionbar",
    help="Inventory the dev tools installed on this machine.",
    no_args_is_help=True,
    add_completion=False,
)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def root(
    _version: bool = typer.Option(
        False, "--version", callback=_show_version, is_eager=True, help="Show the version and exit."
    ),
) -> None:
    pass


def main() -> None:
    app()
