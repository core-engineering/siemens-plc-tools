"""Test file discovery by naming convention.

This module provides functions to discover test files for SCL blocks
based on naming conventions like test_<BlockName>.py.
"""

import re
from pathlib import Path


def discover_test_file(
    block_name: str,
    test_dirs: list[Path],
) -> Path | None:
    """Find test file for a block by naming convention.

    Searches for test files matching common naming patterns:
    - test_<block_name>.py (exact match)
    - test_<block_name_lowercase>.py (lowercase)
    - test_<block_name_snake_case>.py (snake_case conversion)
    - test_fb<block_name>.py (function block prefix)
    - test_fc<block_name>.py (function prefix)

    Parameters
    ----------
    block_name : str
        Name of the SCL block (e.g., "MotorStarter").
    test_dirs : list[Path]
        Directories to search for test files.

    Returns
    -------
    Path | None
        Path to the test file, or None if not found.
    """
    # Generate candidate test file names
    candidates = _generate_test_file_candidates(block_name)

    for test_dir in test_dirs:
        if not test_dir.exists():
            continue

        for candidate in candidates:
            test_file = test_dir / candidate
            if test_file.exists():
                return test_file

            # Also search recursively in subdirectories
            for match in test_dir.rglob(candidate):
                if match.is_file():
                    return match

    return None


def _generate_test_file_candidates(block_name: str) -> list[str]:
    """Generate candidate test file names for a block.

    Parameters
    ----------
    block_name : str
        Name of the SCL block.

    Returns
    -------
    list[str]
        List of possible test file names to search for.
    """
    candidates = []

    # Exact match
    candidates.append(f"test_{block_name}.py")

    # Lowercase
    candidates.append(f"test_{block_name.lower()}.py")

    # Snake case conversion (CamelCase -> snake_case)
    snake_case = _camel_to_snake(block_name)
    if snake_case != block_name.lower():
        candidates.append(f"test_{snake_case}.py")

    # Function block/function prefix variations
    candidates.append(f"test_fb{block_name}.py")
    candidates.append(f"test_fb{block_name.lower()}.py")
    candidates.append(f"test_fc{block_name}.py")
    candidates.append(f"test_fc{block_name.lower()}.py")

    # With underscores removed
    no_underscore = block_name.replace("_", "")
    if no_underscore != block_name:
        candidates.append(f"test_{no_underscore.lower()}.py")

    return candidates


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case.

    Parameters
    ----------
    name : str
        CamelCase string.

    Returns
    -------
    str
        snake_case string.
    """
    # Insert underscore before uppercase letters (except at start)
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def build_test_registry(
    block_names: list[str],
    test_dirs: list[Path],
) -> dict[str, Path]:
    """Build a mapping of block names to their test files.

    Parameters
    ----------
    block_names : list[str]
        Names of all SCL blocks in the project.
    test_dirs : list[Path]
        Directories to search for test files.

    Returns
    -------
    dict[str, Path]
        Mapping from block name to test file path.
    """
    registry: dict[str, Path] = {}

    for block_name in block_names:
        test_file = discover_test_file(block_name, test_dirs)
        if test_file is not None:
            registry[block_name] = test_file

    return registry


def scan_test_directory(test_dir: Path) -> dict[str, Path]:
    """Scan a test directory and extract block names from test files.

    This function parses test file names to determine which blocks they test.
    It uses common naming patterns to extract block names.

    Parameters
    ----------
    test_dir : Path
        Directory containing test files.

    Returns
    -------
    dict[str, Path]
        Mapping from inferred block name to test file path.
    """
    registry: dict[str, Path] = {}

    if not test_dir.exists():
        return registry

    for test_file in test_dir.glob("test_*.py"):
        # Extract block name from file name
        block_names = _extract_block_names_from_test_file(test_file.name)
        for block_name in block_names:
            if block_name not in registry:
                registry[block_name] = test_file

    return registry


def _extract_block_names_from_test_file(filename: str) -> list[str]:
    """Extract possible block names from a test file name.

    Parameters
    ----------
    filename : str
        Test file name (e.g., "test_acknowledged_alarm.py").

    Returns
    -------
    list[str]
        Possible block names this file might test.
    """
    # Remove test_ prefix and .py suffix
    name = filename[5:-3]  # Strip "test_" and ".py"

    candidates = []

    # Direct name (as-is)
    candidates.append(name)

    # Remove fb/fc prefix
    if name.startswith("fb"):
        candidates.append(name[2:])
    if name.startswith("fc"):
        candidates.append(name[2:])

    # Convert snake_case to CamelCase
    camel = _snake_to_camel(name)
    if camel != name:
        candidates.append(camel)

    # Handle fb/fc prefix in camel case
    if name.startswith("fb"):
        candidates.append(_snake_to_camel(name[2:]))
    if name.startswith("fc"):
        candidates.append(_snake_to_camel(name[2:]))

    return candidates


def _snake_to_camel(name: str) -> str:
    """Convert snake_case to CamelCase.

    Parameters
    ----------
    name : str
        snake_case string.

    Returns
    -------
    str
        CamelCase string.
    """
    components = name.split("_")
    return "".join(x.capitalize() for x in components)
