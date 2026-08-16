"""Aggregate statement-parser results into a coverage report.

Answers one question: how much of the SCL we actually have can the AST read?
The figure decides phase 2's strategy — an incremental strangler with a text
fallback, or a single cutover — instead of that call being guessed.

Coverage is **not** ``consumed_tokens / tokens``. ``consumed_tokens`` is
``TokenStream.position()`` after ``parse()`` returns, and the recovery loop
in ``StatementParser.parse`` guarantees forward progress to the end of the
stream on every input — so ``consumed_tokens`` always equals ``len(tokens)``,
clean or not. Measured directly: on ``PumpControl.s7dcl``'s 201-token region,
``consumed_tokens / tokens`` is 201/201, i.e. 100%, regardless of whether the
region actually parsed. That formula is a constant, not a metric.

Coverage here is instead defined from what the parser demonstrably could
**not** read: the union of token indices inside ``ParseResult.error_spans``
(a construct the parser rejected) and ``ParseResult.unattributed_spans`` (a
token no statement, error or separator claimed — always a defect per
``verify_no_silent_loss``). A region's readable-token count is its token
count minus the size of that union; a set is used so a token covered by more
than one span — which should not happen, but is not assumed away — is still
counted once, not once per covering span.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from plc_code.parser.models import Block
from plc_code.parser.statement_parser import ParseResult, parse_statements, verify_no_silent_loss
from plc_code.parser.statements import ParseError


def _unread_token_indices(result: ParseResult) -> set[int]:
    """Token indices a region's tokens that the parser could not account for.

    The complement of this set, over a region's token range, is what
    ``ConformanceReport.coverage`` sums as "read". Built from two sources:
    ``error_spans`` (a construct the parser rejected outright — width 0 for a
    shape error that consumes nothing itself, width 1 for a token
    ``_recover()`` skipped) and ``unattributed_spans`` (a token no statement,
    error or separator claimed at all — an accounting defect in its own
    right, per ``verify_no_silent_loss``, and unambiguously not "read").

    A plain ``set`` of indices is used rather than summing span widths so
    that spans which happen to nest or overlap are not double-counted; each
    token index that is unread counts exactly once no matter how many spans
    cover it.

    Parameters
    ----------
    result : ParseResult
        The result of parsing one region's token slice.

    Returns
    -------
    set[int]
        Token indices, relative to that region's token list, the parser did
        not read.
    """
    unread: set[int] = set()
    for start, end in result.error_spans:
        unread.update(range(start, end))
    for start, end in result.unattributed_spans:
        unread.update(range(start, end))
    return unread


@dataclass
class ConformanceReport:
    """What the statement parser read across a set of blocks.

    Attributes
    ----------
    blocks : int
        Blocks examined (blocks with a name; unparsable files are skipped by
        the caller before this report is built).
    clean_blocks : int
        Blocks in which every region parsed with zero errors. A block with
        no non-empty top-level regions counts as clean vacuously.
    regions : int
        Non-empty top-level regions examined (``block.networks[*].regions``
        only — ``region.nested_regions`` is not descended into, because a
        region's ``tokens`` already contains its nested regions' tokens
        verbatim; descending would parse the same tokens twice and inflate
        every count in this report).
    clean_regions : int
        Regions that parsed with zero errors.
    statements : int
        Statements successfully parsed, across all regions.
    tokens : int
        Tokens offered to the parser, summed over every region examined.
    consumed : int
        Tokens the parser actually accounted for as a statement, an error's
        own token, or a separator — i.e. ``tokens`` minus the size of the
        per-region union of ``error_spans`` and ``unattributed_spans``. Not
        ``ParseResult.consumed_tokens`` (see module docstring for why that
        figure is vacuous).
    errors : list[tuple[str, ParseError]]
        Each error with the name of the block it came from.
    by_statement_kind : dict[str, int]
        Statement class name -> count. This is the conformance matrix,
        derived from behaviour on real code rather than maintained by hand,
        so it cannot go stale.
    silent_loss : list[str]
        One entry per problem ``verify_no_silent_loss`` found, prefixed with
        the block and region it came from. Always empty on well-behaved
        input; a non-empty list means a token was dropped on the floor
        rather than being read, rejected, or flagged as unattributed, and is
        surfaced here rather than hidden, since that is exactly the kind of
        loss this report exists to catch.
    """

    blocks: int = 0
    clean_blocks: int = 0
    regions: int = 0
    clean_regions: int = 0
    statements: int = 0
    tokens: int = 0
    consumed: int = 0
    errors: list[tuple[str, ParseError]] = field(default_factory=list)
    by_statement_kind: dict[str, int] = field(default_factory=dict)
    silent_loss: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Share of tokens the parser could read, 0.0 when there are none."""
        return self.consumed / self.tokens if self.tokens else 0.0

    @property
    def block_clean_rate(self) -> float:
        """Share of blocks that parsed with zero errors, 0.0 when there are none."""
        return self.clean_blocks / self.blocks if self.blocks else 0.0

    @property
    def region_clean_rate(self) -> float:
        """Share of regions that parsed with zero errors, 0.0 when there are none."""
        return self.clean_regions / self.regions if self.regions else 0.0


def build_report(blocks: list[tuple[Path, Block]]) -> ConformanceReport:
    """Parse every top-level region of every block and total the results.

    Parameters
    ----------
    blocks : list[tuple[Path, Block]]
        Source path and parsed block. Blocks that are ``None`` or unnamed are
        skipped.

    Returns
    -------
    ConformanceReport
    """
    report = ConformanceReport()
    kinds: Counter[str] = Counter()

    for _path, block in blocks:
        if block is None or not block.name:
            continue
        report.blocks += 1
        block_has_error = False

        for network in block.networks:
            for region in network.regions:
                if not region.tokens:
                    continue
                report.regions += 1
                result = parse_statements(region.tokens)

                n_tokens = len(region.tokens)
                report.tokens += n_tokens
                report.consumed += n_tokens - len(_unread_token_indices(result))
                report.statements += len(result.statements)
                kinds.update(type(s).__name__ for s in result.statements)
                report.errors.extend((block.name, e) for e in result.errors)
                report.silent_loss.extend(
                    f"{block.name}, region {region.name!r}: {problem}"
                    for problem in verify_no_silent_loss(region.tokens, result)
                )

                if result.errors:
                    block_has_error = True
                else:
                    report.clean_regions += 1

        if not block_has_error:
            report.clean_blocks += 1

    report.by_statement_kind = dict(kinds.most_common())
    return report
