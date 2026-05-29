"""Tests for doc-map.yaml Pydantic schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from plc_code.docmap.schema import (
    Chapter,
    DocMap,
    Document,
    FbRendering,
    Page,
)


def test_document_minimal_fields():
    doc = Document(
        title="Example Plant Control Logic",
        drawing_number="DOC-0001",
        revision="1",
        drawn_by="Example Author",
        approved_by="Example Reviewer",
        output_pdf=["process+safety"],
    )
    assert doc.title == "Example Plant Control Logic"
    assert doc.output_pdf == ["process+safety"]


def test_fb_rendering_pattern_requires_definition_page():
    with pytest.raises(ValidationError):
        FbRendering(style="pattern")  # missing definition_page

    fb = FbRendering(style="pattern", definition_page=4)
    assert fb.definition_page == 4


def test_fb_rendering_blackbox_requires_expose():
    with pytest.raises(ValidationError):
        FbRendering(style="black-box")  # missing expose

    fb = FbRendering(style="black-box", expose=["setpoint", "feedback"])
    assert fb.expose == ["setpoint", "feedback"]


def test_block_ref_plain_string():
    # "DI-001" is a valid plain identifier reference
    chapter = Chapter(
        name="Station",
        range=(10, 39),
        source_blocks=["110-Station/Station.s7dcl"],
        pages=[Page(num=10, title="Station input", blocks=["DI-001", "DI-002"])],
    )
    assert chapter.pages[0].blocks == ["DI-001", "DI-002"]


def test_block_ref_structured_with_or_combine():
    page = Page(
        num=41,
        title="Alarms",
        blocks=[
            {"id": "highTempCombined", "inputs": ["DI-004", "DI-005"], "combine": "or"},
            "PWR59",
        ],
    )
    assert page.blocks[0].id == "highTempCombined"
    assert page.blocks[0].combine == "or"
    assert page.blocks[1] == "PWR59"


def test_chapter_range_validation():
    with pytest.raises(ValidationError):
        Chapter(name="Bad", range=(50, 10), source_blocks=[], pages=[])  # inverted


def test_docmap_root():
    dm = DocMap(
        document=Document(
            title="t",
            drawing_number="d",
            revision="1",
            drawn_by="a",
            approved_by="b",
            output_pdf=["process+safety"],
        ),
        fb_rendering={"MotorStarter": FbRendering(style="pattern", definition_page=4)},
        chapters=[],
    )
    assert "MotorStarter" in dm.fb_rendering
