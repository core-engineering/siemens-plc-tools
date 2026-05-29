"""State machine detection and extraction.

This module provides functions to detect state machine patterns in SCL and LADDER
function blocks, and to dispatch extraction to the appropriate extractor.
"""

import re

from plc_code.analyzer.state_machine.models import StateMachine
from plc_code.parser.models import Block, Region, VariableDeclaration

# Integer types that can be used as state variables
STATE_VAR_TYPES = {"USInt", "Int", "UInt", "SInt", "DInt", "UDInt", "LInt", "ULInt"}

# Common state variable naming patterns
STATE_VAR_NAMES = {"activeState", "state", "currentState", "machineState"}


def has_state_machine(block: Block) -> bool:
    """Detect if a block contains a state machine pattern.

    A block is considered to have a state machine if:
    1. It has a state variable (e.g., activeState) with an integer type
    2. It has at least 2 state constants defined OR uses string-valued CASE
    3. It has state logic (CASE for SCL, EQ_Contact for LADDER)

    Parameters
    ----------
    block : Block
        The parsed block to analyze.

    Returns
    -------
    bool
        True if state machine pattern detected.
    """
    # Only function blocks can have state machines (static variables)
    if block.block_type != "FUNCTION_BLOCK":
        return False

    # Check for state variable
    state_var = _find_state_variable(block)
    if not state_var:
        return False

    # Check for state logic first
    if not _has_state_logic(block, state_var.name):
        return False

    # Check for state constants (at least 2 states) OR string-valued CASE branches
    constants = _find_state_constants(block)
    if len(constants) >= 2:
        return True

    # For blocks without VAR CONSTANT, check for string-valued CASE
    return _has_string_valued_case(block, state_var.name)


def extract_state_machine(block: Block) -> StateMachine | None:
    """Extract state machine from a block.

    Dispatches to the appropriate extractor based on block language.

    Parameters
    ----------
    block : Block
        The parsed block to extract from.

    Returns
    -------
    StateMachine | None
        Extracted state machine or None if not found.
    """
    if not has_state_machine(block):
        return None

    if block.is_ladder:
        from plc_code.analyzer.state_machine.ladder_extractor import (
            extract_ladder_state_machine,
        )

        return extract_ladder_state_machine(block)
    else:
        from plc_code.analyzer.state_machine.scl_extractor import (
            extract_scl_state_machine,
        )

        return extract_scl_state_machine(block)


def _find_state_variable(block: Block) -> VariableDeclaration | None:
    """Find the state variable in VAR section.

    Parameters
    ----------
    block : Block
        The block to search.

    Returns
    -------
    VariableDeclaration | None
        The state variable if found.
    """
    for var in block.static_vars:
        # Check for common state variable names
        if var.name in STATE_VAR_NAMES or var.name.endswith("State"):
            # Must be integer type
            if var.data_type in STATE_VAR_TYPES:
                return var
    return None


def _find_state_constants(block: Block) -> list[VariableDeclaration]:
    """Find state constants in VAR CONSTANT section.

    Parameters
    ----------
    block : Block
        The block to search.

    Returns
    -------
    list[VariableDeclaration]
        List of potential state constants.
    """
    return [
        const
        for const in block.constants
        if const.data_type in STATE_VAR_TYPES and const.default_value is not None
    ]


def _has_state_logic(block: Block, state_var: str) -> bool:
    """Check if block has CASE or LADDER state logic.

    Parameters
    ----------
    block : Block
        The block to check.
    state_var : str
        Name of the state variable.

    Returns
    -------
    bool
        True if state logic is present.
    """
    # Check for CASE #activeState OF pattern in SCL
    if block.is_scl:
        return _has_scl_state_logic(block, state_var)

    # Check for EQ_Contact pattern in LADDER
    if block.is_ladder:
        return _has_ladder_state_logic(block, state_var)

    return False


_CASE_RE_CACHE: dict[str, "re.Pattern[str]"] = {}


def _has_scl_state_logic(block: Block, state_var: str) -> bool:
    """Check for SCL CASE statement on state variable.

    Parameters
    ----------
    block : Block
        The block to check.
    state_var : str
        Name of the state variable.

    Returns
    -------
    bool
        True if CASE statement found.
    """
    import re

    # The parser may emit any whitespace pattern around `#` and the variable
    # name (e.g. "CASE #activeState", "CASE # activeState", "CASE#activeState").
    # Match all of them with a single regex, cached per state_var.
    case_re = _CASE_RE_CACHE.get(state_var)
    if case_re is None:
        case_re = re.compile(rf"\bCASE\s*#\s*{re.escape(state_var)}\b", re.IGNORECASE)
        _CASE_RE_CACHE[state_var] = case_re

    for network in block.networks:
        if case_re.search(network.content):
            return True
        for region in network.regions:
            if _check_region_for_regex(region, case_re):
                return True

    return False


def _check_region_for_pattern(region: Region, pattern: str) -> bool:
    """Recursively check region and nested regions for pattern.

    Parameters
    ----------
    region : Region
        The region to check.
    pattern : str
        Pattern to search for.

    Returns
    -------
    bool
        True if pattern found.
    """
    if pattern in region.content:
        return True

    for nested in region.nested_regions:
        if _check_region_for_pattern(nested, pattern):
            return True

    return False


def _check_region_for_regex(region: Region, pattern: "re.Pattern[str]") -> bool:
    """Recursively check region and nested regions for a regex match."""
    if pattern.search(region.content):
        return True

    for nested in region.nested_regions:
        if _check_region_for_regex(nested, pattern):
            return True

    return False


def _has_ladder_state_logic(block: Block, state_var: str) -> bool:
    """Check for LADDER EQ_Contact pattern on state variable.

    Parameters
    ----------
    block : Block
        The block to check.
    state_var : str
        Name of the state variable.

    Returns
    -------
    bool
        True if EQ_Contact pattern found.
    """
    for network in block.networks:
        # Check in network content
        content = network.content
        if "EQ_Contact" in content and (f"#{state_var}" in content or "#activeState" in content):
            return True

        # Check in ladder_elements (LADDER blocks store content here)
        for element in network.ladder_elements:
            if "EQ_Contact" in element and (f"#{state_var}" in element or "#activeState" in element):
                return True

    return False


def _has_string_valued_case(block: Block, state_var: str) -> bool:
    """Check if block has CASE with string-valued states.

    This detects blocks like MotionMode that use "STATE_NAME" directly
    instead of VAR CONSTANT definitions.

    Parameters
    ----------
    block : Block
        The block to check.
    state_var : str
        Name of the state variable.

    Returns
    -------
    bool
        True if string-valued CASE with at least 2 branches found.
    """
    # Pattern to find string-valued case branches: "STATE_NAME":
    string_case_pattern = re.compile(r'"(\w+)":', re.IGNORECASE)

    for network in block.networks:
        # Check network content
        matches = string_case_pattern.findall(network.content)
        if len(matches) >= 2:
            return True

        # Check regions
        for region in network.regions:
            match_count = _count_string_case_branches(region, string_case_pattern)
            if match_count >= 2:
                return True

    return False


def _count_string_case_branches(region: Region, pattern: "re.Pattern[str]") -> int:
    """Count string-valued CASE branches in region.

    Parameters
    ----------
    region : Region
        The region to check.
    pattern : re.Pattern
        The regex pattern for string case branches.

    Returns
    -------
    int
        Number of branches found.
    """

    matches = set(pattern.findall(region.content))
    for nested in region.nested_regions:
        matches.update(pattern.findall(nested.content))
        # Recurse into nested regions
        for deep_nested in nested.nested_regions:
            matches.update(pattern.findall(deep_nested.content))

    return len(matches)


def find_state_variable(block: Block) -> VariableDeclaration | None:
    """Public interface to find state variable.

    Parameters
    ----------
    block : Block
        The block to search.

    Returns
    -------
    VariableDeclaration | None
        The state variable if found.
    """
    return _find_state_variable(block)


def find_state_constants(block: Block) -> list[VariableDeclaration]:
    """Public interface to find state constants.

    Parameters
    ----------
    block : Block
        The block to search.

    Returns
    -------
    list[VariableDeclaration]
        List of state constants.
    """
    return _find_state_constants(block)
