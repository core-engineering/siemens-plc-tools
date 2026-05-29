"""Configuration file discovery and loading utilities.

This module provides functions to find and load YAML configuration files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Default configuration filenames to search for
CONFIG_FILENAMES = ["plc.yaml", "plc.yml"]


def find_config_file(
    start_path: Path | None = None,
    filenames: list[str] | None = None,
) -> Path | None:
    """Find configuration file by searching up the directory tree.

    Searches for config file in:
    1. start_path (if provided)
    2. Current directory
    3. Parent directories (up to root)

    Parameters
    ----------
    start_path : Path | None
        Starting directory for search.
    filenames : list[str] | None
        List of config filenames to search for. Defaults to CONFIG_FILENAMES.

    Returns
    -------
    Path | None
        Path to config file, or None if not found.
    """
    if start_path is None:
        start_path = Path.cwd()

    if filenames is None:
        filenames = CONFIG_FILENAMES

    start_path = start_path.resolve()

    # If start_path is a file, use its parent
    if start_path.is_file():
        start_path = start_path.parent

    # Search current and parent directories
    current = start_path
    while True:
        for filename in filenames:
            config_path = current / filename
            if config_path.exists():
                return config_path

        # Move to parent
        parent = current.parent
        if parent == current:
            # Reached root
            break
        current = parent

    return None


def load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML file and return its contents.

    Parameters
    ----------
    path : Path
        Path to YAML file.

    Returns
    -------
    dict[str, Any]
        Parsed YAML content.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    yaml.YAMLError
        If the file has invalid YAML syntax.
    """
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data if data is not None else {}


def generate_default_config(
    name: str = "PLC Project",
    code: str = "",
    version: str = "1.0.0",
) -> str:
    """Generate default plc.yaml content.

    Parameters
    ----------
    name : str
        Project name.
    code : str
        Project code.
    version : str
        Project version.

    Returns
    -------
    str
        YAML content for plc.yaml.
    """
    return f"""# PLC Project Configuration
# This file configures the plc tool for this project.

project:
  name: "{name}"
  code: "{code}"
  version: "{version}"

# Shared paths
paths:
  root: .                             # Project root (auto-detected)

# SCL module configuration
scl:
  paths:
    source: program-listings/PLC blocks
    types: program-listings/PLC data types
    docs: docs
    tests: test-cases
  quality:
    enabled: true
    exclude_rules: []
  docs:
    include_source: true
    syntax_highlighting: true

# IOL module configuration
iol:
  paths:
    tags: <project-root>/tags
    iol: specifications/iol
    database: .iol
  functional_groups:
    - id: COMMON
      name: "Common Equipment"
      xml_files: [Common.xml]
  naming:
    pattern: "{{io_category}}_{{location}}_{{signal}}"
    max_length: 64
"""
