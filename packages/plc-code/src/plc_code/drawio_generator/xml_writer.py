"""Serialize Sheet objects into a .drawio file (mxGraph XML format)."""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from pathlib import Path

from plc_code.drawio_generator import iec_stencil
from plc_code.drawio_generator.models import Annotation, Block, Sheet, Wire

_SHAPE_DISPATCH: dict[str, Callable[..., str]] = {
    "instrument_tag_widget": iec_stencil.instrument_tag_widget,
    "plc_digital_input_widget": iec_stencil.plc_digital_input_widget,
    "plc_tag_flag": iec_stencil.plc_tag_flag,
    "acknowledge_alarm_compact": iec_stencil.acknowledge_alarm_compact,
    "and_gate": iec_stencil.and_gate,
    "or_gate": iec_stencil.or_gate,
    "ton_timer": iec_stencil.ton_timer,
    "tof_timer": iec_stencil.tof_timer,
    "tp_timer": iec_stencil.tp_timer,
    "not_gate": iec_stencil.not_gate,
    "latch_sr": iec_stencil.latch_sr,
    "edge_rising": iec_stencil.edge_rising,
    "edge_falling": iec_stencil.edge_falling,
    "comparator": iec_stencil.comparator,
    "state_bubble": iec_stencil.state_bubble,
    "state_machine_container": iec_stencil.state_machine_container,
    "auto_acknowledge_annotation": iec_stencil.auto_acknowledge_annotation,
    "black_box": iec_stencil.black_box,
    "cross_page_ref_out": iec_stencil.cross_page_ref_out,
    "cross_page_ref_in": iec_stencil.cross_page_ref_in,
}


def _render_block(block: Block) -> str:
    """Render a Block as an mxCell XML fragment.

    Parameters
    ----------
    block : Block
        The block to render.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    factory = _SHAPE_DISPATCH.get(block.shape)
    if factory is None:
        # Fallback: render as a labeled rectangle
        label = f"[{block.shape}] {block.id}"
        return (
            f'<mxCell id="{escape(block.id)}" value="{escape(label)}" '
            f'style="rounded=0;whiteSpace=wrap;html=1;" vertex="1" parent="1">'
            f'<mxGeometry x="{block.position[0]}" y="{block.position[1]}" '
            f'width="{block.size[0]}" height="{block.size[1]}" as="geometry"/>'
            f"</mxCell>"
        )
    # black_box stores exposed_io as a comma-joined string in Block.properties
    # (Block.properties is dict[str, str]) — split back to list before calling factory.
    if block.shape == "black_box":
        props = dict(block.properties)
        exposed_str = props.pop("exposed_io", "")
        exposed_list = [s.strip() for s in exposed_str.split(",") if s.strip()]
        return factory(id=block.id, position=block.position, exposed_io=exposed_list, **props)
    # state_machine_container requires size (width × height of the bounding box).
    if block.shape == "state_machine_container":
        return factory(id=block.id, position=block.position, size=block.size, **block.properties)
    return factory(id=block.id, position=block.position, **block.properties)


def _render_wire(wire: Wire) -> str:
    """Render a Wire as an mxCell edge XML fragment.

    Parameters
    ----------
    wire : Wire
        The wire to render.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    return (
        f'<mxCell id="{escape(wire.id)}" value="{escape(wire.label)}" '
        f'style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;" edge="1" '
        f'source="{escape(wire.source_id)}" target="{escape(wire.target_id)}" parent="1">'
        f'<mxGeometry relative="1" as="geometry"/>'
        f"</mxCell>"
    )


def _render_annotation(ann: Annotation) -> str:
    """Render an Annotation as an mxCell XML fragment.

    Parameters
    ----------
    ann : Annotation
        The annotation to render.

    Returns
    -------
    str
        mxCell XML fragment.
    """
    if ann.kind == "auto_acknowledge":
        return iec_stencil.auto_acknowledge_annotation(id=ann.id, position=ann.position, fb_instance=ann.text)
    # comment (and any other kind) → sticky comment fallback
    return iec_stencil.sticky_comment(id=ann.id, position=ann.position, text=ann.text)


def _render_sheet_diagram(sheet: Sheet) -> str:
    """Render a single Sheet as a ``<diagram>`` XML element.

    Parameters
    ----------
    sheet : Sheet
        The sheet to render.

    Returns
    -------
    str
        ``<diagram>…</diagram>`` XML string ready for embedding in an mxfile.
    """
    cells: list[str] = [
        '<mxCell id="0"/>',
        '<mxCell id="1" parent="0"/>',
    ]
    cells.append(
        iec_stencil.cartouche_a3(
            id=f"cart_{sheet.sheet_number}",
            title=sheet.cartouche.title,
            drawing_number=sheet.cartouche.drawing_number,
            sheet_number=sheet.cartouche.sheet_number,
            drawn_by=sheet.cartouche.drawn_by,
            approved_by=sheet.cartouche.approved_by,
            revision=sheet.cartouche.revision,
        )
    )
    cells.extend(_render_block(b) for b in sheet.blocks)
    cells.extend(_render_wire(w) for w in sheet.wires)
    cells.extend(_render_annotation(a) for a in sheet.annotations)
    return (
        f'<diagram id="sheet_{sheet.sheet_number}" name="{sheet.sheet_number} - '
        f'{escape(sheet.cartouche.title)}">'
        f"<mxGraphModel dx='1681' dy='800' grid='1' gridSize='10' guides='1' "
        f"tooltips='1' connect='1' arrows='1' fold='1' page='1' pageScale='1' "
        f"pageWidth='1684' pageHeight='1190' math='0' shadow='0'>"
        f"<root>{''.join(cells)}</root>"
        f"</mxGraphModel></diagram>"
    )


def write_drawio(sheets: list[Sheet], output_path: Path | str) -> None:
    """Write a sequence of sheets to a single .drawio file.

    Parameters
    ----------
    sheets : list[Sheet]
        Sheets to render, in order.
    output_path : Path or str
        Destination file path.
    """
    output_path = Path(output_path)
    diagrams = "".join(_render_sheet_diagram(s) for s in sheets)
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<mxfile host="plc-code-generator" type="device">'
        f"{diagrams}"
        "</mxfile>"
    )
    output_path.write_text(content, encoding="utf-8")
