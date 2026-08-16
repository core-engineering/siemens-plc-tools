"""Tests for PLCRuntime.block_kind — classify a block name by its declared kind."""

from pathlib import Path

from plc_code.executor.runtime import PLCRuntime

# Self-contained fixtures: KindFb is a FUNCTION_BLOCK, typeKindUdt is a TYPE/UDT.
# (The project-D sibling repo would also work, but is not guaranteed present, so
# we keep the fixture in-tree for a hermetic test.)
FIXTURES = Path(__file__).parent / "fixtures" / "block_kind"
SEARCH = [FIXTURES / "blocks", FIXTURES / "data-types"]


def _runtime():
    return PLCRuntime(block_search_paths=[p for p in SEARCH if p.exists()])


def test_block_kind_function_block():
    assert _runtime().block_kind("KindFb") == "FUNCTION_BLOCK"


def test_block_kind_type():
    assert _runtime().block_kind("typeKindUdt") == "TYPE"


def test_block_kind_unknown_returns_none():
    assert _runtime().block_kind("NoSuchBlock") is None
