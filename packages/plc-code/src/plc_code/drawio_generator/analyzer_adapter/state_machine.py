"""Adapter: analyzer.state_machine.StateMachine → state_machine_page Protocols."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class _StateMachineLike(Protocol):
    """Protocol for state machine objects compatible with extraction."""

    states: list
    transitions: list


@dataclass
class SMState:
    """State node (satisfies state_machine_page._StateLike Protocol).

    Attributes
    ----------
    name : str
        State name.
    entry : str
        Entry action/assignment.
    do : str
        Continuous action/assignment.
    exit : str
        Exit action/assignment.
    """

    name: str
    entry: str = ""
    do: str = ""
    exit: str = ""


@dataclass
class SMTransition:
    """Transition edge (satisfies state_machine_page._TransitionLike Protocol).

    Attributes
    ----------
    from_state : str
        Source state name.
    to_state : str
        Target state name.
    condition : str
        Transition condition.
    """

    from_state: str
    to_state: str
    condition: str


def sm_to_protocol_lists(
    sm: _StateMachineLike,
) -> tuple[list[SMState], list[SMTransition]]:
    """Convert an analyzer.state_machine.StateMachine to the Protocol lists
    accepted by state_machine_page.build_state_machine_sheet.

    Parameters
    ----------
    sm : analyzer.state_machine.models.StateMachine
        The extracted SM with states and transitions.

    Returns
    -------
    tuple[list[SMState], list[SMTransition]]
        Tuple of (states list, transitions list) ready for sheet building.
    """
    states = [SMState(name=s.name, entry=f"State := {s.name}") for s in sm.states]
    transitions = [
        SMTransition(from_state=t.from_state, to_state=t.to_state, condition=t.condition)
        for t in sm.transitions
    ]
    return states, transitions
