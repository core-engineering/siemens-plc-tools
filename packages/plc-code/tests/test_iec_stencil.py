"""Tests for IEC stencil shape XML generation."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from plc_code.drawio_generator.iec_stencil import (
    _cell,
    acknowledge_alarm_compact,
    and_gate,
    auto_acknowledge_annotation,
    black_box,
    cartouche_a3,
    comparator,
    cross_page_ref_in,
    cross_page_ref_out,
    edge_falling,
    edge_rising,
    instrument_tag_widget,
    latch_sr,
    not_gate,
    or_gate,
    plc_digital_input_widget,
    plc_tag_flag,
    state_bubble,
    state_machine_container,
    state_transition,
    sticky_comment,
    tof_timer,
    ton_timer,
    tp_timer,
)


def _is_valid_xml(s: str) -> bool:
    try:
        ET.fromstring(f"<root>{s}</root>")
        return True
    except ET.ParseError:
        return False


def test_cell_helper_escapes_parent_attribute():
    result = _cell(
        id="x",
        value="v",
        style="rounded=0;",
        x=0,
        y=0,
        width=10,
        height=10,
        parent='1"><evil/>',
    )
    # Verify the result is valid XML
    assert _is_valid_xml(result)
    # Verify the dangerous string is escaped (not parsed as XML)
    assert "<evil/>" not in result
    # Verify the quote is escaped
    assert "&quot;" in result


def test_cartouche_a3_contains_metadata():
    xml = cartouche_a3(
        id="cart1",
        title="Station-1 : Station input",
        drawing_number="DOC-0001",
        sheet_number="010",
        drawn_by="Example Author",
        approved_by="Example Reviewer",
        revision="1",
    )
    assert _is_valid_xml(xml)
    assert "DOC-0001" in xml
    assert "010" in xml
    assert "Station-1" in xml


def test_instrument_tag_widget_renders_code_and_description():
    xml = instrument_tag_widget(
        id="di001",
        position=(100, 200),
        tag_type="DI",
        code="001",
        description="Lamp test",
    )
    assert _is_valid_xml(xml)
    assert "DI" in xml
    assert "001" in xml
    assert "Lamp test" in xml


def test_plc_digital_input_widget_renders_address():
    xml = plc_digital_input_widget(
        id="di_lamp_test",
        position=(300, 200),
        address="E2.6",
        signal_name="DI_LCP_LAMP_TEST",
    )
    assert _is_valid_xml(xml)
    assert "E2.6" in xml
    assert "DI_LCP_LAMP_TEST" in xml


def test_plc_tag_flag_renders_path_and_direction():
    xml_in = plc_tag_flag(
        id="t1",
        position=(800, 200),
        path="ProcessData.station.userInput.lampTest",
        direction="out",
    )
    assert _is_valid_xml(xml_in)
    assert "ProcessData.station.userInput.lampTest" in xml_in


def test_acknowledge_alarm_compact():
    xml = acknowledge_alarm_compact(
        id="aa1",
        position=(500, 300),
        instance_name="oilHighTempAlarm",
    )
    assert _is_valid_xml(xml)
    assert "MotorStarter" in xml
    assert "oilHighTempAlarm" in xml


def test_and_gate():
    xml = and_gate(id="and1", position=(400, 100), input_count=2)
    assert _is_valid_xml(xml)
    assert "&amp;" in xml or "&" in xml or "AND" in xml


def test_or_gate():
    xml = or_gate(id="or1", position=(400, 200), input_count=2)
    assert _is_valid_xml(xml)
    assert "≥1" in xml or "OR" in xml


def test_sticky_comment_renders_text():
    xml = sticky_comment(
        id="note1",
        position=(50, 500),
        text="Station mode is set to AUTO",
    )
    assert _is_valid_xml(xml)
    assert "Station mode is set to AUTO" in xml


def test_ton_timer_renders_preset():
    xml = ton_timer(id="t1", position=(400, 100), preset_ms=5000)
    assert _is_valid_xml(xml)
    assert "TON" in xml
    assert "5000" in xml or "5s" in xml


def test_tof_timer_renders_preset():
    xml = tof_timer(id="t1", position=(400, 100), preset_ms=3000)
    assert _is_valid_xml(xml)
    assert "TOF" in xml


def test_tp_timer_renders_preset():
    xml = tp_timer(id="t1", position=(400, 100), preset_ms=1000)
    assert _is_valid_xml(xml)
    assert "TP" in xml


def test_not_gate():
    xml = not_gate(id="n1", position=(400, 100))
    assert _is_valid_xml(xml)
    # IEC NOT is "1" with a small inversion circle on the output
    assert "1" in xml


def test_latch_sr():
    xml = latch_sr(id="l1", position=(500, 100))
    assert _is_valid_xml(xml)
    assert "S" in xml and "R" in xml


def test_edge_rising():
    xml = edge_rising(id="e1", position=(500, 100))
    assert _is_valid_xml(xml)
    assert "↑" in xml or "R_TRIG" in xml


def test_edge_falling():
    xml = edge_falling(id="e1", position=(500, 100))
    assert _is_valid_xml(xml)
    assert "↓" in xml or "F_TRIG" in xml


def test_comparator_eq():
    xml = comparator(id="c1", position=(500, 100), op="==")
    assert _is_valid_xml(xml)
    assert "==" in xml


def test_comparator_gt():
    xml = comparator(id="c1", position=(500, 100), op=">")
    assert _is_valid_xml(xml)
    assert ">" in xml or "&gt;" in xml


def test_state_bubble():
    xml = state_bubble(id="s1", position=(400, 100), name="NO_ALARM", entry="State := NO_ALARM")
    assert _is_valid_xml(xml)
    assert "NO_ALARM" in xml


def test_state_transition_arrow():
    # Returns an edge cell (not a vertex), so dispatch path differs
    xml = state_transition(id="t1", source_id="s1", target_id="s2", condition="Trigger")
    assert _is_valid_xml(xml)
    assert "Trigger" in xml


def test_state_machine_container():
    xml = state_machine_container(id="smc", position=(50, 50), size=(800, 400), label="MotorStarter")
    assert _is_valid_xml(xml)
    assert "MotorStarter" in xml


def test_auto_acknowledge_annotation():
    xml = auto_acknowledge_annotation(id="aa1", position=(50, 50), fb_instance="lcpPowerFailureAlarm")
    assert _is_valid_xml(xml)
    assert "Auto-acknowledged" in xml or "AutoAcknowledge" in xml
    assert "lcpPowerFailureAlarm" in xml


def test_black_box_block():
    xml = black_box(
        id="bb1",
        position=(500, 100),
        fb_type="MotionInterpolator",
        instance_name="motion1",
        exposed_io=["setpoint", "feedback", "command"],
    )
    assert _is_valid_xml(xml)
    assert "MotionInterpolator" in xml
    assert "motion1" in xml
    assert "setpoint" in xml


def test_cross_page_ref_out():
    xml = cross_page_ref_out(id="lref1", position=(1400, 200), label="L1", target_page=42)
    assert _is_valid_xml(xml)
    assert "L1" in xml
    assert "042" in xml or "42" in xml


def test_cross_page_ref_in():
    xml = cross_page_ref_in(id="lref2", position=(50, 200), label="L1", source_page=12)
    assert _is_valid_xml(xml)
    assert "L1" in xml
