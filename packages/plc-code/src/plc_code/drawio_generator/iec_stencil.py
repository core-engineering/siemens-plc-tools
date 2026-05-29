"""MVP shape catalog: produces mxCell XML fragments for Draw.io.

Each function returns a string containing one or more mxCell elements
ready to be embedded inside an mxGraphModel root element.
"""

from __future__ import annotations

from html import escape
from typing import Literal


def _cell(
    id: str,
    value: str,
    style: str,
    x: int,
    y: int,
    width: int,
    height: int,
    parent: str = "1",
) -> str:
    return (
        f'<mxCell id="{escape(id)}" value="{escape(value)}" '
        f'style="{escape(style, quote=True)}" vertex="1" parent="{escape(parent, quote=True)}">'
        f'<mxGeometry x="{x}" y="{y}" width="{width}" height="{height}" as="geometry"/>'
        f"</mxCell>"
    )


def cartouche_a3(
    id: str,
    title: str,
    drawing_number: str,
    sheet_number: str,
    drawn_by: str,
    approved_by: str,
    revision: str,
) -> str:
    """Render the A3 title block at the bottom-right of the sheet.

    Parameters
    ----------
    id:
        Unique cell identifier.
    title:
        Drawing title (e.g. "Chapter-1 : Section title").
    drawing_number:
        Document number (e.g. "DEVICE-001").
    sheet_number:
        Sheet index (e.g. "010").
    drawn_by:
        Author initials/name.
    approved_by:
        Approver initials/name.
    revision:
        Revision string (e.g. "1").

    Returns
    -------
    str
        mxCell XML fragment.
    """
    label = (
        f"<b>{escape(title)}</b><br/>"
        f"DN: {escape(drawing_number)} &nbsp; Sheet: {escape(sheet_number)}<br/>"
        f"Drawn: {escape(drawn_by)} &nbsp; Approved: {escape(approved_by)} &nbsp; "
        f"Rev: {escape(revision)}"
    )
    style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#000000;align=center;"
    return _cell(id, label, style, x=1100, y=1100, width=600, height=80)


def instrument_tag_widget(
    id: str,
    position: tuple[int, int],
    tag_type: str,
    code: str,
    description: str,
) -> str:
    """Render a physical instrument tag widget (HS/PWR/XS/TSH/…).

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    tag_type:
        Instrument type prefix (e.g. "HS", "PWR").
    code:
        Instrument loop number (e.g. "102").
    description:
        Human-readable description (e.g. "Lamp test").

    Returns
    -------
    str
        mxCell XML fragment.
    """
    label = f"<b>{escape(tag_type)} {escape(code)}</b><br/>{escape(description)}"
    style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;align=center;"
    x, y = position
    return _cell(id, label, style, x=x, y=y, width=120, height=60)


def plc_digital_input_widget(
    id: str,
    position: tuple[int, int],
    address: str,
    signal_name: str,
) -> str:
    """Render a PLC digital input widget (address + signal name).

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    address:
        PLC hardware address (e.g. "E2.6").
    signal_name:
        Symbolic tag name (e.g. "DI_PANEL_LAMP_TEST").

    Returns
    -------
    str
        mxCell XML fragment.
    """
    label = f"<b>{escape(address)}</b><br/>{escape(signal_name)}"
    style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#e8f4f8;strokeColor=#4a90b8;align=center;"
    x, y = position
    return _cell(id, label, style, x=x, y=y, width=140, height=50)


def plc_tag_flag(
    id: str,
    position: tuple[int, int],
    path: str,
    direction: Literal["in", "out"],
) -> str:
    """Render a PLC tag flag (input or output banner).

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    path:
        Dotted DB path (e.g. "SectionData.panel.userInput.lampTest").
    direction:
        Data flow direction: "in" for inputs, "out" for outputs.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    fill = "#e8f8e8" if direction == "out" else "#e8f4f8"
    style = (
        f"shape=mxgraph.flowchart.process;rounded=0;whiteSpace=wrap;html=1;"
        f"fillColor={fill};strokeColor=#4a8a4a;align=left;"
    )
    x, y = position
    return _cell(id, path, style, x=x, y=y, width=240, height=30)


def acknowledge_alarm_compact(
    id: str,
    position: tuple[int, int],
    instance_name: str,
) -> str:
    """Render the compact MotorStarter pattern block.

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    instance_name:
        FB instance name (e.g. "oilHighTempAlarm").

    Returns
    -------
    str
        mxCell XML fragment.
    """
    label = (
        f"<b>MotorStarter</b><br/>"
        f"<i>{escape(instance_name)}</i><br/>"
        f"trigger / acknowledge / reset → State"
    )
    style = "rounded=4;whiteSpace=wrap;html=1;fillColor=#fffaf0;strokeColor=#333333;align=center;"
    x, y = position
    return _cell(id, label, style, x=x, y=y, width=200, height=80)


def and_gate(id: str, position: tuple[int, int], input_count: int = 2) -> str:
    """Render an AND gate (IEC ``&``).

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    input_count:
        Number of inputs; controls the gate height.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    label = "<b>&amp;</b>"
    style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;align=center;"
    x, y = position
    return _cell(id, label, style, x=x, y=y, width=60, height=20 * max(input_count, 2) + 20)


def or_gate(id: str, position: tuple[int, int], input_count: int = 2) -> str:
    """Render an OR gate (IEC ``≥1``).

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    input_count:
        Number of inputs; controls the gate height.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    label = "<b>≥1</b>"
    style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;align=center;"
    x, y = position
    return _cell(id, label, style, x=x, y=y, width=60, height=20 * max(input_count, 2) + 20)


def sticky_comment(id: str, position: tuple[int, int], text: str) -> str:
    """Render a green sticky note for design intent.

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    text:
        Comment body text.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    label = f"&lt;&lt;Comment&gt;&gt;<br/>{escape(text)}"
    style = (
        "shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;darkOpacity=0.05;"
        "fillColor=#c8e6c9;strokeColor=#388e3c;align=left;"
    )
    x, y = position
    return _cell(id, label, style, x=x, y=y, width=240, height=70)


def _timer(name: str, id: str, position: tuple[int, int], preset_ms: int) -> str:
    """Internal helper for IEC timer shapes.

    Parameters
    ----------
    name:
        Timer type name (TON, TOF, or TP).
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    preset_ms:
        Preset time in milliseconds.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    seconds = preset_ms / 1000
    label = f"<b>{name}</b><br/>" f"IN ─┐&nbsp;&nbsp; ┌─ Q<br/>" f"PT={escape(f'{seconds:g}s')} ─┤  ├─ ET"
    style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;align=center;"
    x, y = position
    return _cell(id, label, style, x=x, y=y, width=120, height=70)


def ton_timer(id: str, position: tuple[int, int], preset_ms: int) -> str:
    """Render an IEC TON (on-delay) timer.

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    preset_ms:
        Preset time in milliseconds.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    return _timer("TON", id, position, preset_ms)


def tof_timer(id: str, position: tuple[int, int], preset_ms: int) -> str:
    """Render an IEC TOF (off-delay) timer.

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    preset_ms:
        Preset time in milliseconds.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    return _timer("TOF", id, position, preset_ms)


def tp_timer(id: str, position: tuple[int, int], preset_ms: int) -> str:
    """Render an IEC TP (pulse) timer.

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    preset_ms:
        Preset time in milliseconds.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    return _timer("TP", id, position, preset_ms)


def not_gate(id: str, position: tuple[int, int]) -> str:
    """Render an IEC NOT gate (1 with inversion circle on output).

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    label = "<b>1</b>"
    style = (
        "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;"
        "align=center;shape=mxgraph.electrical.logic_gates.gate_not_2;"
    )
    x, y = position
    return _cell(id, label, style, x=x, y=y, width=50, height=40)


def latch_sr(id: str, position: tuple[int, int]) -> str:
    """Render an IEC S/R latch (Set/Reset).

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    label = "<b>S</b><br/>RS<br/><b>R</b>"
    style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;align=center;"
    x, y = position
    return _cell(id, label, style, x=x, y=y, width=60, height=60)


def edge_rising(id: str, position: tuple[int, int]) -> str:
    """Render an IEC R_TRIG rising-edge detector.

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    label = "<b>R_TRIG</b><br/>↑"
    style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;align=center;"
    x, y = position
    return _cell(id, label, style, x=x, y=y, width=70, height=40)


def edge_falling(id: str, position: tuple[int, int]) -> str:
    """Render an IEC F_TRIG falling-edge detector.

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    label = "<b>F_TRIG</b><br/>↓"
    style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;align=center;"
    x, y = position
    return _cell(id, label, style, x=x, y=y, width=70, height=40)


def comparator(
    id: str,
    position: tuple[int, int],
    op: Literal["==", "!=", ">", "<", ">=", "<="],
) -> str:
    """Render a comparator block.

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    op:
        Comparison operator (==, !=, >, <, >=, <=).

    Returns
    -------
    str
        mxCell XML fragment.
    """
    label = f"<b>{escape(op)}</b>"
    style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;align=center;"
    x, y = position
    return _cell(id, label, style, x=x, y=y, width=50, height=40)


def state_bubble(
    id: str,
    position: tuple[int, int],
    name: str,
    entry: str = "",
    do: str = "",
    exit: str = "",
) -> str:
    """Render a state bubble (used inside a state_machine_container).

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    name:
        State name (e.g. "NO_ALARM").
    entry:
        Optional entry action text.
    do:
        Optional do action text.
    exit:
        Optional exit action text.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    actions = ""
    if entry:
        actions += f"<br/>entry / {escape(entry)};"
    if do:
        actions += f"<br/>do / {escape(do)};"
    if exit:
        actions += f"<br/>exit / {escape(exit)};"
    label = f"<b>{escape(name)}</b>{actions}"
    style = "rounded=20;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;" "align=center;"
    x, y = position
    return _cell(id, label, style, x=x, y=y, width=180, height=80)


def state_transition(id: str, source_id: str, target_id: str, condition: str) -> str:
    """Render a state transition arrow (edge cell).

    Parameters
    ----------
    id:
        Unique cell identifier.
    source_id:
        ID of the source state bubble cell.
    target_id:
        ID of the target state bubble cell.
    condition:
        Guard condition / trigger label for the transition.

    Returns
    -------
    str
        mxCell XML fragment (edge, not vertex).
    """
    return (
        f'<mxCell id="{escape(id, quote=True)}" value="{escape(condition, quote=True)}" '
        f'style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=classic;" '
        f'edge="1" source="{escape(source_id, quote=True)}" '
        f'target="{escape(target_id, quote=True)}" parent="1">'
        f'<mxGeometry relative="1" as="geometry"/>'
        f"</mxCell>"
    )


def state_machine_container(id: str, position: tuple[int, int], size: tuple[int, int], label: str) -> str:
    """Render a <<StateMachine>> green container box around an SM diagram.

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    size:
        (width, height) of the container box.
    label:
        State machine name (e.g. "MotorStarter").

    Returns
    -------
    str
        mxCell XML fragment.
    """
    full_label = f"&lt;&lt;StateMachine&gt;&gt; {escape(label)}"
    style = (
        "rounded=4;whiteSpace=wrap;html=1;fillColor=#c8e6c9;strokeColor=#388e3c;"
        "align=left;verticalAlign=top;fillOpacity=30;"
    )
    x, y = position
    w, h = size
    return _cell(id, full_label, style, x=x, y=y, width=w, height=h)


def auto_acknowledge_annotation(id: str, position: tuple[int, int], fb_instance: str) -> str:
    """Render a yellow sticky note marking an FB instance as auto-acknowledged.

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    fb_instance:
        FB instance name to annotate (e.g. "panelPowerFailureAlarm").

    Returns
    -------
    str
        mxCell XML fragment.
    """
    label = (
        f"&lt;&lt;AutoAcknowledge&gt;&gt;<br/>"
        f"<i>{escape(fb_instance)}</i><br/>"
        f"Auto-acknowledged — no operator action required."
    )
    style = (
        "shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;"
        "fillColor=#fff8b8;strokeColor=#bfa800;align=left;"
    )
    x, y = position
    return _cell(id, label, style, x=x, y=y, width=240, height=70)


def black_box(
    id: str,
    position: tuple[int, int],
    fb_type: str,
    instance_name: str,
    exposed_io: list[str],
) -> str:
    """Render an opaque FB block (internal logic not detailed).

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    fb_type:
        Function block type name (e.g. "MotionInterpolator").
    instance_name:
        FB instance name (e.g. "motion1").
    exposed_io:
        List of exposed port names (e.g. ["setpoint", "feedback"]).

    Returns
    -------
    str
        mxCell XML fragment.
    """
    io_list = "<br/>".join(f"• {escape(p)}" for p in exposed_io)
    label = f"<b>[Black-box] {escape(fb_type)}</b><br/>" f"<i>{escape(instance_name)}</i><br/>" f"{io_list}"
    style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#eeeeee;strokeColor=#666666;" "align=left;dashed=1;"
    x, y = position
    return _cell(id, label, style, x=x, y=y, width=220, height=20 + 18 * (3 + len(exposed_io)))


def cross_page_ref_out(id: str, position: tuple[int, int], label: str, target_page: int) -> str:
    """Render a cross-page reference exit marker (e.g. '→ L1 (page 042)').

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    label:
        Signal label (e.g. "L1").
    target_page:
        Destination page number (zero-padded to 3 digits in the label).

    Returns
    -------
    str
        mxCell XML fragment.
    """
    full_label = f"→ <b>{escape(label)}</b> (page {target_page:03d})"
    style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#888888;" "align=left;dashed=0;"
    x, y = position
    return _cell(id, full_label, style, x=x, y=y, width=160, height=24)


def cross_page_ref_in(id: str, position: tuple[int, int], label: str, source_page: int) -> str:
    """Render a cross-page reference entry marker (e.g. 'L1 (from page 012) →').

    Parameters
    ----------
    id:
        Unique cell identifier.
    position:
        (x, y) coordinates in the diagram.
    label:
        Signal label (e.g. "L1").
    source_page:
        Origin page number (zero-padded to 3 digits in the label).

    Returns
    -------
    str
        mxCell XML fragment.
    """
    full_label = f"<b>{escape(label)}</b> (from page {source_page:03d}) →"
    style = "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#888888;" "align=right;dashed=0;"
    x, y = position
    return _cell(id, full_label, style, x=x, y=y, width=160, height=24)
