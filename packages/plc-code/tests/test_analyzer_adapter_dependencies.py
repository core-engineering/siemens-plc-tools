"""Tests for the dependency analyzer adapter."""

from __future__ import annotations

from dataclasses import dataclass, field

from plc_code.drawio_generator.analyzer_adapter.dependencies import (
    extract_dependencies,
)


@dataclass
class _StubNode:
    """Minimal DependencyNode-like."""

    name: str
    children: list = field(default_factory=list)


@dataclass
class _StubChain:
    """Minimal DependencyChain-like, with one root node and its tree."""

    root: _StubNode


def test_extract_dependencies_flat_single_chain():
    """Single chain: root depends on two children."""
    chains = [
        _StubChain(
            root=_StubNode(
                name="lcpHighTempAlarm",
                children=[
                    _StubNode(name="hs-102"),
                    _StubNode(name="hs-103"),
                ],
            )
        )
    ]
    page_ids = {"hs-102", "hs-103", "lcpHighTempAlarm"}
    deps = extract_dependencies(chains=chains, page_block_ids=page_ids)
    assert "lcpHighTempAlarm" in deps
    assert set(deps["lcpHighTempAlarm"]) == {"hs-102", "hs-103"}


def test_extract_dependencies_drops_off_page_sources():
    chains = [
        _StubChain(
            root=_StubNode(
                name="lcpHighTempAlarm",
                children=[
                    _StubNode(name="hs-102"),
                    _StubNode(name="hs-999_not_on_page"),
                ],
            )
        )
    ]
    page_ids = {"hs-102", "lcpHighTempAlarm"}
    deps = extract_dependencies(chains=chains, page_block_ids=page_ids)
    assert deps["lcpHighTempAlarm"] == ["hs-102"]


def test_extract_dependencies_drops_off_page_targets():
    chains = [
        _StubChain(
            root=_StubNode(
                name="target_not_on_page",
                children=[
                    _StubNode(name="hs-102"),
                ],
            )
        )
    ]
    page_ids = {"hs-102", "lcpHighTempAlarm"}
    deps = extract_dependencies(chains=chains, page_block_ids=page_ids)
    assert deps == {}


def test_extract_dependencies_handles_nested_children():
    """Children of children should NOT appear in the flat output —
    only direct sources of each target."""
    chains = [
        _StubChain(
            root=_StubNode(
                name="A",
                children=[
                    _StubNode(
                        name="B",
                        children=[
                            _StubNode(name="C"),
                        ],
                    ),
                ],
            )
        )
    ]
    page_ids = {"A", "B", "C"}
    deps = extract_dependencies(chains=chains, page_block_ids=page_ids)
    # A directly depends on B; B directly depends on C; not A on C.
    assert deps == {"A": ["B"], "B": ["C"]}
