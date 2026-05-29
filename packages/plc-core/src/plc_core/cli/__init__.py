"""CLI framework for PLC tools.

This module provides utilities for building command-line interfaces,
including plugin discovery and Rich console helpers.

Example
-------
>>> from plc_core.cli import console, print_error, print_success
>>> print_success("Operation completed")
"""

from plc_core.cli.base import create_plugin_group, discover_plugins
from plc_core.cli.output import (
    console,
    print_error,
    print_info,
    print_success,
    print_table,
    print_warning,
)

__all__ = [
    "create_plugin_group",
    "discover_plugins",
    "console",
    "print_error",
    "print_info",
    "print_success",
    "print_warning",
    "print_table",
]
