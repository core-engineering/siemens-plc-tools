"""Tests for the page builder (doc-map page → render Sheet)."""

from __future__ import annotations

from pathlib import Path

import pytest

from plc_code.docmap.resolver import Resolver
from plc_code.docmap.schema import Document, Page
from plc_code.drawio_generator.page_builder import (
    _parse_instrument_id,
    _short_description,
    build_sheet,
)


def _doc() -> Document:
    return Document(
        title="Example Plant",
        drawing_number="DOC-0001",
        revision="1",
        drawn_by="Example Author",
        approved_by="Example Reviewer",
        output_pdf=["process+safety"],
    )


def test_build_sheet_assigns_cartouche_fields(simple_xml_tags_dir: Path):
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=None)
    page = Page(num=10, title="Station input", blocks=["DI-001"], comments=[])
    sheet = build_sheet(page=page, document=_doc(), resolver=resolver, chapter_name="Station")
    assert sheet.cartouche.title == "Station-1 : Station input"
    assert sheet.cartouche.sheet_number == "010"
    assert sheet.cartouche.drawing_number == "DOC-0001"


def test_build_sheet_places_instrument_tags_in_left_column(simple_xml_tags_dir: Path):
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=None)
    page = Page(num=10, title="Station input", blocks=["DI-001", "DI-002"], comments=[])
    sheet = build_sheet(page=page, document=_doc(), resolver=resolver, chapter_name="Station")
    assert len(sheet.blocks) == 2
    # Both placed in the left column (low x)
    xs = sorted(b.position[0] for b in sheet.blocks)
    assert all(x < 400 for x in xs)
    # Stacked vertically
    ys = sorted(b.position[1] for b in sheet.blocks)
    assert ys[1] - ys[0] >= 60  # at least one widget height apart


def test_build_sheet_renders_comments_as_sticky_notes(simple_xml_tags_dir: Path):
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=None)
    page = Page(
        num=10,
        title="Station input",
        blocks=["DI-001"],
        comments=["Station mode is set to AUTO", "Station is always active"],
    )
    sheet = build_sheet(page=page, document=_doc(), resolver=resolver, chapter_name="Station")
    assert len(sheet.annotations) == 2
    assert sheet.annotations[0].kind == "comment"
    assert "AUTO" in sheet.annotations[0].text


def test_build_sheet_assigns_section_number_from_page_order(simple_xml_tags_dir: Path):
    """The {N} in {Subsystem}-{N} is the page index within the chapter (1-based)."""
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=None)
    page = Page(num=12, title="Station input", blocks=["DI-001"], comments=[])
    sheet = build_sheet(
        page=page,
        document=_doc(),
        resolver=resolver,
        chapter_name="Station",
        section_number=3,
    )
    assert sheet.cartouche.title == "Station-3 : Station input"


# ---------------------------------------------------------------------------
# Unit tests for _parse_instrument_id (Fix 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "identifier, expected",
    [
        ("DI-6020A", ("DI", "6020A")),
        ("DI-6020B", ("DI", "6020B")),
        ("AIH-55", ("AIH", "55")),
        ("DI102", ("DI", "102")),
        ("DI-6020L1", ("DI", "6020L1")),
        # Edge case: no digits at all — all-alpha collapses to (letters, empty)
        # The regex requires at least one char in group 2, so "WEIRD" → ('?', 'WEIRD')
        ("WEIRD", ("?", "WEIRD")),
    ],
)
def test_parse_instrument_id(identifier: str, expected: tuple[str, str]) -> None:
    assert _parse_instrument_id(identifier) == expected


# ---------------------------------------------------------------------------
# Unit tests for _short_description (Fix 1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "metadata, expected",
    [
        # Typical case: project-prefixed comment → strip prefix
        ({"comment": "021-DI-6070", "data_type": "Bool"}, "DI-6070"),
        # Comment already without prefix → returned as-is
        ({"comment": "DI-6070", "data_type": "Bool"}, "DI-6070"),
        # Empty comment → fall back to data_type
        ({"comment": "", "data_type": "Bool"}, "Bool"),
        # No comment key → fall back to data_type
        ({"data_type": "Bool"}, "Bool"),
        # Nothing → empty string
        ({}, ""),
    ],
)
def test_short_description(metadata: dict[str, str], expected: str) -> None:
    assert _short_description(metadata) == expected


# ---------------------------------------------------------------------------
# Regression test: description must be non-empty for DI-001 (Fix 1 × Fix 2)
# ---------------------------------------------------------------------------


def test_build_sheet_description_non_empty_for_hs102(simple_xml_tags_dir: Path) -> None:
    """Regression: block description was always '' because 'Datatype' key didn't exist."""
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=None)
    page = Page(num=10, title="Station input", blocks=["DI-001"], comments=[])
    sheet = build_sheet(page=page, document=_doc(), resolver=resolver, chapter_name="Station")
    block = sheet.blocks[0]
    assert (
        block.properties["description"] != ""
    ), "description must not be empty — check metadata['comment'] lookup"
    # Also verify tag_type is not garbled (Fix 2)
    assert block.properties["tag_type"] == "DI"
    assert block.properties["code"] == "001"


# ---------------------------------------------------------------------------
# Task 7: FB rendering modes — pattern / black-box / inline
# ---------------------------------------------------------------------------


def test_pattern_mode_produces_compact_block(simple_xml_tags_dir: Path, simple_scl_dir: Path) -> None:
    from plc_code.docmap.schema import FbRendering

    fb_rendering = {"MotorStarter": FbRendering(style="pattern", definition_page=4)}
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=simple_scl_dir)
    page = Page(num=41, title="Alarms", blocks=["motorStartCmd"], comments=[])
    sheet = build_sheet(
        page=page,
        document=_doc(),
        resolver=resolver,
        chapter_name="PumpControl",
        section_number=2,
        fb_rendering=fb_rendering,
    )
    assert len(sheet.blocks) == 1
    assert sheet.blocks[0].shape == "acknowledge_alarm_compact"
    assert sheet.blocks[0].properties.get("instance_name") == "motorStartCmd"


def test_black_box_mode_produces_opaque_block(simple_xml_tags_dir: Path, simple_scl_dir: Path) -> None:
    from plc_code.docmap.schema import FbRendering

    fb_rendering = {
        "MotorStarter": FbRendering(style="black-box", expose=["Trigger", "Acknowledge", "Reset"])
    }
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=simple_scl_dir)
    page = Page(num=41, title="Alarms", blocks=["motorStartCmd"], comments=[])
    sheet = build_sheet(
        page=page,
        document=_doc(),
        resolver=resolver,
        chapter_name="PumpControl",
        section_number=2,
        fb_rendering=fb_rendering,
    )
    assert sheet.blocks[0].shape == "black_box"
    # Properties values are dict[str, str]; exposed_io serialized as comma-joined
    assert "Trigger" in sheet.blocks[0].properties.get("exposed_io", "")


def test_inline_mode_falls_back_to_placeholder(simple_xml_tags_dir: Path, simple_scl_dir: Path) -> None:
    """Inline mode for an FB instance (default if FB type missing from fb_rendering)
    produces a placeholder block — full inline expansion is Plan 2B."""
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=simple_scl_dir)
    page = Page(num=41, title="Alarms", blocks=["motorStartCmd"], comments=[])
    sheet = build_sheet(
        page=page,
        document=_doc(),
        resolver=resolver,
        chapter_name="PumpControl",
        section_number=2,
        # no fb_rendering → defaults to inline
    )
    assert len(sheet.blocks) == 1
    # Just verify it's some kind of placeholder (existing or new shape).
    assert sheet.blocks[0].id == "motorStartCmd"


def test_auto_acknowledge_annotation_emitted_for_marked_instance(
    simple_xml_tags_dir: Path, simple_scl_dir: Path
) -> None:
    """When a StructuredBlockRef has annotation='auto_acknowledge',
    an Annotation(kind='auto_acknowledge') is added to the sheet."""
    from plc_code.docmap.schema import FbRendering, StructuredBlockRef

    fb_rendering = {"MotorStarter": FbRendering(style="pattern", definition_page=4)}
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=simple_scl_dir)
    page = Page(
        num=41,
        title="Alarms",
        blocks=[
            StructuredBlockRef(
                id="pumpFaultGroup",
                inputs=["pumpFaultAlarm"],
                annotation="auto_acknowledge",
            )
        ],
        comments=[],
    )
    sheet = build_sheet(
        page=page,
        document=_doc(),
        resolver=resolver,
        chapter_name="PumpControl",
        section_number=2,
        fb_rendering=fb_rendering,
    )
    # At least one annotation of kind="auto_acknowledge"
    auto_acks = [a for a in sheet.annotations if a.kind == "auto_acknowledge"]
    assert len(auto_acks) >= 1
    # The annotation references the inputs (or the structured ref id)
    assert "pumpFaultAlarm" in auto_acks[0].text or "pumpFaultGroup" in auto_acks[0].text


# ---------------------------------------------------------------------------
# Task 9: Auto-wiring integration tests
# ---------------------------------------------------------------------------


def test_build_sheet_auto_wires_blocks_when_dependencies_provided(
    simple_xml_tags_dir: Path, simple_scl_dir: Path
) -> None:
    """When dependencies are provided, build_sheet auto-wires blocks."""
    from plc_code.docmap.schema import FbRendering

    fb_rendering = {"MotorStarter": FbRendering(style="pattern", definition_page=4)}
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=simple_scl_dir)
    page = Page(
        num=41,
        title="Alarms",
        blocks=["DI-001", "motorStartCmd"],
        comments=[],
    )
    # Map target id to its source dependencies.
    # Instrument tags use .lower() (e.g. "di-001"), FB instances preserve id.
    deps = {"motorStartCmd": ["di-001"]}
    sheet = build_sheet(
        page=page,
        document=_doc(),
        resolver=resolver,
        chapter_name="PumpControl",
        section_number=2,
        fb_rendering=fb_rendering,
        dependencies=deps,
    )
    assert len(sheet.wires) == 1
    assert sheet.wires[0].source_id == "di-001"
    assert sheet.wires[0].target_id == "motorStartCmd"


def test_build_sheet_no_wires_when_dependencies_not_provided(
    simple_xml_tags_dir: Path,
) -> None:
    """When dependencies are not provided, no wires are generated."""
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=None)
    page = Page(num=10, title="Station input", blocks=["DI-001"], comments=[])
    sheet = build_sheet(page=page, document=_doc(), resolver=resolver, chapter_name="Station")
    assert sheet.wires == []
