"""State variable detector for PLC programs.

This module identifies state variables that serve as termination points
for dependency tracing. State variables are typically:
- Part of state machines (motionMode, userMode, ersState, safetyState)
- Located in .status paths in data structures
- USInt/Int types used in CASE statements
"""

import re
from dataclasses import dataclass

from plc_code.parser.models import Block


def _normalize_field_path(field_path: str) -> str:
    """Normalize a field path for comparison.

    Handles parser-added spaces: "ProcessData" . station . input . field
    """
    # Remove spaces around dots and brackets
    normalized = re.sub(r"\s*\.\s*", ".", field_path)
    normalized = re.sub(r"\s*\[\s*", "[", normalized)
    normalized = re.sub(r"\s*\]\s*", "]", normalized)
    # Remove # and surrounding spaces in array indices
    normalized = re.sub(r"\[\s*#\s*", "[#", normalized)
    return normalized


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


# Patterns for identifying state variables
STATE_FIELD_PATTERNS = [
    # Common state field names
    r"\.status\.(motionMode|userMode|safetyState|ersState|userState|alarmState)",
    r"\.status\.[a-zA-Z]*[Ss]tate",
    r"\.status\.[a-zA-Z]*[Mm]ode",
    # Fields ending in State or Mode
    r"\.[a-zA-Z]+State$",
    r"\.[a-zA-Z]+Mode$",
    # Safety state patterns
    r"SafetyData.*\.status\.",
]

# Patterns for state variable names (local variables)
STATE_VAR_PATTERNS = [
    r"^activeState$",
    r"^state$",
    r"^currentState$",
    r"State$",
    r"Mode$",
]

# I/O tag prefixes (these are also termination points)
IO_TAG_PREFIXES = ("DO_", "SDO_", "DI_", "SDI_", "AI_", "SAI_")


@dataclass
class StateVariable:
    """Represents a detected state variable."""

    name: str
    block_name: str
    pattern_matched: str
    context: str  # e.g., "CASE statement", "assignment target"


def is_io_tag(name: str) -> bool:
    """Check if a name is a physical I/O tag.

    Parameters
    ----------
    name : str
        The name to check.

    Returns
    -------
    bool
        True if this is an I/O tag.
    """
    # Handle quoted tag names
    clean_name = name.strip('"')
    return any(clean_name.startswith(p) for p in IO_TAG_PREFIXES)


def is_state_variable(field_path: str) -> bool:
    """Check if a field path is a state variable.

    Parameters
    ----------
    field_path : str
        The field path to check (e.g., "ProcessData".status.motionMode).

    Returns
    -------
    bool
        True if this appears to be a state variable.
    """
    # Normalize the path to handle parser-added spaces
    normalized = _normalize_field_path(field_path)
    for pattern in STATE_FIELD_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return True
    return False


def is_state_var_name(var_name: str) -> bool:
    """Check if a local variable name is a state variable.

    Parameters
    ----------
    var_name : str
        The variable name to check (without # prefix).

    Returns
    -------
    bool
        True if this appears to be a state variable.
    """
    clean_name = var_name.lstrip("#").strip()
    for pattern in STATE_VAR_PATTERNS:
        if re.search(pattern, clean_name, re.IGNORECASE):
            return True
    return False


def is_termination_point(name: str, io_tag_names: set[str] | None = None) -> bool:
    """Check if a variable is a termination point for tracing.

    A termination point is either:
    - A state variable
    - An I/O tag

    Parameters
    ----------
    name : str
        The variable/field name to check.
    io_tag_names : set[str] | None
        Optional set of known I/O tag names for faster lookup.

    Returns
    -------
    bool
        True if this is a termination point.
    """
    # Check I/O tags first
    if io_tag_names and name.strip('"') in io_tag_names:
        return True
    if is_io_tag(name):
        return True

    # Check state variables
    if is_state_variable(name):
        return True

    # Check local state variable names
    if name.startswith("#") and is_state_var_name(name):
        return True

    return False


def detect_state_variables_in_block(block: Block) -> list[StateVariable]:
    """Detect state variables used in a block.

    Parameters
    ----------
    block : Block
        The block to analyze.

    Returns
    -------
    list[StateVariable]
        List of detected state variables.
    """
    state_vars = []
    content = _get_block_content(block)
    seen = set()

    # Find variables used in CASE statements
    case_pattern = re.compile(r'\bCASE\s+(#\s*[a-zA-Z_][a-zA-Z0-9_]*|"[^"]+"\S*)\s+OF\b', re.IGNORECASE)
    for match in case_pattern.finditer(content):
        var = match.group(1).strip()
        if var not in seen:
            seen.add(var)
            state_vars.append(
                StateVariable(
                    name=var,
                    block_name=block.name,
                    pattern_matched="CASE statement",
                    context="CASE statement variable",
                )
            )

    # Find global DB fields with state-like names in assignments
    global_pattern = re.compile(r'"[^"]+"\.[a-zA-Z0-9_.\[\]]+')
    for match in global_pattern.finditer(content):
        field = match.group(0)
        if field not in seen and is_state_variable(field):
            seen.add(field)
            state_vars.append(
                StateVariable(
                    name=field,
                    block_name=block.name,
                    pattern_matched="state field pattern",
                    context="global field access",
                )
            )

    return state_vars


def detect_all_state_variables(blocks: list[Block]) -> dict[str, StateVariable]:
    """Detect all state variables across all blocks.

    Parameters
    ----------
    blocks : list[Block]
        List of blocks to analyze.

    Returns
    -------
    dict[str, StateVariable]
        Dictionary mapping variable names to their info.
    """
    all_vars: dict[str, StateVariable] = {}

    for block in blocks:
        vars_in_block = detect_state_variables_in_block(block)
        for var in vars_in_block:
            if var.name not in all_vars:
                all_vars[var.name] = var

    return all_vars


def get_state_variable_names(blocks: list[Block]) -> set[str]:
    """Get a set of all state variable names.

    Parameters
    ----------
    blocks : list[Block]
        List of blocks to analyze.

    Returns
    -------
    set[str]
        Set of state variable names.
    """
    state_vars = detect_all_state_variables(blocks)
    return set(state_vars.keys())


def classify_variable(
    name: str, io_tag_names: set[str] | None = None, state_var_names: set[str] | None = None
) -> str:
    """Classify a variable as io_tag, state_var, or field.

    Parameters
    ----------
    name : str
        The variable name to classify.
    io_tag_names : set[str] | None
        Set of known I/O tag names.
    state_var_names : set[str] | None
        Set of known state variable names.

    Returns
    -------
    str
        One of: "io_tag", "state_var", "local", "field"
    """
    clean_name = name.strip('"')

    # Check I/O tags
    if io_tag_names and clean_name in io_tag_names:
        return "io_tag"
    if is_io_tag(name):
        return "io_tag"

    # Check state variables
    if state_var_names and name in state_var_names:
        return "state_var"
    if is_state_variable(name):
        return "state_var"
    if name.startswith("#") and is_state_var_name(name):
        return "state_var"

    # Check local variables
    if name.startswith("#"):
        return "local"

    # Default to field
    return "field"
