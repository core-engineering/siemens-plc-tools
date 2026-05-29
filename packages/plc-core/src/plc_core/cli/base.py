"""Plugin discovery and command group utilities.

This module provides utilities for discovering and loading CLI plugins
from entry points.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    pass


def discover_plugins(group: str = "plc_tools.plugins") -> dict[str, click.Group]:
    """Discover CLI plugins from entry points.

    Parameters
    ----------
    group : str
        Entry point group name to search.

    Returns
    -------
    dict[str, click.Group]
        Mapping from plugin name to click group.
    """
    plugins: dict[str, click.Group] = {}

    eps = entry_points(group=group)

    for ep in eps:
        try:
            plugin_group = ep.load()
            if isinstance(plugin_group, click.Group):
                plugins[ep.name] = plugin_group
        except Exception as e:
            click.echo(f"Warning: Failed to load plugin '{ep.name}': {e}", err=True)

    return plugins


def create_plugin_group(
    cli: click.Group,
    entry_point_group: str = "plc_tools.plugins",
) -> click.Group:
    """Create a click group with auto-discovered plugins.

    Parameters
    ----------
    cli : click.Group
        Base click group to add plugins to.
    entry_point_group : str
        Entry point group name to search for plugins.

    Returns
    -------
    click.Group
        The modified click group with plugins registered.
    """
    plugins = discover_plugins(entry_point_group)
    for name, group in plugins.items():
        cli.add_command(group, name=name)
    return cli
