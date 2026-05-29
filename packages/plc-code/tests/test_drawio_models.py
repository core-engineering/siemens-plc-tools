"""Tests for drawio_generator render IR dataclasses."""

from __future__ import annotations

from plc_code.drawio_generator.models import (
    Annotation,
    Block,
    Cartouche,
    Sheet,
    Wire,
)


def test_block_construction():
    b = Block(
        id="di001",
        shape="instrument_tag",
        position=(100, 200),
        size=(120, 80),
        properties={"tag_type": "DI", "code": "001", "description": "Lamp test"},
    )
    assert b.id == "di001"
    assert b.position == (100, 200)


def test_wire_construction():
    w = Wire(id="w1", source_id="b1", target_id="b2", label="DI_LAMP_TEST")
    assert w.source_id == "b1"
    assert w.target_id == "b2"


def test_annotation_construction():
    a = Annotation(
        id="note1",
        kind="comment",
        text="Station mode is set to AUTO",
        position=(50, 600),
    )
    assert a.kind == "comment"


def test_cartouche_construction():
    c = Cartouche(
        title="Station-1 : Station input",
        drawing_number="DOC-0001",
        sheet_number="010",
        drawn_by="Example Author",
        approved_by="Example Reviewer",
        revision="1",
    )
    assert c.sheet_number == "010"


def test_sheet_aggregates_blocks_wires_annotations():
    sheet = Sheet(
        sheet_number="010",
        cartouche=Cartouche(
            title="Station-1 : Station input",
            drawing_number="DOC-0001",
            sheet_number="010",
            drawn_by="Example Author",
            approved_by="Example Reviewer",
            revision="1",
        ),
        blocks=[Block(id="b1", shape="and", position=(0, 0), size=(60, 60), properties={})],
        wires=[Wire(id="w1", source_id="b1", target_id="b2", label="")],
        annotations=[Annotation(id="n1", kind="comment", text="hello", position=(0, 0))],
    )
    assert len(sheet.blocks) == 1
    assert len(sheet.wires) == 1
    assert len(sheet.annotations) == 1
