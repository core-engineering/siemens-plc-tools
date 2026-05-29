"""Rich console output helpers.

This module provides standardized output utilities using Rich for
consistent terminal formatting across PLC tools.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from collections.abc import Sequence

# Global console instance
console = Console()


def print_error(message: str, prefix: str = "Error") -> None:
    """Print an error message in red.

    Parameters
    ----------
    message : str
        Error message to display.
    prefix : str
        Prefix for the message (default: "Error").
    """
    console.print(f"[bold red]{prefix}:[/bold red] {message}")


def print_warning(message: str, prefix: str = "Warning") -> None:
    """Print a warning message in yellow.

    Parameters
    ----------
    message : str
        Warning message to display.
    prefix : str
        Prefix for the message (default: "Warning").
    """
    console.print(f"[bold yellow]{prefix}:[/bold yellow] {message}")


def print_info(message: str, prefix: str = "Info") -> None:
    """Print an info message in blue.

    Parameters
    ----------
    message : str
        Info message to display.
    prefix : str
        Prefix for the message (default: "Info").
    """
    console.print(f"[bold blue]{prefix}:[/bold blue] {message}")


def print_success(message: str, prefix: str = "Success") -> None:
    """Print a success message in green.

    Parameters
    ----------
    message : str
        Success message to display.
    prefix : str
        Prefix for the message (default: "Success").
    """
    console.print(f"[bold green]{prefix}:[/bold green] {message}")


def print_table(
    title: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    show_header: bool = True,
    show_lines: bool = False,
) -> None:
    """Print a formatted table using Rich.

    Parameters
    ----------
    title : str
        Table title.
    columns : Sequence[str]
        Column headers.
    rows : Sequence[Sequence[Any]]
        Table rows (each row is a sequence of cell values).
    show_header : bool
        Whether to show column headers (default: True).
    show_lines : bool
        Whether to show row separator lines (default: False).
    """
    table = Table(title=title, show_header=show_header, show_lines=show_lines)

    for column in columns:
        table.add_column(column)

    for row in rows:
        table.add_row(*[str(cell) for cell in row])

    console.print(table)
