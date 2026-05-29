"""Extract global data block references from SCL code.

This module provides functionality to detect and extract references to
global data blocks (DBs) from parsed SCL blocks, enabling tracking of
implicit dependencies on global variables.
"""

import re
from dataclasses import dataclass, field

from plc_code.parser.models import Block


@dataclass
class GlobalDBReference:
    """A reference to a global data block variable.

    Attributes
    ----------
    db_name : str
        Name of the data block (e.g., "ProcessData").
    field_path : str
        Full field path (e.g., "status.retractionTime").
    full_reference : str
        Complete reference as it appears in code.
    line_number : int
        Approximate line number in source.
    is_write : bool
        True if this is a write access (assignment target).
    """

    db_name: str
    field_path: str
    full_reference: str
    line_number: int = 0
    is_write: bool = False


@dataclass
class BlockDBDependencies:
    """Global DB dependencies for a block.

    Attributes
    ----------
    block_name : str
        Name of the block.
    references : list[GlobalDBReference]
        All DB references found in the block.
    db_names : set[str]
        Unique DB names referenced.
    read_dbs : set[str]
        DBs that are read from.
    write_dbs : set[str]
        DBs that are written to.
    """

    block_name: str
    references: list[GlobalDBReference] = field(default_factory=list)
    db_names: set[str] = field(default_factory=set)
    read_dbs: set[str] = field(default_factory=set)
    write_dbs: set[str] = field(default_factory=set)


# Pattern to match global DB access: "DBName".field or "DBName".field.subfield
# Captures: group(1) = DB name, group(2) = field path
# Handles optional whitespace around dots (parser may add spaces)
GLOBAL_DB_PATTERN = re.compile(
    r'"([A-Za-z][A-Za-z0-9_]*)"'  # DB name in quotes
    r"\s*\.\s*"  # Dot separator with optional whitespace
    r"([A-Za-z_][A-Za-z0-9_\s\.\[\]#]*)",  # Field path (may include spaces)
    re.MULTILINE,
)

# Pattern to detect if a reference is on the left side of an assignment
ASSIGNMENT_PATTERN = re.compile(
    r'"([A-Za-z][A-Za-z0-9_]*)"' r"\s*\.\s*" r"([A-Za-z_][A-Za-z0-9_\s\.\[\]#]*)" r"\s*:=",
    re.MULTILINE,
)

# DB names that are typically constants, not data blocks
CONSTANT_DB_NAMES: set[str] = {
    "ARM1",
    "ARM2",
    "ARM3",
    "ARM4",
    "ARM5",
    "ARM6",
    "ARM7",
    "ARM8",
    "ARM9",
    "NO_ALARM",
    "ALARM",
    "PRE_ALARM",
    "TRUE",
    "FALSE",
}

# SCL keywords that may appear trailing after a variable reference
SCL_TRAILING_KEYWORDS: set[str] = {
    "OR",
    "AND",
    "XOR",
    "NOT",
    "THEN",
    "ELSE",
    "ELSIF",
    "DO",
    "OF",
    "TO",
    "BY",
    "END_IF",
    "END_FOR",
    "END_WHILE",
    "END_CASE",
    "END_REPEAT",
    "RETURN",
    "EXIT",
    "CONTINUE",
}


def _normalize_field_path(field_path: str) -> str:
    """Normalize a field path by removing extra whitespace.

    Parameters
    ----------
    field_path : str
        The raw field path (may contain spaces from parser).

    Returns
    -------
    str
        Normalized field path with spaces removed around dots.
    """
    # Truncate at newline
    if "\n" in field_path:
        field_path = field_path.split("\n")[0]

    # Remove spaces around dots
    normalized = re.sub(r"\s*\.\s*", ".", field_path)

    # Remove spaces around brackets
    normalized = re.sub(r"\s*\[\s*", "[", normalized)
    normalized = re.sub(r"\s*\]\s*", "]", normalized)

    # Remove any trailing whitespace or non-identifier characters
    normalized = re.sub(r"[\s,;()]+$", "", normalized)

    # Remove spaces around hash (temp var marker)
    normalized = re.sub(r"\s*#\s*", "#", normalized)

    # Strip trailing SCL keywords (e.g., "arms[#armIndex].status.endOfRetraction OR")
    # Loop to handle multiple keywords (e.g., "percCollar AND NOT")
    while True:
        words = normalized.split()
        if words and words[-1].upper() in SCL_TRAILING_KEYWORDS:
            normalized = " ".join(words[:-1]) if len(words) > 1 else ""
            # Clean up any trailing punctuation after keyword removal
            normalized = re.sub(r"[\s,;()]+$", "", normalized)
        else:
            break

    return normalized


def extract_db_references(block: Block) -> BlockDBDependencies:
    """Extract all global DB references from a block.

    Parameters
    ----------
    block : Block
        The parsed block to analyze.

    Returns
    -------
    BlockDBDependencies
        All DB dependencies found in the block.
    """
    deps = BlockDBDependencies(block_name=block.name)

    # Get all code content
    code_contents = _get_code_content(block)

    # First pass: find all write accesses
    write_refs: set[str] = set()
    for content, _ in code_contents:
        for match in ASSIGNMENT_PATTERN.finditer(content):
            db_name = match.group(1)
            field_path = _normalize_field_path(match.group(2))
            full_ref = f'"{db_name}".{field_path}'
            write_refs.add(full_ref)

    # Second pass: find all DB references
    seen_refs: set[str] = set()
    for content, base_line in code_contents:
        for match in GLOBAL_DB_PATTERN.finditer(content):
            db_name = match.group(1)
            field_path = _normalize_field_path(match.group(2))
            full_ref = f'"{db_name}".{field_path}'

            # Skip constants
            if db_name in CONSTANT_DB_NAMES:
                continue

            # Skip duplicates
            if full_ref in seen_refs:
                continue
            seen_refs.add(full_ref)

            is_write = full_ref in write_refs

            ref = GlobalDBReference(
                db_name=db_name,
                field_path=field_path,
                full_reference=full_ref,
                line_number=base_line + content[: match.start()].count("\n"),
                is_write=is_write,
            )
            deps.references.append(ref)
            deps.db_names.add(db_name)

            if is_write:
                deps.write_dbs.add(db_name)
            else:
                deps.read_dbs.add(db_name)

    return deps


def _get_code_content(block: Block) -> list[tuple[str, int]]:
    """Get all code content from a block.

    Parameters
    ----------
    block : Block
        The block to extract code from.

    Returns
    -------
    list[tuple[str, int]]
        List of (content, base_line_number) tuples.
    """
    contents: list[tuple[str, int]] = []

    for network in block.networks:
        # Add network content
        if network.content:
            contents.append((network.content, 0))

        # Add region content
        for region in network.regions:
            if region.content:
                contents.append((region.content, 0))

            # Handle nested regions
            for nested in region.nested_regions:
                if nested.content:
                    contents.append((nested.content, 0))

    return contents


def get_db_summary(deps: BlockDBDependencies) -> dict[str, list[str]]:
    """Get a summary of DB dependencies grouped by DB name.

    Parameters
    ----------
    deps : BlockDBDependencies
        The block's DB dependencies.

    Returns
    -------
    dict[str, list[str]]
        Mapping of DB name to list of field paths accessed.
    """
    summary: dict[str, list[str]] = {}

    for ref in deps.references:
        if ref.db_name not in summary:
            summary[ref.db_name] = []
        if ref.field_path not in summary[ref.db_name]:
            summary[ref.db_name].append(ref.field_path)

    # Sort field paths within each DB
    for db_name in summary:
        summary[db_name].sort()

    return dict(sorted(summary.items()))
