"""Block discovery and categorization.

This module provides utilities for discovering SCL files in a project
and organizing them into logical categories based on directory structure.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BlockFile:
    """A discovered block file with metadata.

    Attributes
    ----------
    source_path : Path
        Path to the .s7dcl file.
    resource_path : Path | None
        Path to the .s7res file if it exists.
    name : str
        Block name (from filename).
    category : str
        Category derived from path structure.
    subcategory : str
        Subcategory derived from path structure.
    relative_path : Path
        Path relative to source root.
    """

    source_path: Path
    resource_path: Path | None = None
    name: str = ""
    category: str = ""
    subcategory: str = ""
    relative_path: Path = field(default_factory=lambda: Path("."))

    def __post_init__(self) -> None:
        """Initialize derived fields."""
        if not self.name:
            self.name = self.source_path.stem


def discover_blocks(
    source_dir: Path,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> list[BlockFile]:
    """Discover all block files in a directory.

    Parameters
    ----------
    source_dir : Path
        Root directory to search.
    include_patterns : list[str] | None
        Glob patterns for files to include. Defaults to ["**/*.s7dcl"].
    exclude_patterns : list[str] | None
        Glob patterns for files to exclude.

    Returns
    -------
    list[BlockFile]
        List of discovered block files with metadata.
    """
    if include_patterns is None:
        include_patterns = ["**/*.s7dcl"]
    if exclude_patterns is None:
        exclude_patterns = []

    blocks: list[BlockFile] = []
    seen_paths: set[Path] = set()

    for pattern in include_patterns:
        for source_path in source_dir.glob(pattern):
            if source_path in seen_paths:
                continue

            # Check exclusions
            relative = source_path.relative_to(source_dir)
            excluded = False
            for exclude in exclude_patterns:
                if source_path.match(exclude):
                    excluded = True
                    break

            if excluded:
                continue

            seen_paths.add(source_path)

            # Look for companion .s7res file
            resource_candidate = source_path.with_suffix(".s7res")
            resource_path: Path | None = resource_candidate if resource_candidate.exists() else None

            # Extract category from path
            category, subcategory = _extract_categories(relative)

            blocks.append(
                BlockFile(
                    source_path=source_path,
                    resource_path=resource_path,
                    name=source_path.stem,
                    category=category,
                    subcategory=subcategory,
                    relative_path=relative,
                )
            )

    # Sort by category, then name
    blocks.sort(key=lambda b: (b.category, b.subcategory, b.name))

    return blocks


def _extract_categories(relative_path: Path) -> tuple[str, str]:
    """Extract category and subcategory from path structure.

    Handles TIA Portal export naming like:
    - "PLC blocks/Category/MyBlock.s7dcl"
    - "PLC data types/20 - Parameters/typeUnitGeometry.s7dcl"

    Preserves the full TIA Portal directory names including numeric prefixes.

    Parameters
    ----------
    relative_path : Path
        Path relative to source root.

    Returns
    -------
    tuple[str, str]
        (category, subcategory) tuple.
    """
    parts = relative_path.parts[:-1]  # Exclude filename

    if not parts:
        return ("", "")

    # Keep full TIA Portal names, only filter out root directories
    categories = []
    for part in parts:
        if part not in ("PLC blocks", "PLC data types", ".vci"):
            categories.append(part)

    if len(categories) == 0:
        return ("", "")
    elif len(categories) == 1:
        return (categories[0], "")
    else:
        return (categories[0], " / ".join(categories[1:]))


def group_by_category(blocks: list[BlockFile]) -> dict[str, list[BlockFile]]:
    """Group blocks by their category.

    Parameters
    ----------
    blocks : list[BlockFile]
        List of block files.

    Returns
    -------
    dict[str, list[BlockFile]]
        Blocks grouped by category name.
    """
    groups: dict[str, list[BlockFile]] = {}

    for block in blocks:
        category = block.category or "Uncategorized"
        if category not in groups:
            groups[category] = []
        groups[category].append(block)

    return groups


def group_by_type(blocks: list[BlockFile]) -> dict[str, list[BlockFile]]:
    """Group blocks by inferred type (from path).

    Parameters
    ----------
    blocks : list[BlockFile]
        List of block files.

    Returns
    -------
    dict[str, list[BlockFile]]
        Blocks grouped by type (blocks, types, functions).
    """
    groups: dict[str, list[BlockFile]] = {
        "blocks": [],
        "types": [],
        "functions": [],
    }

    for block in blocks:
        # Infer type from path
        path_str = str(block.relative_path).lower()
        if "data type" in path_str or block.name.startswith("type"):
            groups["types"].append(block)
        elif "function" in path_str and "block" not in path_str:
            groups["functions"].append(block)
        else:
            groups["blocks"].append(block)

    return groups
