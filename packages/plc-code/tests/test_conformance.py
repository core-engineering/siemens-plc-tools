"""The conformance report — what the parser reads, and what it does not.

Deliberately separate from `--check`: nothing generates from the AST yet, so an
unparsed statement does not mean a broken block. Routing this into --check would
turn correct blocks red and destroy the gate value that command was built for.
Hence: always exit 0. It is a report, not a gate.

Coverage is derived from ``ParseResult.error_spans`` and
``ParseResult.unattributed_spans`` — the tokens the parser demonstrably could
not read — rather than from ``ParseResult.consumed_tokens``, which is always
``len(tokens)`` by loop construction and therefore always reads 100% no matter
what the parser can actually handle. The acceptance bar for this module is
that the figure visibly drops on an input the parser is guaranteed to reject
(``GOTO`` has no node type, by design); a metric that still reads 100% there
would be worse than shipping nothing.
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from plc_code.cli import cli
from plc_code.parser import parse_scl_file
from plc_code.parser.conformance import build_report
from plc_code.parser.lexer import TokenType, tokenize
from plc_code.parser.models import Block, Network, Region

FIXTURES = Path(__file__).resolve().parent / "fixtures"
# SignalDebounce.s7dcl (the brief's suggested fixture) has no code REGION at
# all — its network content sits outside any region, so region.tokens is
# empty everywhere and build_report has nothing to measure. PumpControl.s7dcl
# has a real 201-token logic region and parses with zero errors.
CLEAN_BLOCK = FIXTURES / "PumpControl.s7dcl"


def _region_block(name: str, source: str) -> Block:
    """Build a minimal synthetic block wrapping one region's worth of source.

    Parameters
    ----------
    name : str
        Block and region name to use.
    source : str
        SCL statement source, tokenized directly (no full block wrapper needed
        — ``build_report`` only ever reads ``block.networks[*].regions[*]``).

    Returns
    -------
    Block
        A block with one network holding one region with ``source``'s tokens.
    """
    tokens = [t for t in tokenize(source) if t.type is not TokenType.EOF]
    region = Region(name=name, tokens=tokens)
    return Block(name=name, block_type="FUNCTION", networks=[Network(regions=[region])])


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestBuildReport:
    def test_counts_blocks_and_tokens(self) -> None:
        block = parse_scl_file(CLEAN_BLOCK)
        report = build_report([(CLEAN_BLOCK, block)])
        assert report.blocks == 1
        assert report.tokens > 0

    def test_full_coverage_on_a_clean_block(self) -> None:
        block = parse_scl_file(CLEAN_BLOCK)
        report = build_report([(CLEAN_BLOCK, block)])
        assert report.coverage == pytest.approx(1.0)
        assert report.errors == []
        assert report.silent_loss == []
        assert report.block_clean_rate == pytest.approx(1.0)
        assert report.region_clean_rate == pytest.approx(1.0)

    def test_counts_statements_by_kind(self) -> None:
        block = parse_scl_file(CLEAN_BLOCK)
        report = build_report([(CLEAN_BLOCK, block)])
        assert sum(report.by_statement_kind.values()) == report.statements

    def test_coverage_is_zero_for_no_tokens(self) -> None:
        report = build_report([])
        assert report.coverage == 0.0
        assert report.block_clean_rate == 0.0
        assert report.region_clean_rate == 0.0

    def test_coverage_drops_on_unreadable_input(self) -> None:
        """The acceptance bar: GOTO has no node type, by design, and must error."""
        block = _region_block("HasGoto", "#a := 1; GOTO done; #b := 2;")
        report = build_report([(Path("HasGoto.s7dcl"), block)])
        assert report.errors != []
        assert report.coverage < 1.0
        assert report.clean_blocks == 0
        assert report.clean_regions == 0

    def test_full_coverage_block_has_no_errors_and_is_clean(self) -> None:
        block = _region_block("Clean", "#a := 1; #b := 2;")
        report = build_report([(Path("Clean.s7dcl"), block)])
        assert report.coverage == pytest.approx(1.0)
        assert report.clean_blocks == 1
        assert report.clean_regions == 1

    def test_empty_region_is_skipped_not_counted(self) -> None:
        region = Region(name="Empty", tokens=[])
        block = Block(name="Empty", block_type="FUNCTION", networks=[Network(regions=[region])])
        report = build_report([(Path("Empty.s7dcl"), block)])
        assert report.blocks == 1
        assert report.regions == 0
        assert report.tokens == 0
        # No regions examined: vacuously clean.
        assert report.clean_blocks == 1

    def test_unnamed_block_is_skipped(self) -> None:
        report = build_report([(Path("nope.s7dcl"), Block(name="", block_type="FUNCTION"))])
        assert report.blocks == 0

    def test_none_block_is_skipped(self) -> None:
        report = build_report([(Path("nope.s7dcl"), None)])  # type: ignore[list-item]
        assert report.blocks == 0

    def test_fixture_corpus_is_fully_readable(self) -> None:
        """Documents the current baseline: the shipped corpus parses clean."""
        blocks = []
        for path in sorted(FIXTURES.rglob("*.s7dcl")):
            block = parse_scl_file(path)
            if block is not None and block.name:
                blocks.append((path, block))
        report = build_report(blocks)
        assert report.coverage == pytest.approx(1.0)
        assert report.errors == []
        assert report.silent_loss == []
        assert report.block_clean_rate == pytest.approx(1.0)
        assert report.region_clean_rate == pytest.approx(1.0)


class TestCli:
    def test_conformance_flag_exists(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["transpile", "--help"])
        assert "--conformance" in result.output

    def test_always_exits_zero(self, runner: CliRunner) -> None:
        """A report, not a gate — even over the whole corpus."""
        result = runner.invoke(cli, ["transpile", "--conformance", str(FIXTURES)])
        assert result.exit_code == 0

    def test_reports_a_coverage_figure(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["transpile", "--conformance", str(FIXTURES)])
        assert "%" in result.output

    def test_json_output(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["transpile", "--conformance", "-f", "json", str(CLEAN_BLOCK)])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["blocks"] == 1
        assert "coverage" in payload
        assert payload["errors"] == []

    def test_check_is_unaffected(self, runner: CliRunner) -> None:
        """--check keeps its own semantics: it still gates."""
        result = runner.invoke(cli, ["transpile", "--check", str(FIXTURES)])
        assert result.exit_code == 0
