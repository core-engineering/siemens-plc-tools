"""Root CLI for PLC Tools with plugin discovery.

This module provides the main entry point for the `plc` command,
which discovers and loads plugins from installed packages.

Example
-------
>>> # Run from command line
>>> plc --help
>>> plc code lint
>>> plc iol validate
"""

from __future__ import annotations

import sys
from importlib.metadata import entry_points
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from collections.abc import Callable

from plc_tools import __version__


def discover_plugins() -> dict[str, click.Group]:
    """Discover CLI plugins from entry points.

    Searches for plugins registered under 'plc_tools.plugins' entry point group.

    Returns
    -------
    dict[str, click.Group]
        Mapping from plugin name to click group.
    """
    plugins: dict[str, click.Group] = {}

    eps = entry_points(group="plc_tools.plugins")

    for ep in eps:
        try:
            plugin_group = ep.load()
            if isinstance(plugin_group, click.Group):
                plugins[ep.name] = plugin_group
        except Exception as e:
            click.echo(f"Warning: Failed to load plugin '{ep.name}': {e}", err=True)

    return plugins


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="plc-tools")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """PLC Tools - Industrial automation toolset.

    A unified CLI for PLC development tools including:

    \b
    - plc code: PLC code analysis, documentation, and testing
    - plc iol: I/O list management and validation

    Use 'plc <subcommand> --help' for detailed help on each module.
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# Lazy-load plugins when first accessed
_plugins_loaded = False


def _load_plugins() -> None:
    """Load and register all discovered plugins."""
    global _plugins_loaded
    if _plugins_loaded:
        return

    plugins = discover_plugins()
    for name, group in plugins.items():
        cli.add_command(group, name=name)

    _plugins_loaded = True


def main() -> int:
    """Main entry point for the CLI.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for errors).
    """
    _load_plugins()
    try:
        cli(standalone_mode=False)
        return 0
    except click.ClickException as e:
        e.show()
        return e.exit_code
    except click.Abort:
        click.echo("Aborted.", err=True)
        return 1
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
