"""Every shipped fixture must parse with zero errors and no silent token loss.

Same role as ``test_diagnostics_corpus.py`` plays for the diagnostics: a
statement parser that cannot read the toolchain's own examples is not ready
to measure anything else. There is no ``KNOWN_DEFECTS`` escape hatch here on
purpose — a fixture in this directory is a block the toolchain is expected to
handle.

Traversal is top-level regions only (``block.networks[*].regions``), not a
recursive descent into ``region.nested_regions``: a region's ``tokens``
already includes every token of its nested regions (verified directly on
``PumpControl.s7dcl`` — the top-level region's 201 tokens contain its
children's 174 verbatim), so descending would parse the same tokens twice
under two different names and double-count both regions and statements.

The invariant checked here is the strong, span-based one from
``verify_no_silent_loss`` (Task 7), not ``consumed_tokens``: the cursor
always reaches the end of the stream by loop construction, so
``consumed_tokens == len(tokens)`` holds unconditionally and proves nothing
about whether a construct was silently dropped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plc_code.parser import parse_scl_file
from plc_code.parser.statement_parser import parse_statements, verify_no_silent_loss

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _fixture_files() -> list[Path]:
    return sorted(FIXTURES.rglob("*.s7dcl"))


def test_the_corpus_is_not_empty() -> None:
    """Guard against the glob silently matching nothing."""
    assert len(_fixture_files()) >= 20


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_fixture_parses_without_errors(path: Path) -> None:
    """Every top-level, non-empty region in every fixture parses with zero errors."""
    block = parse_scl_file(path)
    if block is None or not block.name:
        pytest.skip(f"{path.name} holds no parsable block")

    for network in block.networks:
        for region in network.regions:
            if not region.tokens:
                continue
            result = parse_statements(region.tokens)
            assert result.errors == [], f"{path.name}, region {region.name!r}:\n" + "\n".join(
                f"  {e.message}" for e in result.errors
            )


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_fixture_has_no_silent_token_loss(path: Path) -> None:
    """Every token in every top-level region is covered by a statement, error or separator span."""
    block = parse_scl_file(path)
    if block is None or not block.name:
        pytest.skip(f"{path.name} holds no parsable block")

    for network in block.networks:
        for region in network.regions:
            if not region.tokens:
                continue
            result = parse_statements(region.tokens)
            problems = verify_no_silent_loss(region.tokens, result)
            assert not problems, f"{path.name}, region {region.name!r}:\n" + "\n".join(
                f"  {p}" for p in problems
            )
