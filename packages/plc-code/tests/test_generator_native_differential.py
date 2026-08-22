r"""The unit-level differential: `generate_statements` against `_generate_statements_via_strings`.

Task 6's instrument. The expression-level differential (`test_renderer_differential.py`)
compares `render(tree)` against `ExpressionTranslator().translate(scl_text(tokens))` --
one expression at a time, in isolation. This module compares one level up: for every
statement list found in the corpus (one per region, one per network's own out-of-region
tokens -- the same two populations `conftest._block_expression_slices` walks), it runs
BOTH generator entry points over the *same* parsed statements and asserts the Python
lines they produce line-for-line agree::

    _generate_statements_via_strings(statements, string_constants=...)
        against
    generate_statements(statements, string_constants=...)

`string_constants` is collected per block exactly as `SCLTranspiler.transpile` does
(`self._collect_string_constants()`, a pre-scan over every region's raw text), so a
block that uses symbolic CASE labels or symbolic assignments exercises the same mapping
in this differential that a real `transpile_block` run would use.

The bar is the same one `test_renderer_differential.py` applies: **zero UNATTRIBUTED
divergences**, not zero divergences outright. The reason a unit-level divergence can be
legitimate at all is structural, not a relaxation invented here: `Assignment`'s old
branch (`_generate_statements_via_strings`) still routes `target`/`value` through
`StatementTranslator.translate_simple_statement`, which routes through the very same
`ExpressionTranslator` the expression-level differential already measures -- so any
defect that differential already found and attributed (a bare builtin call binding a
parameter by name, a global DB name `GLOBAL_DB_PATTERN` can't match, the acknowledged
`NOT`-prefix bug, a chained typed literal under a size prefix) is not a *new* generator
bug when it resurfaces here: it is that same expression-level residual, seen through
one more layer of text-reconstruction. A unit-level divergence earns "attributed"
status only by containing at least one expression slice
(`test_renderer_differential.py`'s own `expression_slice_diverges` fixture, reused
verbatim rather than reimplemented, so the two differentials never judge the same slice
two different ways) that itself diverges -- never by assertion.

The comparison is made after `normalize_whitespace` (the fixture from `conftest.py`,
shared with `test_renderer_differential.py`) on each corresponding line, for the same
reason that differential applies it to expression text: `_generate_statements_via_strings`'s
`Assignment` branch still goes through `scl_text`'s token-joined reconstruction, which
puts a space next to `.`/`(`/`)`/`[`/`]` where the source had none (`self.a . b`), while
`generate_statements`'s native branch renders directly from the tree and never
introduces one (`self.a.b`). Measured directly against the real corpus (not assumed):
of 594 units, an UNnormalised comparison shows 418 "divergent" units; normalising
closes 410 of them as pure reconstruction spacing; of the remaining 8, every single one
contains an expression slice the expression-level differential also reports as
divergent -- see the task report for the full per-unit cross-reference and sanitised
examples.

This differential does not decide attribution by assertion -- it asks the same
question `test_renderer_differential.py` already answered for that exact slice, and
only accepts "attributed" when the answer is yes. A unit whose line-level difference
cannot be traced to any of its own expression slices diverging is *not* attributed, and
the test fails on it -- that is exactly the generator bug this differential exists to
catch, and no docstring here excuses it.

No golden file: the generated Python and the SCL it came from both carry customer
identifiers, and this repository is public (see `tests/test_no_confidential_references.py`).
Everything is compared and reported in memory, for one session, and never written to
disk.

Skips (rather than fails) when `PLC_CORPUS_ROOTS` is unset -- same convention as
`test_renderer_differential.py` and the same reason: the corpus is a read-only sibling
of this repository, present on a developer machine but absent on CI.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from plc_code.executor.generator import _generate_statements_via_strings, generate_statements
from plc_code.executor.transpiler import SCLTranspiler
from plc_code.parser.expressions import Expression
from plc_code.parser.lexer import Token
from plc_code.parser.models import Block
from plc_code.parser.statement_parser import parse_statements
from plc_code.parser.statements import Statement

#: One `(label, tokens, tree)` entry per non-empty expression-bearing slice found by
#: walking a statement list — the `statement_expression_slices` fixture's type, spelled
#: once so neither docstring below has to wrap it across a 110-column line.
_StatementExpressionSlices = Callable[
    [list[Statement], str], Iterator[tuple[str, list[Token], Expression | None]]
]


def _corpus_statement_lists(block: Block) -> list[tuple[str, list[Statement]]]:
    """One entry per region and per network's own out-of-region tokens, parsed to statements.

    Mirrors `conftest._block_expression_slices`'s two populations (`network.regions[*]`
    and each network's own `tokens`) at the statement-list level rather than the
    expression-slice level -- this differential compares whole `generate_statements`
    calls, which take a *list* of statements, not one expression at a time.

    Parameters
    ----------
    block : Block
        A parsed block.

    Returns
    -------
    list[tuple[str, list[Statement]]]
        A label (block name, network index, region name or "outside any region") paired
        with the statements `parse_statements` reads from that unit's tokens. A unit
        whose tokens fail to parse contributes an empty statement list -- this
        differential is not the parser's own conformance check (see
        `test_statement_parser_corpus.py`), so a parse failure is treated the same on
        both sides of the comparison rather than skipped.
    """
    units: list[tuple[str, list[Statement]]] = []
    for index, network in enumerate(block.networks):
        for region in network.regions:
            if not region.tokens:
                continue
            result = parse_statements(region.tokens)
            label = f"{block.name} network[{index}] region {region.name!r}"
            units.append((label, result.statements))
        if network.tokens:
            result = parse_statements(network.tokens)
            label = f"{block.name} network[{index}] outside any region"
            units.append((label, result.statements))
    return units


def _block_string_constants(block: Block) -> dict[str, int]:
    """The string-constant mapping a real `transpile_block` run would use for `block`.

    Parameters
    ----------
    block : Block
        A parsed block.

    Returns
    -------
    dict[str, int]
        `SCLTranspiler._collect_string_constants`'s own result: the same pre-scan
        `SCLTranspiler.transpile` performs before generating any code, run here so this
        differential exercises the same `string_constants` a real transpile would pass
        to `generate_statements`.
    """
    transpiler = SCLTranspiler(block=block)
    transpiler._collect_string_constants()  # noqa: SLF001 - reusing the real pre-scan, not reinventing it
    return transpiler._string_constants  # noqa: SLF001


def _lines_agree(
    old_lines: list[str], new_lines: list[str], normalize_whitespace: Callable[[str], str]
) -> bool:
    """Whether two lists of generated Python lines agree, up to layout whitespace.

    A different number of lines is always a real divergence -- there is no whitespace
    normalisation that can make two structurally different outputs the same. Given the
    same number of lines, each corresponding pair is compared through
    `normalize_whitespace` rather than by strict equality, for the same reason
    `test_renderer_differential.py` applies it to expression text: the old side's
    `Assignment` branch still goes through `scl_text`'s token-joined reconstruction,
    which puts a space next to `.`/`(`/`)`/`[`/`]` where the source had none
    (`self.a . b`), while the new side renders directly from the tree and never
    introduces one (`self.a.b`) -- see the module docstring for the measured count this
    closes.

    Parameters
    ----------
    old_lines : list[str]
        `_generate_statements_via_strings`'s output for one unit.
    new_lines : list[str]
        `generate_statements`'s output for the same unit.
    normalize_whitespace : Callable[[str], str]
        The layout-whitespace-removal fixture from `conftest.py`.

    Returns
    -------
    bool
        True when both lists have the same length and every corresponding pair of
        lines is equal after `normalize_whitespace`.
    """
    if len(old_lines) != len(new_lines):
        return False
    return all(
        normalize_whitespace(old_line) == normalize_whitespace(new_line)
        for old_line, new_line in zip(old_lines, new_lines, strict=True)
    )


def _unit_has_a_diverging_expression_slice(
    statements: list[Statement],
    label: str,
    statement_expression_slices: _StatementExpressionSlices,
    expression_slice_diverges: Callable[[list[Token], Expression | None], bool],
) -> bool:
    """Whether at least one expression slice inside `statements` diverges at the expression level.

    The attribution check: a unit-level divergence is legitimate only when it contains a
    slice `test_renderer_differential.py`'s own judgement (`expression_slice_diverges`)
    already flags as divergent -- see the module docstring. Walking every slice with
    `statement_expression_slices` rather than only `Assignment.target`/`Assignment.value`
    is deliberate breadth, not guesswork: `If`/`For`/`While`/`Case` slices are rendered
    identically by both generator entry points (neither's branch for those kinds changed
    in this task), so they can never themselves be the cause of a unit's divergence, but
    checking all of them anyway costs nothing and keeps this function honest about what
    "at least one slice diverges" actually means, rather than assuming which kind it will
    be.

    Parameters
    ----------
    statements : list[Statement]
        One unit's statement list (as `_corpus_statement_lists` yields it).
    label : str
        The unit's own label, used as this walk's `label_prefix` -- not otherwise
        inspected, since only whether *any* slice diverges matters here.
    statement_expression_slices : _StatementExpressionSlices
        The per-unit expression-slice walker fixture from `conftest.py`.
    expression_slice_diverges : Callable[[list[Token], Expression | None], bool]
        The shared per-slice divergence judgement fixture from `conftest.py`.

    Returns
    -------
    bool
        True if any slice found by walking `statements` diverges per
        `expression_slice_diverges`.
    """
    return any(
        expression_slice_diverges(tokens, tree)
        for _slice_label, tokens, tree in statement_expression_slices(statements, label)
    )


def test_generator_native_differential_over_the_corpus(
    corpus_blocks: tuple[tuple[Path, Block], ...],
    normalize_whitespace: Callable[[str], str],
    statement_expression_slices: _StatementExpressionSlices,
    expression_slice_diverges: Callable[[list[Token], Expression | None], bool],
) -> None:
    """`_generate_statements_via_strings` against `generate_statements`, over every unit found.

    Zero *unattributed* divergences is the bar, not zero divergences outright -- see the
    module docstring for why a divergence attributable to an expression-level residual is
    not a new generator bug, and how `_unit_has_a_diverging_expression_slice` decides
    attribution by re-asking `test_renderer_differential.py`'s own question rather than
    by an enumerated exception list.

    Parameters
    ----------
    corpus_blocks : tuple[tuple[Path, Block], ...]
        The session-scoped, once-parsed corpus fixture from `conftest.py`.
    normalize_whitespace : Callable[[str], str]
        The layout-whitespace-removal fixture from `conftest.py`.
    statement_expression_slices : _StatementExpressionSlices
        The per-unit expression-slice walker fixture from `conftest.py`.
    expression_slice_diverges : Callable[[list[Token], Expression | None], bool]
        The shared per-slice divergence judgement fixture from `conftest.py`.
    """
    blocks_seen = 0
    units_seen = 0
    agreements = 0
    attributed_divergences: list[str] = []
    unattributed_divergences: list[str] = []

    for _path, block in corpus_blocks:
        blocks_seen += 1
        string_constants = _block_string_constants(block)
        for label, statements in _corpus_statement_lists(block):
            units_seen += 1
            old_lines = _generate_statements_via_strings(statements, string_constants=string_constants)
            new_lines = generate_statements(statements, string_constants=string_constants)
            if _lines_agree(old_lines, new_lines, normalize_whitespace):
                agreements += 1
                continue
            if _unit_has_a_diverging_expression_slice(
                statements, label, statement_expression_slices, expression_slice_diverges
            ):
                attributed_divergences.append(label)
            else:
                unattributed_divergences.append(label)

    if blocks_seen == 0:
        pytest.skip("PLC_CORPUS_ROOTS is unset or names no readable project")

    print(
        f"\ngenerator native differential: {units_seen} unit(s) examined across "
        f"{blocks_seen} block(s), {agreements} agree, "
        f"{len(attributed_divergences)} diverge (attributed), "
        f"{len(unattributed_divergences)} diverge (UNATTRIBUTED)"
    )
    assert unattributed_divergences == []
    assert units_seen > 0
