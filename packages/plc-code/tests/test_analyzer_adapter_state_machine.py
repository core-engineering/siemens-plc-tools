"""Tests for SM analyzer adapter."""

from __future__ import annotations

from dataclasses import dataclass

from plc_code.drawio_generator.analyzer_adapter.state_machine import (
    SMState,
    SMTransition,
    sm_to_protocol_lists,
)


@dataclass
class _StubConst:
    name: str
    value: str = ""


@dataclass
class _StubTrans:
    from_state: str
    to_state: str
    condition: str


@dataclass
class _StubMachine:
    states: list
    transitions: list


def test_sm_to_protocol_lists_maps_states_and_transitions():
    sm = _StubMachine(
        states=[
            _StubConst(name="IDLE"),
            _StubConst(name="RUNNING"),
            _StubConst(name="FAULT"),
        ],
        transitions=[
            _StubTrans("IDLE", "RUNNING", "start"),
            _StubTrans("RUNNING", "FAULT", "fault_detected"),
            _StubTrans("FAULT", "IDLE", "reset"),
        ],
    )
    states, transitions = sm_to_protocol_lists(sm)
    assert len(states) == 3
    assert states[0].name == "IDLE"
    assert isinstance(states[0], SMState)
    assert len(transitions) == 3
    assert transitions[1].condition == "fault_detected"
    assert isinstance(transitions[1], SMTransition)


def test_sm_to_protocol_lists_handles_empty():
    sm = _StubMachine(states=[], transitions=[])
    states, transitions = sm_to_protocol_lists(sm)
    assert states == []
    assert transitions == []
