"""Human output. The only module that imports Rich; JSON runs never load it."""

from rich.console import Console
from rich.table import Table
from rich.text import Text

from versionbar.models import CheckResult, ScanResult

# Wide enough that no real path wraps; the table still shrinks to its content.
_PIPE_WIDTH = 10_000


def _console(*, terminal: bool, color: bool) -> Console:
    return Console(
        force_terminal=color,
        no_color=not color,
        color_system="auto" if color else None,
        # On a terminal Rich measures the real window (honouring COLUMNS, the
        # standard override). Piped output has no width, so lines never wrap
        # and each tool stays on one greppable line.
        width=None if terminal else _PIPE_WIDTH,
        highlight=False,
    )


def print_list(result: ScanResult, *, terminal: bool, color: bool) -> None:
    table = Table(box=None, pad_edge=False)
    table.add_column("Tool", style="bold")
    table.add_column("Version")
    table.add_column("Path", overflow="fold")
    table.add_column("Others", justify="right")
    for tool in result.tools:
        if tool.active is not None:
            others = len(tool.installs) - 1
            table.add_row(
                tool.id, tool.active.version, tool.active.path, str(others) if others else ""
            )
        else:
            table.add_row(Text(tool.id, style="dim"), Text(tool.status, style="dim red"), "", "")
    _console(terminal=terminal, color=color).print(table)


def print_check(result: CheckResult, *, terminal: bool, color: bool) -> None:
    """One line per requirement; the message is the explanation, so nothing is left unsaid."""
    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column()
    table.add_column(no_wrap=True)
    table.add_column()
    for item in result.requirements:
        verdict = Text("pass", style="green") if item.passed else Text("FAIL", style="bold red")
        table.add_row(verdict, item.requirement, item.message)
    _console(terminal=terminal, color=color).print(table)


def print_show(result: ScanResult, *, terminal: bool, color: bool) -> None:
    """One row per install, the active one first, so `grep git` shows them all."""
    table = Table(box=None, pad_edge=False)
    table.add_column("Tool", style="bold")
    table.add_column("")
    table.add_column("Version")
    table.add_column("Path", overflow="fold")
    table.add_column("Source")
    notes: list[str] = []
    for tool in result.tools:
        if not tool.installs:
            table.add_row(
                Text(tool.id, style="dim"), Text(tool.status, style="dim red"), "", "", ""
            )
        for index, install in enumerate(tool.installs):
            role = Text("active", style="green") if index == 0 else Text("other", style="dim")
            source = (
                install.source if install.via is None else f"{install.source} via {install.via}"
            )
            table.add_row(
                tool.id if index == 0 else "", role, install.version, install.path, source
            )
        notes.extend(f"{tool.id}: {note}" for note in tool.notes)
    console = _console(terminal=terminal, color=color)
    console.print(table)
    for note in notes:
        console.print(Text(note, style="dim"))
