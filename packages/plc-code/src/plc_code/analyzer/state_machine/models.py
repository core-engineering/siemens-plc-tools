"""Data models for state machine representation.

This module defines the dataclasses used to represent state machines
extracted from SCL and LADDER function blocks.
"""

from dataclasses import dataclass, field


@dataclass
class StateConstant:
    """A state constant defined in VAR CONSTANT section.

    Attributes
    ----------
    name : str
        Constant name (e.g., "NO_ALARM", "ERS_AUTHORIZED").
    value : int | str
        Numeric or string value.
    data_type : str
        Data type (USInt, Int, etc.).
    description : str
        MLC-resolved description if available.
    """

    name: str
    value: int | str
    data_type: str = ""
    description: str = ""


@dataclass
class StateTransition:
    """A transition between two states.

    Attributes
    ----------
    from_state : str
        Source state name.
    to_state : str
        Target state name.
    condition : str
        Transition condition (simplified for display).
    raw_condition : str
        Original condition text from source.
    """

    from_state: str
    to_state: str
    condition: str
    raw_condition: str = ""


@dataclass
class StateMachine:
    """Complete state machine extracted from a block.

    Attributes
    ----------
    state_variable : str
        Name of the state variable (e.g., "activeState").
    state_type : str
        Data type of state variable (USInt, Int).
    states : list[StateConstant]
        All defined states.
    transitions : list[StateTransition]
        All transitions between states.
    initial_state : str | None
        Initial state (from default value or first in list).
    block_name : str
        Name of the containing block.
    language : str
        Source language (SCL or LAD).
    """

    state_variable: str
    state_type: str
    states: list[StateConstant] = field(default_factory=list)
    transitions: list[StateTransition] = field(default_factory=list)
    initial_state: str | None = None
    block_name: str = ""
    language: str = "SCL"

    @property
    def state_names(self) -> list[str]:
        """Get list of state names."""
        return [s.name for s in self.states]

    @property
    def state_count(self) -> int:
        """Get number of states."""
        return len(self.states)

    @property
    def transition_count(self) -> int:
        """Get number of transitions."""
        return len(self.transitions)

    def get_transitions_from(self, state: str) -> list[StateTransition]:
        """Get all transitions from a given state.

        Parameters
        ----------
        state : str
            The source state name.

        Returns
        -------
        list[StateTransition]
            Transitions originating from this state.
        """
        return [t for t in self.transitions if t.from_state == state]

    def get_transitions_to(self, state: str) -> list[StateTransition]:
        """Get all transitions to a given state.

        Parameters
        ----------
        state : str
            The target state name.

        Returns
        -------
        list[StateTransition]
            Transitions ending at this state.
        """
        return [t for t in self.transitions if t.to_state == state]
