"""Tests for .drawio XML file serialization."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from plc_code.drawio_generator.models import (
    Annotation,
    Block,
    Cartouche,
    Sheet,
)
from plc_code.drawio_generator.xml_writer import write_drawio


def _sample_sheet(num: str = "010", title: str = "Station-1 : Station input") -> Sheet:
    return Sheet(
        sheet_number=num,
        cartouche=Cartouche(
            title=title,
            drawing_number="DOC-0001",
            sheet_number=num,
            drawn_by="Example Author",
            approved_by="Example Reviewer",
            revision="1",
        ),
        blocks=[
            Block(
                id="di001",
                shape="instrument_tag_widget",
                position=(100, 200),
                size=(120, 60),
                properties={"tag_type": "DI", "code": "001", "description": "Lamp test"},
            ),
        ],
        wires=[],
        annotations=[
            Annotation(
                id="note1",
                kind="comment",
                text="Station mode is set to AUTO",
                position=(50, 600),
            ),
        ],
    )


def test_write_drawio_creates_file(tmp_path: Path) -> None:
    out = tmp_path / "station.drawio"
    write_drawio([_sample_sheet()], out)
    assert out.exists()


def test_drawio_xml_is_well_formed(tmp_path: Path) -> None:
    out = tmp_path / "station.drawio"
    write_drawio([_sample_sheet()], out)
    tree = ET.parse(out)
    root = tree.getroot()
    assert root.tag == "mxfile"


def test_drawio_xml_has_one_diagram_per_sheet(tmp_path: Path) -> None:
    out = tmp_path / "multi.drawio"
    sheets = [_sample_sheet("010"), _sample_sheet("011", "Station-2 : Station input")]
    write_drawio(sheets, out)
    tree = ET.parse(out)
    diagrams = tree.findall("diagram")
    assert len(diagrams) == 2


def test_drawio_xml_contains_block_content(tmp_path: Path) -> None:
    out = tmp_path / "station.drawio"
    write_drawio([_sample_sheet()], out)
    content = out.read_text(encoding="utf-8")
    assert "DI" in content
    assert "001" in content
    assert "Station mode is set to AUTO" in content
