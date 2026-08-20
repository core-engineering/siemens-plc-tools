"""Aggregate statement-parser results into a coverage report.

Answers one question: how much of the SCL we actually have can the AST read?
The figure decides phase 2's strategy — an incremental strangler with a text
fallback, or a single cutover — instead of that call being guessed.

Coverage is **not** "the cursor reached the end of the stream". The recovery
loop in ``StatementParser.parse`` guarantees forward progress to the end of
the stream on every input, so that alone is a constant, not a metric —
measured directly, on ``PumpControl.s7dcl``'s 201-token region the cursor
reaches token 201 of 201 regardless of whether the region actually parsed.

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

from plc_code.parser.expressions import Expression
from plc_code.parser.lexer import Token
from plc_code.parser.models import Block
from plc_code.parser.statement_parser import ParseResult, parse_statements, verify_no_silent_loss
from plc_code.parser.statements import Assignment, Call, Case, For, If, ParseError, Statement, While


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


def _expression_slice_counts(statements: list[Statement]) -> tuple[int, int]:
    """Count expression-bearing slices and how many of them parsed, recursively.

    Walks every statement field wired to a ``*_expr`` counterpart in
    ``statements.py`` (``statement_parser.py`` is what actually populated
    those fields, at parse time) plus every nested body — an ``If``'s
    ``branches`` **and its separate** ``else_body``, a ``Case``'s
    ``branches`` **and its separate** ``default`` — since missing either
    under-counts the corpus by 12%.

    An empty slice (e.g. a ``For`` loop with no ``BY`` clause) is not
    counted at all: it never held an expression to parse, so counting it as
    an unparsed one would understate the rate for a reason that has nothing
    to do with what the parser can read. This mirrors ``StatementParser.
    _parse_expr``'s own treatment of an empty slice.

    Parameters
    ----------
    statements : list[Statement]
        Statements to walk, typically ``ParseResult.statements`` for one
        region.

    Returns
    -------
    tuple[int, int]
        ``(slices, slices_parsed)`` — how many non-empty expression slices
        were found, and how many of those have a non-``None`` tree.
    """
    slices = 0
    parsed = 0

    def _count(tokens: list[Token], expr: Expression | None) -> None:
        nonlocal slices, parsed
        if not tokens:
            return
        slices += 1
        if expr is not None:
            parsed += 1

    for statement in statements:
        if isinstance(statement, Assignment):
            _count(statement.target, statement.target_expr)
            _count(statement.value, statement.value_expr)
        elif isinstance(statement, Call):
            _count(statement.callee, statement.callee_expr)
            for argument in statement.arguments:
                _count(argument.value, argument.value_expr)
        elif isinstance(statement, If):
            for branch in statement.branches:
                _count(branch.condition, branch.condition_expr)
                inner_slices, inner_parsed = _expression_slice_counts(branch.body)
                slices += inner_slices
                parsed += inner_parsed
            inner_slices, inner_parsed = _expression_slice_counts(statement.else_body)
            slices += inner_slices
            parsed += inner_parsed
        elif isinstance(statement, Case):
            _count(statement.selector, statement.selector_expr)
            for case_branch in statement.branches:
                # `values_expr` is documented as optional (default: an empty list), so
                # a `CaseBranch` built without it must not crash here: an index past
                # its end is treated as an unparsed entry, not a length mismatch to
                # raise on. Every other index pairs exactly, same as `zip(strict=True)`.
                for index, value in enumerate(case_branch.values):
                    value_expr = (
                        case_branch.values_expr[index] if index < len(case_branch.values_expr) else None
                    )
                    _count(value, value_expr)
                inner_slices, inner_parsed = _expression_slice_counts(case_branch.body)
                slices += inner_slices
                parsed += inner_parsed
            inner_slices, inner_parsed = _expression_slice_counts(statement.default)
            slices += inner_slices
            parsed += inner_parsed
        elif isinstance(statement, For):
            _count(statement.start, statement.start_expr)
            _count(statement.end, statement.end_expr)
            _count(statement.step, statement.step_expr)
            inner_slices, inner_parsed = _expression_slice_counts(statement.body)
            slices += inner_slices
            parsed += inner_parsed
        elif isinstance(statement, While):
            _count(statement.condition, statement.condition_expr)
            inner_slices, inner_parsed = _expression_slice_counts(statement.body)
            slices += inner_slices
            parsed += inner_parsed

    return slices, parsed


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
        the cursor's raw end position (see module docstring for why that
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
    expression_slices : int
        Non-empty expression-bearing token slices found across every
        statement examined (an ``Assignment.value``, a ``Branch.condition``,
        one entry per ``CaseBranch`` label value, ...), counted once each. An
        absent optional slice (a ``For`` loop with no ``BY`` clause) is not
        counted — see ``_expression_slice_counts``.
    expression_slices_parsed : int
        How many of ``expression_slices`` have a non-``None`` ``*_expr``
        tree.
    expression_errors : list[tuple[str, ParseError]]
        Each expression-parse failure with the name of the block it came
        from. Kept separate from ``errors``: an expression the parser
        cannot yet read is not a statement-parser failure, and folding the
        two together would drop statement conformance for a reason that
        belongs to a different, still-in-progress grammar.
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
    expression_slices: int = 0
    expression_slices_parsed: int = 0
    expression_errors: list[tuple[str, ParseError]] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Share of tokens the parser could read, 0.0 when there are none."""
        return self.consumed / self.tokens if self.tokens else 0.0

    @property
    def expression_rate(self) -> float:
        """Share of expression slices that parsed, 0.0 when there are none."""
        return self.expression_slices_parsed / self.expression_slices if self.expression_slices else 0.0

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

                slices, slices_parsed = _expression_slice_counts(result.statements)
                report.expression_slices += slices
                report.expression_slices_parsed += slices_parsed
                report.expression_errors.extend((block.name, e) for e in result.expression_errors)

                if result.errors:
                    block_has_error = True
                else:
                    report.clean_regions += 1

        if not block_has_error:
            report.clean_blocks += 1

    report.by_statement_kind = dict(kinds.most_common())
    return report
