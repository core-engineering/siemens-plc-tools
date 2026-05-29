"""Generate Mermaid state diagrams from state machines.

This module provides functionality to generate Mermaid stateDiagram-v2
diagrams from extracted state machine data.
"""

import re

from plc_code.analyzer.state_machine.models import StateMachine


def generate_state_diagram(
    state_machine: StateMachine,
    direction: str = "auto",
    include_initial: bool = True,
) -> str:
    """Generate Mermaid stateDiagram-v2 from state machine.

    Parameters
    ----------
    state_machine : StateMachine
        The extracted state machine.
    direction : str
        Diagram direction: LR (left-right), TB (top-bottom), or "auto"
        to automatically choose based on complexity.
    include_initial : bool
        Whether to include initial state arrow from [*].

    Returns
    -------
    str
        Mermaid stateDiagram code (without fences).
    """
    # Auto-select direction based on complexity
    if direction == "auto":
        # Use TB for complex diagrams (better vertical layout)
        # Use LR for simple diagrams (more compact horizontal)
        if state_machine.state_count > 4 or state_machine.transition_count > 6:
            direction = "TB"
        else:
            direction = "LR"

    lines: list[str] = [
        "stateDiagram-v2",
        f"    direction {direction}",
    ]

    # Add initial state transition
    if include_initial and state_machine.initial_state:
        initial_id = _safe_state_id(state_machine.initial_state)
        lines.append(f"    [*] --> {initial_id}")

    # Add state aliases for names that need escaping
    for state in state_machine.states:
        safe_id = _safe_state_id(state.name)
        # Only add explicit state definition if name needs aliasing
        if safe_id != state.name:
            lines.append(f"    {safe_id} : {state.name}")

    # Add transitions
    seen_transitions: set[tuple[str, str, str]] = set()
    for transition in state_machine.transitions:
        from_id = _safe_state_id(transition.from_state)
        to_id = _safe_state_id(transition.to_state)

        # Deduplicate identical transitions
        key = (from_id, to_id, transition.condition)
        if key in seen_transitions:
            continue
        seen_transitions.add(key)

        # Format transition
        condition = transition.condition
        if condition and condition != "transition":
            escaped_condition = _escape_label(condition)
            lines.append(f"    {from_id} --> {to_id} : {escaped_condition}")
        else:
            lines.append(f"    {from_id} --> {to_id}")

    return "\n".join(lines)


def generate_state_diagram_block(
    state_machine: StateMachine,
    direction: str = "auto",
    include_initial: bool = True,
) -> str:
    """Generate complete Mermaid code block with fences.

    Parameters
    ----------
    state_machine : StateMachine
        The extracted state machine.
    direction : str
        Diagram direction.
    include_initial : bool
        Whether to include initial state arrow.

    Returns
    -------
    str
        Complete Mermaid code block with ``` fences.
    """
    diagram = generate_state_diagram(
        state_machine,
        direction=direction,
        include_initial=include_initial,
    )
    return f"```mermaid\n{diagram}\n```"


def _safe_state_id(name: str) -> str:
    """Convert state name to safe Mermaid identifier.

    Parameters
    ----------
    name : str
        State name.

    Returns
    -------
    str
        Safe identifier (alphanumeric with underscores).
    """
    # Replace non-alphanumeric with underscores
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    # Ensure starts with letter
    if safe and not safe[0].isalpha():
        safe = "S" + safe
    return safe


def _escape_label(text: str) -> str:
    """Escape special characters for Mermaid labels.

    Parameters
    ----------
    text : str
        Label text.

    Returns
    -------
    str
        Escaped text safe for Mermaid.
    """
    # Escape characters that break Mermaid syntax
    text = text.replace('"', "'")
    text = text.replace("\n", " ")
    # Mermaid state diagram labels can't contain certain chars
    text = text.replace(":", "")
    text = text.replace(";", "")

    # Format multi-condition expressions with line breaks for readability
    # Add <br> before AND/OR operators (but not at the start)
    text = re.sub(r"\s+(AND)\s+", r"<br>\1 ", text)
    text = re.sub(r"\s+(OR)\s+", r"<br>\1 ", text)

    # Escape < and > but preserve our <br> tags
    text = text.replace("<br>", "___BR___")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace("___BR___", "<br>")

    return text
