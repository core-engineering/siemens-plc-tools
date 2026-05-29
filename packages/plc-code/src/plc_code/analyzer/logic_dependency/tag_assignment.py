"""Tag assignment finder for PLC programs.

This module finds where I/O tags are assigned or read in the program,
mapping physical tags to their corresponding data structure fields.
"""

import re
from dataclasses import dataclass

from plc_code.parser.models import Block

from .tag_parser import TagCollection


@dataclass
class TagAssignment:
    """Represents an assignment between a physical tag and a data field."""

    tag_name: str
    mapped_field: str
    block_name: str
    line_number: int
    assignment_type: str  # "direct", "ladder_coil", "ladder_move", "ladder_contact"
    direction: str  # "write" (outputs) or "read" (inputs)
    source_expression: str  # Full expression (for context)

    @property
    def is_output_assignment(self) -> bool:
        """Check if this is an output tag assignment (PLC writes to tag)."""
        return self.direction == "write"

    @property
    def is_input_assignment(self) -> bool:
        """Check if this is an input tag assignment (PLC reads from tag)."""
        return self.direction == "read"


# Regex patterns for different assignment types
# Note: Parser adds spaces around dots and brackets, e.g., "ProcessData" . station . input . field

# Direct SCL assignment: "TAG_NAME" := expression  (output - PLC writes)
PATTERN_OUTPUT_DIRECT = re.compile(r'"([A-Z][A-Z0-9_]*_[A-Z0-9_]+)"\s*:=\s*(.+?)\s*;', re.MULTILINE)

# Direct SCL assignment: field := "TAG_NAME"  (input - PLC reads)
# Handles spaces around dots: "ProcessData" . station . input . field := "TAG" ;
PATTERN_INPUT_DIRECT = re.compile(r'("[^"]+".+?)\s*:=\s*"([A-Z][A-Z0-9_]*_[A-Z0-9_]+)"\s*;', re.MULTILINE)

# Ladder Contact + Coil: Contact(field)\nCoil("TAG")  (output)
# Note: In ladder_elements, these are separate strings joined by newlines
PATTERN_LADDER_COIL = re.compile(
    r'Contact\(\s*(.+?)\s*\)\s*[\n\r]+\s*Coil\(\s*"([A-Z][A-Z0-9_]*_[A-Z0-9_]+)"\s*\)',
    re.MULTILINE | re.DOTALL,
)

# Ladder Contact from tag: Contact("TAG")  (input read)
PATTERN_LADDER_CONTACT_TAG = re.compile(r'Contact\(\s*"([A-Z][A-Z0-9_]*_[A-Z0-9_]+)"\s*\)', re.MULTILINE)

# Ladder Move: Move(in := "TAG", out1 => field)  (input)
PATTERN_LADDER_MOVE_INPUT = re.compile(
    r'Move\(\s*in\s*:=\s*"([A-Z][A-Z0-9_]*_[A-Z0-9_]+)"\s*,\s*out1\s*=>\s*(.+?)\s*\)', re.MULTILINE
)

# Ladder Move: Move(in := field, out1 => "TAG")  (output)
PATTERN_LADDER_MOVE_OUTPUT = re.compile(
    r'Move\(\s*in\s*:=\s*(.+?)\s*,\s*out1\s*=>\s*"([A-Z][A-Z0-9_]*_[A-Z0-9_]+)"\s*\)', re.MULTILINE
)


def _get_line_number(content: str, match_start: int) -> int:
    """Get the line number for a match position."""
    return content[:match_start].count("\n") + 1


def _is_io_tag(name: str) -> bool:
    """Check if a name is an I/O tag."""
    prefixes = ("DO_", "SDO_", "DI_", "SDI_", "AI_", "SAI_")
    return any(name.startswith(p) for p in prefixes)


def _get_block_content(block: Block) -> str:
    """Get the full content from a block (combining networks, regions, and ladder elements)."""
    parts = []
    for network in block.networks:
        if network.content:
            parts.append(network.content)
        # Include ladder elements for LAD blocks
        if network.ladder_elements:
            parts.append("\n".join(network.ladder_elements))
        for region in network.regions:
            if region.content:
                parts.append(region.content)
            # Handle nested regions
            for nested in region.nested_regions:
                if nested.content:
                    parts.append(nested.content)
    return "\n".join(parts)


def find_assignments_in_block(block: Block, tag_names: set[str]) -> list[TagAssignment]:
    """Find all tag assignments in a single block.

    Parameters
    ----------
    block : Block
        The block to search.
    tag_names : set[str]
        Set of known tag names to look for.

    Returns
    -------
    list[TagAssignment]
        List of found tag assignments.
    """
    assignments = []
    content = _get_block_content(block)

    # Direct output assignments: "DO_TAG" := field;
    for match in PATTERN_OUTPUT_DIRECT.finditer(content):
        tag_name = match.group(1)
        if tag_name in tag_names or _is_io_tag(tag_name):
            field = match.group(2).strip()
            assignments.append(
                TagAssignment(
                    tag_name=tag_name,
                    mapped_field=field,
                    block_name=block.name,
                    line_number=_get_line_number(content, match.start()),
                    assignment_type="direct",
                    direction="write",
                    source_expression=match.group(0),
                )
            )

    # Direct input assignments: field := "DI_TAG";
    for match in PATTERN_INPUT_DIRECT.finditer(content):
        tag_name = match.group(2)
        if tag_name in tag_names or _is_io_tag(tag_name):
            field = match.group(1).strip()
            assignments.append(
                TagAssignment(
                    tag_name=tag_name,
                    mapped_field=field,
                    block_name=block.name,
                    line_number=_get_line_number(content, match.start()),
                    assignment_type="direct",
                    direction="read",
                    source_expression=match.group(0),
                )
            )

    # Ladder Coil outputs: Contact(field) Coil("SDO_TAG")
    for match in PATTERN_LADDER_COIL.finditer(content):
        tag_name = match.group(2)
        if tag_name in tag_names or _is_io_tag(tag_name):
            field = match.group(1).strip()
            assignments.append(
                TagAssignment(
                    tag_name=tag_name,
                    mapped_field=field,
                    block_name=block.name,
                    line_number=_get_line_number(content, match.start()),
                    assignment_type="ladder_coil",
                    direction="write",
                    source_expression=match.group(0),
                )
            )

    # Ladder Contact inputs: Contact("SDI_TAG")
    for match in PATTERN_LADDER_CONTACT_TAG.finditer(content):
        tag_name = match.group(1)
        if tag_name in tag_names or _is_io_tag(tag_name):
            # For Contact, the "field" is typically the next Coil target
            # We'll mark it as reading into the ladder network
            assignments.append(
                TagAssignment(
                    tag_name=tag_name,
                    mapped_field="(ladder network)",
                    block_name=block.name,
                    line_number=_get_line_number(content, match.start()),
                    assignment_type="ladder_contact",
                    direction="read",
                    source_expression=match.group(0),
                )
            )

    # Ladder Move inputs: Move(in := "SAI_TAG", out1 => field)
    for match in PATTERN_LADDER_MOVE_INPUT.finditer(content):
        tag_name = match.group(1)
        if tag_name in tag_names or _is_io_tag(tag_name):
            field = match.group(2).strip()
            assignments.append(
                TagAssignment(
                    tag_name=tag_name,
                    mapped_field=field,
                    block_name=block.name,
                    line_number=_get_line_number(content, match.start()),
                    assignment_type="ladder_move",
                    direction="read",
                    source_expression=match.group(0),
                )
            )

    # Ladder Move outputs: Move(in := field, out1 => "TAG")
    for match in PATTERN_LADDER_MOVE_OUTPUT.finditer(content):
        tag_name = match.group(2)
        if tag_name in tag_names or _is_io_tag(tag_name):
            field = match.group(1).strip()
            assignments.append(
                TagAssignment(
                    tag_name=tag_name,
                    mapped_field=field,
                    block_name=block.name,
                    line_number=_get_line_number(content, match.start()),
                    assignment_type="ladder_move",
                    direction="write",
                    source_expression=match.group(0),
                )
            )

    return assignments


def find_all_tag_assignments(
    blocks: list[Block], tags: TagCollection | None = None
) -> dict[str, TagAssignment]:
    """Find all tag assignments across all blocks.

    Parameters
    ----------
    blocks : list[Block]
        List of blocks to search.
    tags : TagCollection | None
        Optional collection of known tags. If None, all found tags
        matching I/O prefixes will be included.

    Returns
    -------
    dict[str, TagAssignment]
        Dictionary mapping tag names to their assignments.
    """
    tag_names = tags.all_tag_names() if tags else set()
    result: dict[str, TagAssignment] = {}

    for block in blocks:
        assignments = find_assignments_in_block(block, tag_names)
        for assignment in assignments:
            # Keep the first assignment found (typically the primary mapping)
            if assignment.tag_name not in result:
                result[assignment.tag_name] = assignment

    return result


def get_tag_to_field_mapping(blocks: list[Block], tags: TagCollection | None = None) -> dict[str, str]:
    """Get a simple mapping from tag names to their mapped fields.

    Parameters
    ----------
    blocks : list[Block]
        List of blocks to search.
    tags : TagCollection | None
        Optional collection of known tags.

    Returns
    -------
    dict[str, str]
        Dictionary mapping tag names to field paths.
    """
    assignments = find_all_tag_assignments(blocks, tags)
    return {name: a.mapped_field for name, a in assignments.items()}


def get_field_to_tag_mapping(blocks: list[Block], tags: TagCollection | None = None) -> dict[str, str]:
    """Get a mapping from field paths to tag names.

    Parameters
    ----------
    blocks : list[Block]
        List of blocks to search.
    tags : TagCollection | None
        Optional collection of known tags.

    Returns
    -------
    dict[str, str]
        Dictionary mapping field paths to tag names.
    """
    assignments = find_all_tag_assignments(blocks, tags)
    return {a.mapped_field: name for name, a in assignments.items() if a.mapped_field != "(ladder network)"}
