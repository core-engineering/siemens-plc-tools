"""Tests for the auto-wiring module."""

from __future__ import annotations

from plc_code.drawio_generator.models import Block
from plc_code.drawio_generator.wiring import build_wires_for_sheet


def test_no_blocks_yields_no_wires():
    wires = build_wires_for_sheet(blocks=[], dependencies={})
    assert wires == []


def test_simple_input_to_alarm_chain():
    """Input block → MotorStarter pattern → output flag.

    Given a placed input block and a placed FB-instance alarm block,
    plus a known dependency input→alarm, produce one wire.
    """
    blocks = [
        Block(
            id="in_high_temp",
            shape="instrument_tag_widget",
            position=(100, 200),
            size=(120, 60),
            properties={},
        ),
        Block(
            id="lcp_high_temp_alarm",
            shape="acknowledge_alarm_compact",
            position=(500, 200),
            size=(200, 80),
            properties={},
        ),
    ]
    dependencies = {
        "lcp_high_temp_alarm": ["in_high_temp"],  # alarm reads input
    }
    wires = build_wires_for_sheet(blocks=blocks, dependencies=dependencies)
    assert len(wires) == 1
    assert wires[0].source_id == "in_high_temp"
    assert wires[0].target_id == "lcp_high_temp_alarm"


def test_dependency_for_block_not_on_sheet_is_skipped():
    """If a dependency references a block id not placed on this sheet,
    no wire is created (it's a cross-page concern, handled elsewhere)."""
    blocks = [
        Block(
            id="local_block",
            shape="and_gate",
            position=(100, 200),
            size=(60, 60),
            properties={},
        ),
    ]
    dependencies = {
        "local_block": ["external_unknown_block"],
    }
    wires = build_wires_for_sheet(blocks=blocks, dependencies=dependencies)
    assert wires == []
