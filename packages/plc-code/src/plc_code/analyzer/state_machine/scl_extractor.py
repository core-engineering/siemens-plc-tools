"""SCL state machine extraction.

This module provides functions to extract state machine information from SCL
function blocks by parsing CASE statements and IF transitions.
"""

import re

from plc_code.analyzer.state_machine.models import (
    StateConstant,
    StateMachine,
    StateTransition,
)
from plc_code.parser.models import Block, Region, VariableDeclaration

# Regex patterns for SCL state machine parsing
# Note: Patterns use \s* to handle cases where spaces are stripped by the parser

# Match CASE #variable OF ... END_CASE (spaces optional)
CASE_PATTERN = re.compile(r"CASE\s*#\s*(\w+)\s*OF\s*(.*?)\s*END_CASE", re.DOTALL | re.IGNORECASE)

# Match case branches: #CONSTANT: or "STRING":
# Captures state identifier and branch content until next state or END_CASE.
# The parser may insert whitespace after `#`, so allow `#\s*` between the
# marker and the identifier in every place it appears.
CASE_BRANCH_PATTERN = re.compile(
    r"(#\s*\w+|\"[^\"]+\")\s*:\s*(.*?)" r"(?=(?:#\s*\w+|\"[^\"]+\")\s*:\s*|\s*ELSE\s*|\s*END_CASE)",
    re.DOTALL,
)

# Match IF ... THEN ... #stateVar := #newState (spaces optional)
# Use [^;]* instead of .*? to avoid crossing statement boundaries
IF_TRANSITION_PATTERN = re.compile(
    r"IF\s*([^;]*?)\s*THEN[^;]*?#\s*(\w+)\s*:=\s*(#\s*\w+|\"[^\"]+\")\s*;",
    re.DOTALL | re.IGNORECASE,
)

# Simple assignment pattern without IF (for direct transitions)
DIRECT_ASSIGNMENT_PATTERN = re.compile(r"#\s*(\w+)\s*:=\s*(#\s*\w+|\"[^\"]+\")\s*;", re.IGNORECASE)


def extract_scl_state_machine(block: Block) -> StateMachine | None:
    """Extract state machine from SCL block.

    Parameters
    ----------
    block : Block
        Parsed SCL block.

    Returns
    -------
    StateMachine | None
        Extracted state machine or None if not found.
    """
    from plc_code.analyzer.state_machine.detector import (
        find_state_constants,
        find_state_variable,
    )

    # Find state variable
    state_var = find_state_variable(block)
    if not state_var:
        return None

    # Get constants for value lookup
    constant_vars = find_state_constants(block)
    constant_map = {c.name: c for c in constant_vars}

    # Get all content to search for CASE pattern
    content = _get_all_content(block)

    # Find CASE statement - verify we're operating on the state variable
    case_match = CASE_PATTERN.search(content)
    if not case_match:
        return None

    case_var = case_match.group(1)
    if case_var != state_var.name:
        return None

    case_body = case_match.group(2)

    # Extract states ONLY from CASE branch labels (not all constants)
    # This ensures we only include actual states, not comparison values
    case_states = _extract_states_from_case(case_body)

    # Enrich with constant values where available
    states: list[StateConstant] = []
    for cs in case_states:
        if cs.name in constant_map:
            const = constant_map[cs.name]
            value: int | str
            try:
                value = int(const.default_value) if const.default_value else 0
            except ValueError:
                value = const.default_value or cs.name
            states.append(
                StateConstant(
                    name=cs.name,
                    value=value,
                    data_type=const.data_type,
                    description=const.comment,
                )
            )
        else:
            states.append(cs)

    state_names = {s.name for s in states}

    # Extract transitions from nested regions (primary method for well-structured code)
    transitions = _extract_transitions_from_regions(block, state_var.name, state_names)

    # If no transitions from regions, try extracting from combined content
    if not transitions:
        transitions = _extract_transitions(case_body, state_var.name, state_names)

    # Determine initial state from default value
    initial = _get_initial_state(state_var, states)

    return StateMachine(
        state_variable=state_var.name,
        state_type=state_var.data_type,
        states=states,
        transitions=transitions,
        initial_state=initial,
        block_name=block.name,
        language="SCL",
    )


def _get_all_content(block: Block) -> str:
    """Get all network and region content as a single string.

    Parameters
    ----------
    block : Block
        The block to extract content from.

    Returns
    -------
    str
        Combined content string.
    """
    parts: list[str] = []

    for network in block.networks:
        parts.append(network.content)
        for region in network.regions:
            parts.append(_get_region_content(region))

    return "\n".join(parts)


def _get_region_content(region: Region) -> str:
    """Recursively get region and nested region content.

    Parameters
    ----------
    region : Region
        The region to extract from.

    Returns
    -------
    str
        Combined content.
    """
    parts = [region.content]
    for nested in region.nested_regions:
        parts.append(_get_region_content(nested))
    return "\n".join(parts)


def _extract_transitions_from_regions(
    block: Block, state_var: str, state_names: set[str]
) -> list[StateTransition]:
    """Extract transitions from named regions.

    This method uses region naming conventions to identify state contexts:
    - "STATE_NAME state" indicates a state context
    - "STATE_NAME state transitions" or "STATE_NAME transitions" contains transition logic

    Parameters
    ----------
    block : Block
        The block to extract from.
    state_var : str
        Name of the state variable.
    state_names : set[str]
        Set of valid state names.

    Returns
    -------
    list[StateTransition]
        Extracted transitions.
    """
    transitions: list[StateTransition] = []

    for network in block.networks:
        for region in network.regions:
            _extract_from_region_tree(region, state_var, state_names, transitions, None)

    return transitions


def _extract_from_region_tree(
    region: Region,
    state_var: str,
    state_names: set[str],
    transitions: list[StateTransition],
    current_state: str | None,
) -> None:
    """Recursively extract transitions from region tree.

    Parameters
    ----------
    region : Region
        Current region to process.
    state_var : str
        Name of the state variable.
    state_names : set[str]
        Valid state names.
    transitions : list[StateTransition]
        List to append transitions to.
    current_state : str | None
        Current state context (from parent region).
    """
    # Try to identify state from region name
    region_name = region.name.upper()
    detected_state = current_state

    # Sort state names by length (longest first) to match more specific states first
    # e.g., "ALARM_ACKNOWLEDGE" should match before "ALARM"
    sorted_states = sorted(state_names, key=len, reverse=True)

    # First pass: Check for direct matches (region starts with full state name)
    direct_match_found = False
    for state_name in sorted_states:
        state_upper = state_name.upper()
        if region_name.startswith(state_upper):
            detected_state = state_name
            direct_match_found = True
            break

    # Second pass: If no direct match, try partial matches
    # Handle cases like "FREEWHEEL mode" matching "USER_FREEWHEEL"
    if not direct_match_found:
        for state_name in sorted_states:
            state_upper = state_name.upper()
            parts = state_upper.split("_")
            if len(parts) > 1:
                # Only use the last meaningful part (avoid matching prefixes)
                last_part = parts[-1]
                if region_name.startswith(last_part) and len(last_part) > 3:
                    detected_state = state_name
                    break

    # If this is a transitions region, extract from content
    if "TRANSITION" in region_name and detected_state:
        _extract_transitions_from_content(region.content, state_var, detected_state, state_names, transitions)

    # Recurse into nested regions
    for nested in region.nested_regions:
        _extract_from_region_tree(nested, state_var, state_names, transitions, detected_state)


def _extract_transitions_from_content(
    content: str,
    state_var: str,
    from_state: str,
    state_names: set[str],
    transitions: list[StateTransition],
) -> None:
    """Extract transitions from content within a known state context.

    Parameters
    ----------
    content : str
        Region content to parse.
    state_var : str
        Name of the state variable.
    from_state : str
        The source state for transitions.
    state_names : set[str]
        Valid state names.
    transitions : list[StateTransition]
        List to append transitions to.
    """
    for if_match in IF_TRANSITION_PATTERN.finditer(content):
        condition_raw = if_match.group(1).strip()
        assigned_var = if_match.group(2)
        to_state_raw = if_match.group(3)

        # Only capture transitions on the state variable
        if assigned_var == state_var:
            to_state = _normalize_state_name(to_state_raw)

            # Verify this is a valid state
            if to_state in state_names or to_state_raw.startswith('"'):
                transitions.append(
                    StateTransition(
                        from_state=from_state,
                        to_state=to_state,
                        condition=_simplify_condition(condition_raw),
                        raw_condition=condition_raw,
                    )
                )


def _extract_states_from_constants(
    constants: list[VariableDeclaration],
) -> list[StateConstant]:
    """Extract state constants from VAR CONSTANT declarations.

    Parameters
    ----------
    constants : list[VariableDeclaration]
        Constants from VAR CONSTANT section.

    Returns
    -------
    list[StateConstant]
        Extracted states.
    """
    states: list[StateConstant] = []
    for const in constants:
        # Parse the value
        value: int | str
        if const.default_value is not None:
            try:
                value = int(const.default_value)
            except ValueError:
                value = const.default_value
        else:
            value = 0

        states.append(
            StateConstant(
                name=const.name,
                value=value,
                data_type=const.data_type,
                description=const.comment,
            )
        )

    return states


def _extract_states_from_case(case_body: str) -> list[StateConstant]:
    """Extract states from CASE branch labels.

    This handles cases where string literals are used directly
    instead of constants (e.g., "USER_ANGULAR":).

    Parameters
    ----------
    case_body : str
        The body of the CASE statement.

    Returns
    -------
    list[StateConstant]
        Extracted states.
    """
    states: list[StateConstant] = []
    seen: set[str] = set()

    # Find all branch labels. The parser may insert a space after `#`
    # (e.g. "# NO_ALARM :"), so we normalise that out by stripping the
    # captured prefix when matching.
    branch_pattern = re.compile(r'(#\s*\w+|"[^"]+")\s*:', re.IGNORECASE)
    for match in branch_pattern.finditer(case_body):
        raw_name = match.group(1)
        name = _normalize_state_name(raw_name)

        if name not in seen:
            seen.add(name)
            states.append(
                StateConstant(
                    name=name,
                    value=name,  # For string literals, value equals name
                    data_type="String" if raw_name.startswith('"') else "USInt",
                )
            )

    return states


def _extract_transitions(case_body: str, state_var: str, state_names: set[str]) -> list[StateTransition]:
    """Extract transitions from CASE branches.

    Parameters
    ----------
    case_body : str
        The body of the CASE statement.
    state_var : str
        Name of the state variable.
    state_names : set[str]
        Set of valid state names.

    Returns
    -------
    list[StateTransition]
        Extracted transitions.
    """
    transitions: list[StateTransition] = []

    # Split by case branches to track current state
    # We need a more robust approach: find each branch and its content
    branch_pattern = re.compile(
        r'(#\w+|"[^"]+"):\s*(?:REGION[^\n]*\n)?(.*?)(?=(?:#\w+|"[^"]+"):\s*(?:REGION)?|\s*ELSE\s*|\s*END_CASE)',
        re.DOTALL | re.IGNORECASE,
    )

    for branch_match in branch_pattern.finditer(case_body):
        from_state_raw = branch_match.group(1)
        from_state = _normalize_state_name(from_state_raw)
        branch_content = branch_match.group(2)

        # Find IF transitions within this branch
        for if_match in IF_TRANSITION_PATTERN.finditer(branch_content):
            condition_raw = if_match.group(1).strip()
            assigned_var = if_match.group(2)
            to_state_raw = if_match.group(3)

            # Only capture transitions on the state variable
            if assigned_var == state_var:
                to_state = _normalize_state_name(to_state_raw)

                # Verify this is a valid state
                if to_state in state_names or to_state_raw.startswith('"'):
                    transitions.append(
                        StateTransition(
                            from_state=from_state,
                            to_state=to_state,
                            condition=_simplify_condition(condition_raw),
                            raw_condition=condition_raw,
                        )
                    )

    return transitions


def _normalize_state_name(raw: str) -> str:
    """Normalize state name by removing # prefix and quotes.

    Parameters
    ----------
    raw : str
        Raw state identifier.

    Returns
    -------
    str
        Normalized name.
    """
    return raw.strip().lstrip("#").strip().strip('"').strip()


def _simplify_condition(condition: str) -> str:
    """Simplify condition for diagram display.

    Removes:
    - # prefixes from variables
    - Full DB paths, keeping only the last component
    - Quotes around string values
    - Truncates long conditions

    Parameters
    ----------
    condition : str
        Raw condition expression.

    Returns
    -------
    str
        Simplified condition.
    """
    # Remove # prefixes
    simplified = re.sub(r"#(\w+)", r"\1", condition)

    # Simplify DB paths: "ProcessData".userInput.motionModeSelection -> motionModeSelection
    simplified = re.sub(r'"[^"]+"\.\w+\.(\w+)', r"\1", simplified)

    # Simplify single-level DB paths: "DBName".field -> field
    simplified = re.sub(r'"[^"]+"\.(\w+)', r"\1", simplified)

    # Remove quotes around string values for readability
    simplified = re.sub(r'"(\w+)"', r"\1", simplified)

    # Replace <> operator with != for better readability and to avoid HTML issues
    simplified = simplified.replace("<>", "!=")

    # Ensure spaces around comparison operators
    simplified = re.sub(r"(\w)=(\w)", r"\1 = \2", simplified)
    simplified = re.sub(r"(\w)!=(\w)", r"\1 != \2", simplified)

    # Remove unnecessary outer parentheses around simple conditions
    # Match: ( condition ) where condition has no unbalanced parentheses
    simplified = re.sub(r"^\(\s*([^()]+)\s*\)$", r"\1", simplified.strip())

    # Ensure spaces around AND/OR operators
    # Only match UPPERCASE OR/AND (SCL keywords) to avoid matching "hornAcknowledge"
    # Handle word AND/OR word
    simplified = re.sub(r"(\w)(OR)(\w)", r"\1 \2 \3", simplified)
    simplified = re.sub(r"(\w)(AND)(\w)", r"\1 \2 \3", simplified)
    # Handle cases with space on one side
    simplified = re.sub(r"\s(OR)(\w)", r" \1 \2", simplified)
    simplified = re.sub(r"(\w)(OR)\s", r"\1 \2 ", simplified)
    simplified = re.sub(r"\s(AND)(\w)", r" \1 \2", simplified)
    simplified = re.sub(r"(\w)(AND)\s", r"\1 \2 ", simplified)
    # Handle AND/OR next to parentheses: )AND( or )OR(
    simplified = re.sub(r"\)(AND)\(", r") \1 (", simplified)
    simplified = re.sub(r"\)(OR)\(", r") \1 (", simplified)
    simplified = re.sub(r"\)(AND)(\w)", r") \1 \2", simplified)
    simplified = re.sub(r"\)(OR)(\w)", r") \1 \2", simplified)
    simplified = re.sub(r"(\w)(AND)\(", r"\1 \2 (", simplified)
    simplified = re.sub(r"(\w)(OR)\(", r"\1 \2 (", simplified)
    # Handle spaces already present on one side with parenthesis on the other
    simplified = re.sub(r"\s(AND)\(", r" \1 (", simplified)
    simplified = re.sub(r"\s(OR)\(", r" \1 (", simplified)
    simplified = re.sub(r"\)(AND)\s", r") \1 ", simplified)
    simplified = re.sub(r"\)(OR)\s", r") \1 ", simplified)

    # Clean up extra whitespace (but preserve structure)
    simplified = " ".join(simplified.split())

    # For long conditions, format with line breaks at OR/AND for readability
    # Keep it on one line for Mermaid but use <br> for multi-line display
    # Actually, Mermaid doesn't support <br> in labels well, so just clean up
    # Don't truncate - let the full condition be visible

    return simplified.strip()


def _get_initial_state(state_var: VariableDeclaration, states: list[StateConstant]) -> str | None:
    """Determine the initial state from default value.

    Parameters
    ----------
    state_var : VariableDeclaration
        The state variable.
    states : list[StateConstant]
        List of states.

    Returns
    -------
    str | None
        Initial state name or None.
    """
    if not state_var.default_value:
        # Return first state as default
        return states[0].name if states else None

    # Try to match default value to a state
    try:
        default_int = int(state_var.default_value)
        for state in states:
            if isinstance(state.value, int) and state.value == default_int:
                return state.name
    except ValueError:
        # Default might be a string
        for state in states:
            if state.name == state_var.default_value.strip('"'):
                return state.name

    # Fall back to first state
    return states[0].name if states else None
