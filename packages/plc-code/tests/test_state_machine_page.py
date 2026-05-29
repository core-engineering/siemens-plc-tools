"""Tests for state-machine page generator."""

from __future__ import annotations

from dataclasses import dataclass

from plc_code.docmap.schema import Document
from plc_code.drawio_generator.state_machine_page import build_state_machine_sheet


@dataclass
class _StubState:
    name: str
    entry: str = ""
    do: str = ""
    exit: str = ""


@dataclass
class _StubTransition:
    from_state: str
    to_state: str
    condition: str


def _doc() -> Document:
    return Document(
        title="Example Plant",
        drawing_number="DOC-0001",
        revision="1",
        drawn_by="Example Author",
        approved_by="Example Reviewer",
        output_pdf=["process+safety"],
    )


def test_build_state_machine_sheet_has_one_bubble_per_state():
    states = [
        _StubState(name="NO_ALARM", entry="State := NO_ALARM"),
        _StubState(name="ALARM", entry="State := ALARM"),
        _StubState(name="ALARM_ACKNOWLEDGE", entry="State := ALARM_ACKNOWLEDGE"),
    ]
    transitions = [
        _StubTransition("NO_ALARM", "ALARM", "Trigger"),
        _StubTransition("ALARM", "ALARM_ACKNOWLEDGE", "Acknowledge"),
        _StubTransition("ALARM_ACKNOWLEDGE", "NO_ALARM", "Reset AND NOT(Trigger)"),
    ]
    sheet = build_state_machine_sheet(
        page_num=4,
        title="MotorStarter",
        document=_doc(),
        states=states,
        transitions=transitions,
    )
    assert sheet.sheet_number == "004"
    # 1 container + 3 bubbles + 3 transitions
    assert len(sheet.blocks) == 4  # container + 3 bubbles (transitions are wires)
    assert len(sheet.wires) == 3


def test_build_state_machine_sheet_cartouche_title():
    states = [_StubState(name="ONLY_STATE")]
    transitions: list[_StubTransition] = []
    sheet = build_state_machine_sheet(
        page_num=5,
        title="Selector",
        document=_doc(),
        states=states,
        transitions=transitions,
    )
    assert "Selector" in sheet.cartouche.title
    assert sheet.cartouche.sheet_number == "005"
