"""Configuration framework for PLC tools.

This module provides YAML-based configuration loading and management,
with support for hierarchical configuration and path resolution.

Example
-------
>>> from plc_core.config import find_config_file, load_yaml
>>> config_path = find_config_file()
>>> data = load_yaml(config_path)
"""

from plc_core.config.base import BaseConfig, PathsConfig
from plc_core.config.loader import find_config_file, load_yaml

__all__ = [
    "BaseConfig",
    "PathsConfig",
    "find_config_file",
    "load_yaml",
]
