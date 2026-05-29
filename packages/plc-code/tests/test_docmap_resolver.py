"""Tests for resolving doc-map block refs against SCL/tag sources."""

from __future__ import annotations

from pathlib import Path

import pytest

from plc_code.docmap.resolver import (
    ResolutionError,
    ResolvedBlock,
    Resolver,
)


def test_resolve_instrument_tag(simple_xml_tags_dir: Path):
    """Resolve by instrument tag form (bare, without project prefix)."""
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=None)
    resolved = resolver.resolve("DI-001")
    assert isinstance(resolved, ResolvedBlock)
    assert resolved.kind == "instrument_tag"
    assert resolved.identifier == "DI-001"
    assert resolved.metadata["plc_name"] == "DI_LCP_LAMP_TEST"
    assert resolved.metadata["address"] == "%E2.6"


def test_resolve_instrument_tag_with_project_prefix(simple_xml_tags_dir: Path):
    """Resolve by instrument tag form including project prefix (010-DI-001)."""
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=None)
    resolved = resolver.resolve("010-DI-001")
    assert resolved.kind == "instrument_tag"
    assert resolved.identifier == "010-DI-001"
    assert resolved.metadata["plc_name"] == "DI_LCP_LAMP_TEST"


def test_resolve_by_plc_tag_name(simple_xml_tags_dir: Path):
    """Resolve by exact PLC tag name (DI_LCP_LAMP_TEST)."""
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=None)
    resolved = resolver.resolve("DI_LCP_LAMP_TEST")
    assert resolved.kind == "instrument_tag"
    assert resolved.identifier == "DI_LCP_LAMP_TEST"
    assert resolved.metadata["plc_name"] == "DI_LCP_LAMP_TEST"
    assert resolved.metadata["comment"] == "010-DI-001"


def test_resolve_unknown_raises():
    resolver = Resolver(xml_tags_dir=None, scl_dir=None)
    with pytest.raises(ResolutionError) as exc:
        resolver.resolve("UNKNOWN_BLOCK")
    assert "UNKNOWN_BLOCK" in str(exc.value)


def test_resolve_structured_block_with_inputs(simple_xml_tags_dir: Path):
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=None)
    structured = {"id": "highTempCombined", "inputs": ["DI-004", "DI-005"], "combine": "or"}
    resolved = resolver.resolve(structured)
    assert resolved.kind == "combined"
    assert len(resolved.children) == 2
    assert resolved.combine == "or"
    assert resolved.children[0].metadata["plc_name"] == "DI_LCP_HIGH_TEMP1"
    assert resolved.children[1].metadata["plc_name"] == "DI_LCP_HIGH_TEMP2"


def test_resolve_fb_instance(simple_xml_tags_dir: Path, simple_scl_dir: Path):
    """Quoted declaration ``instanceName : "FbType";`` is resolved correctly."""
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=simple_scl_dir)
    resolved = resolver.resolve("motorStartCmd")
    assert resolved.kind == "fb_instance"
    assert resolved.identifier == "motorStartCmd"
    assert resolved.metadata.get("fb_type") == "MotorStarter"
    assert resolved.metadata.get("parent_block") == "PumpControl"


def test_resolve_fb_instance_library_ref(simple_xml_tags_dir: Path, simple_scl_dir: Path):
    """Library-reference declaration ``instanceName : _.FbType;`` is resolved correctly.

    The library-ref form ``_.MotorStarter`` — the resolver must extract the FB
    type name without the leading ``_.`` prefix.
    """
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=simple_scl_dir)
    resolved = resolver.resolve("pumpFaultAlarm")
    assert resolved.kind == "fb_instance"
    assert resolved.identifier == "pumpFaultAlarm"
    assert resolved.metadata.get("fb_type") == "MotorStarter"
    assert resolved.metadata.get("parent_block") == "PumpControl"


def test_resolve_prefers_instrument_tag_over_fb_when_both_exist(
    simple_xml_tags_dir: Path, simple_scl_dir: Path
):
    """If a name resolves to both an instrument tag and an FB instance,
    instrument tag wins (more specific, has hardware mapping)."""
    # DI-001 is an instrument tag; we won't have an FB with the same name
    # in the fixture, but the test documents the precedence rule.
    resolver = Resolver(xml_tags_dir=simple_xml_tags_dir, scl_dir=simple_scl_dir)
    resolved = resolver.resolve("DI-001")
    assert resolved.kind == "instrument_tag"
