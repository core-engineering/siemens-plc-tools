"""LADDER state machine extraction.

This module provides functions to extract state machine information from LADDER
function blocks by parsing EQ_Contact and ConditionalMoveNoSil patterns.
"""

import re

from plc_code.analyzer.state_machine.models import (
    StateConstant,
    StateMachine,
    StateTransition,
)
from plc_code.parser.models import Block, VariableDeclaration

# Regex patterns for LADDER state machine parsing

# Match EQ_Contact(in1 := #var, in2 := #state)
EQ_CONTACT_PATTERN = re.compile(
    r"EQ_Contact\s*\(\s*in1\s*:=\s*#(\w+)\s*,\s*in2\s*:=\s*#(\w+)\s*\)",
    re.IGNORECASE,
)

# Match ConditionalMoveNoSil(condition := wire#w, value := #state, variable := #var)
CONDITIONAL_MOVE_PATTERN = re.compile(
    r'"?ConditionalMoveNoSil"?\s*\(\s*'
    r"condition\s*:=\s*wire#(\w+)\s*,\s*"
    r"value\s*:=\s*#(\w+)\s*,\s*"
    r"variable\s*:=\s*#(\w+)\s*\)",
    re.IGNORECASE | re.DOTALL,
)

# Match Contact(#var) - normal contact (use negative lookbehind to exclude I_Contact)
CONTACT_PATTERN = re.compile(r"(?<!I_)Contact\s*\(\s*#(\w+)\s*\)", re.IGNORECASE)

# Match I_Contact(#var) - inverted contact (NOT)
I_CONTACT_PATTERN = re.compile(r"I_Contact\s*\(\s*#(\w+)\s*\)", re.IGNORECASE)

# Match Contact(#var.Q) - timer output (use negative lookbehind to exclude I_Contact)
TIMER_CONTACT_PATTERN = re.compile(r"(?<!I_)Contact\s*\(\s*#(\w+)\.Q\s*\)", re.IGNORECASE)


def extract_ladder_state_machine(block: Block) -> StateMachine | None:
    """Extract state machine from LADDER block.

    Parameters
    ----------
    block : Block
        Parsed LADDER block.

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

    # Extract states from constants
    constant_vars = find_state_constants(block)
    states = _extract_states_from_constants(constant_vars)
    state_names = {s.name for s in states}

    # Parse networks for transitions
    transitions = _extract_ladder_transitions(block, state_var.name, state_names)

    if not transitions:
        return None

    # Determine initial state
    initial = _get_initial_state(state_var, states)

    return StateMachine(
        state_variable=state_var.name,
        state_type=state_var.data_type,
        states=states,
        transitions=transitions,
        initial_state=initial,
        block_name=block.name,
        language="LAD",
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


def _extract_ladder_transitions(block: Block, state_var: str, state_names: set[str]) -> list[StateTransition]:
    """Extract transitions from LADDER networks.

    LADDER state machines use a pattern where each network can contain:
    - EQ_Contact to check the current state
    - Contact/I_Contact for transition conditions
    - ConditionalMoveNoSil to set the next state

    The parser may split LADDER elements into tokens, so we use both
    regex-based extraction and token-based extraction.

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
        elements = network.ladder_elements
        content = network.content
        if not content.strip() and elements:
            content = "\n".join(elements)

        # Find the state check (EQ_Contact on activeState)
        current_state: str | None = None

        # Method 1: Check individual elements for EQ_Contact pattern
        for elem in elements:
            if "EQ_Contact" in elem:
                match = EQ_CONTACT_PATTERN.search(elem)
                if match:
                    checked_var = match.group(1)
                    checked_value = match.group(2)
                    if checked_var in (state_var, "activeState") and checked_value in state_names:
                        current_state = checked_value
                        break

        # Method 2: Also try regex on combined content
        if not current_state:
            for eq_match in EQ_CONTACT_PATTERN.finditer(content):
                checked_var = eq_match.group(1)
                checked_value = eq_match.group(2)
                if checked_var in (state_var, "activeState") and checked_value in state_names:
                    current_state = checked_value
                    break

        if not current_state:
            continue

        # Collect conditions from Contact and I_Contact
        conditions: list[str] = []

        for elem in elements:
            # Check for Contact pattern
            contact_match = CONTACT_PATTERN.search(elem)
            if contact_match:
                contact_var = contact_match.group(1)
                if contact_var not in state_names and contact_var not in (
                    state_var,
                    "activeState",
                    "calculatedActiveState",
                ):
                    conditions.append(contact_var)

            # Check for timer Contact pattern
            timer_match = TIMER_CONTACT_PATTERN.search(elem)
            if timer_match:
                timer_var = timer_match.group(1)
                conditions.append(f"{timer_var}.Q")

            # Check for I_Contact pattern
            i_contact_match = I_CONTACT_PATTERN.search(elem)
            if i_contact_match:
                contact_var = i_contact_match.group(1)
                if contact_var not in state_names and contact_var not in (
                    state_var,
                    "activeState",
                    "calculatedActiveState",
                ):
                    conditions.append(f"NOT({contact_var})")

        # Find target state - Method 1: Token-based extraction
        # Look for 'value' token followed by state name
        target_state: str | None = None
        for i, elem in enumerate(elements):
            if elem == "value" and i + 1 < len(elements):
                next_elem = elements[i + 1]
                if next_elem in state_names:
                    target_state = next_elem
                    break

        # Method 2: Try regex on content
        if not target_state:
            for move_match in CONDITIONAL_MOVE_PATTERN.finditer(content):
                target_state_val = move_match.group(2)
                target_var = move_match.group(3)
                if target_var in ("calculatedActiveState", state_var):
                    if target_state_val in state_names:
                        target_state = target_state_val
                        break

        # Create transition if we have a valid from/to pair
        if target_state and target_state != current_state:
            condition_str = " AND ".join(conditions) if conditions else "transition"
            transitions.append(
                StateTransition(
                    from_state=current_state,
                    to_state=target_state,
                    condition=_simplify_condition(condition_str),
                    raw_condition=condition_str,
                )
            )

    return transitions


def _simplify_condition(condition: str) -> str:
    """Simplify condition for diagram display.

    Parameters
    ----------
    condition : str
        Raw condition expression.

    Returns
    -------
    str
        Simplified condition.
    """
    # Clean up extra whitespace
    simplified = " ".join(condition.split())

    # Don't truncate - keep full condition visible
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
        pass

    # Fall back to first state
    return states[0].name if states else None
