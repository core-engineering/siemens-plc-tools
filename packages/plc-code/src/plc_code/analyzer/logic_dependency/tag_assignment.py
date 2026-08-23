"""Tag assignment finder for PLC programs.

This module finds where I/O tags are assigned or read in the program,
mapping physical tags to their corresponding data structure fields.
"""

from dataclasses import dataclass

from plc_code.parser.models import Block

from .access_index import access_index
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


def _is_io_tag(name: str) -> bool:
    """Check if a name is an I/O tag."""
    prefixes = ("DO_", "SDO_", "DI_", "SDI_", "AI_", "SAI_")
    return any(name.startswith(p) for p in prefixes)


def find_assignments_in_block(block: Block, tag_names: set[str]) -> list[TagAssignment]:
    """Find all tag assignments in a block.

    A tag is a bare quoted symbol (``"DO_PUMP_1"``) that is either in
    ``tag_names`` or named like an I/O tag. Each access of one is reported with
    the field it maps to: for a direct assignment the other side, for a ladder
    coil its contacts, for a Move box the other operand.

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
    for access in access_index(block).accesses:
        name = _bare_symbol(access.path)
        if name is None or not (name in tag_names or _is_io_tag(name)):
            continue
        direction = "write" if access.is_write else "read"
        if access.element == "assignment":
            if access.is_write:
                mapped = access.expression
            elif (
                access.dependencies
                and access.dependencies[0].startswith('"')
                and access.statement == f"{access.dependencies[0]} := {access.path};"
            ):
                mapped = access.dependencies[0]  # `"DB".field := "TAG";`, the tag copied whole
            else:
                continue  # a tag read inside a larger expression is not a mapping
            assignment_type = "direct"
        elif access.element == "coil":
            # The contact nearest the coil (the last on the rail) is its mapping.
            mapped = access.dependencies[-1] if access.dependencies else ""
            assignment_type = "ladder_coil"
        elif access.element == "contact":
            mapped = "(ladder network)"
            assignment_type = "ladder_contact"
        elif access.element == "box" and access.statement.startswith("Move("):
            mapped = (
                access.expression
                if access.is_write
                else (access.dependencies[0] if access.dependencies else "")
            )
            assignment_type = "ladder_move"
        else:
            continue
        assignments.append(
            TagAssignment(
                tag_name=name,
                mapped_field=mapped,
                block_name=block.name,
                line_number=access.line,
                assignment_type=assignment_type,
                direction=direction,
                source_expression=access.statement,
            )
        )
    return assignments


def _bare_symbol(path: str) -> str | None:
    """``"NAME"`` -> ``NAME``; ``None`` for a path with members, a local or an address."""
    if path.startswith('"') and path.endswith('"') and path.count('"') == 2:
        return path[1:-1]
    return None


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
        for assignment in find_assignments_in_block(block, tag_names):
            # Keep the primary mapping: a write over a read, a direct assignment
            # or Move over a coil, a coil over a contact; source order breaks ties.
            current = result.get(assignment.tag_name)
            if current is None or _rank(assignment) < _rank(current):
                result[assignment.tag_name] = assignment

    return result


_TYPE_RANK = {"direct": 0, "ladder_move": 1, "ladder_coil": 2, "ladder_contact": 3}


def _rank(assignment: TagAssignment) -> tuple[int, int]:
    return (0 if assignment.direction == "write" else 1, _TYPE_RANK.get(assignment.assignment_type, 9))


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
