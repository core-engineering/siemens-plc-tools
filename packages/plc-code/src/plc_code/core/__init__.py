"""Core utilities for PLC tools.

This module provides core functionality used across the plc-tools package,
including project configuration loading and common utilities.
"""

from plc_code.core.config import (
    ProjectConfig,
    find_config_file,
    load_config,
)

__all__ = [
    "ProjectConfig",
    "load_config",
    "find_config_file",
]
