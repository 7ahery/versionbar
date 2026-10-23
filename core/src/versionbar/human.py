"""Human output. The only module that imports Rich; JSON runs never load it."""

from rich.console import Console
from rich.table import Table
from rich.text import Text

from versionbar.models import ScanResult

# Wide enough that no real path wraps; the table still shrinks to its content.
_PIPE_WIDTH = 10_000


def print_list(result: ScanResult, *, terminal: bool, color: bool) -> None:
    console = Console(
        force_terminal=color,
        no_color=not color,
        color_system="auto" if color else None,
        # On a terminal Rich measures the real window (honouring COLUMNS, the
        # standard override). Piped output has no width, so lines never wrap
        # and each tool stays on one greppable line.
        width=None if terminal else _PIPE_WIDTH,
        highlight=False,
    )
    table = Table(box=None, pad_edge=False)
    table.add_column("Tool", style="bold")
    table.add_column("Version")
    table.add_column("Path", overflow="fold")
    for tool in result.tools:
        if tool.active is not None:
            table.add_row(tool.id, tool.active.version, tool.active.path)
        else:
            table.add_row(Text(tool.id, style="dim"), Text(tool.status, style="dim red"), "")
    console.print(table)
