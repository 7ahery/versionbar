"""Human output. The only module that imports Rich; JSON runs never load it."""

from rich.console import Console
from rich.table import Table
from rich.text import Text

from versionbar.models import ScanResult


def print_list(result: ScanResult, *, no_color: bool) -> None:
    # Rich already drops styling when stdout is not a terminal; NO_COLOR is
    # passed explicitly because the environment is read through the system seam.
    # It drops bold/dim too, so NO_COLOR output matches piped output exactly.
    console = Console(color_system=None if no_color else "auto", highlight=False)
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
