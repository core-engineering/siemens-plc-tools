r"""The unit-level differential: `generate_statements` against `_generate_statements_via_strings`.

Task 6's instrument. The expression-level differential (`test_renderer_differential.py`)
compares `render(tree)` against `ExpressionTranslator().translate(scl_text(tokens))` --
one expression at a time, in isolation. This module compares one level up: for every
statement list found in the corpus (one per region, one per network's own out-of-region
tokens -- the same two populations `conftest._block_expression_slices` walks), it runs
BOTH generator entry points over the *same* parsed statements and checks the Python
lines they produce::

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
`ExpressionTranslator` the expression-level differential already measures -- so a defect
that differential already found and attributed (a bare builtin call binding a parameter
by name, a global DB name `GLOBAL_DB_PATTERN` can't match, the acknowledged `NOT`-prefix
bug, a chained typed literal under a size prefix) is not a *new* generator bug when it
resurfaces here.

**Attribution is per statement, not per unit.** An earlier version of this differential
attributed a whole diverging unit if *any* expression slice inside it diverged --
including an `If`/`Case`/`For`/`While` header's own condition or label. That was too
weak when only `Assignment` was native: those headers were unchanged and byte-identical
on both generator entry points, so a residual there could never itself cause a unit's
lines to differ, yet it could still license waving away a genuine `Assignment` bug
sitting elsewhere in the same unit. `_attribute_unit_divergence` fixed this for
`Assignment` (`_walk_assignments`, recursing into `If`/`Case`/`For`/`While` bodies,
comparing each one **in isolation**), and now that a header renders natively too (Task
7), the same discipline applies to it: `_walk_control_flow_headers` walks every
`If`/`For`/`While`/`Case` header in the unit, yielding a *shallow* copy (the header's own
condition/bounds/selector/label slices, but an empty body and, for `If`/`Case`, only the
one branch/arm being isolated -- see its own docstring for why an empty body isolates
the header line cleanly) so it too can be generated **in isolation** and compared. Both
walks feed the same rule: a unit found by either one is compared
(`_generate_statements_via_strings`/`generate_statements` on the one-element/shallow
list, at that unit's own indent depth, with the same `string_constants`) and, when it
diverges, is only accepted as "explained" when its own slice(s) (via
`statement_expression_slices` on that same isolated list) are flagged by
`expression_slice_diverges`. Since every other statement kind still contributes
byte-identical lines on both sides, the sum of explained units' own differing-line counts
must equal the whole unit's differing-line count; if it does not, some line is left
unexplained and the unit is unattributed. `string_constants` is threaded into
`expression_slice_diverges` too, so the classifier judges the exact question this
differential asks, not a narrower one that ignores string constants.

**The native/fallback split is measured, not assumed.** `generate_statements`'s
`Assignment` branch falls back to the dispatcher for three shapes (see
`generator._generate_assignment`'s own docstring), and its `If`/`For`/`While`/`Case`
header rendering falls back for two (see `generator._render_expression_or_fallback` /
`_render_case_label`); a fallback compares the dispatcher against itself and can only
ever agree, so "N agree" alone conflates agreement that exercised the new path with
agreement that did not exercise it at all. `generator.reset_assignment_render_counters` /
`generator.assignment_render_counts` and (Task 7) the parallel
`generator.reset_control_flow_render_counters` / `generator.control_flow_render_counts`
expose module-level counters this differential resets immediately before each unit's
real `generate_statements` call and reads immediately after, before any of the
diagnostic isolated calls `_attribute_unit_divergence` goes on to make (which would
otherwise pollute the count) -- accumulated across the whole run and printed as
``native=N fell_back=M, control_flow_native=P control_flow_fell_back=Q``.

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

from plc_code.executor.generator import (
    _generate_statements_via_strings,
    assignment_render_counts,
    control_flow_render_counts,
    generate_statements,
    reset_assignment_render_counters,
    reset_control_flow_render_counters,
)
from plc_code.executor.transpiler import SCLTranspiler
from plc_code.parser.expressions import Expression
from plc_code.parser.lexer import Token
from plc_code.parser.models import Block
from plc_code.parser.statement_parser import parse_statements
from plc_code.parser.statements import Assignment, Branch, Case, CaseBranch, For, If, Statement, While

#: One `(label, tokens, tree)` entry per non-empty expression-bearing slice found by
#: walking a statement list — the `statement_expression_slices` fixture's type, spelled
#: once so neither docstring below has to wrap it across a 110-column line.
_StatementExpressionSlices = Callable[
    [list[Statement], str], Iterator[tuple[str, list[Token], Expression | None]]
]

#: `expression_slice_diverges`'s type, `string_constants` included — spelled once for
#: the same reason as `_StatementExpressionSlices` above.
_ExpressionSliceDiverges = Callable[[list[Token], Expression | None, dict[str, int] | None], bool]


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


def _differing_line_count(
    old_lines: list[str], new_lines: list[str], normalize_whitespace: Callable[[str], str]
) -> int:
    """How many lines two generated-Python outputs disagree on, after `normalize_whitespace`.

    Counts one per position in the shared prefix where the normalised lines differ,
    plus the absolute difference in length -- so a length mismatch always contributes a
    positive count and can never be mistaken for "zero differing lines" the way a naive
    `zip`-based comparison would if one side were simply a prefix of the other.

    Parameters
    ----------
    old_lines : list[str]
        One side's generated Python lines.
    new_lines : list[str]
        The other side's, for the same input.
    normalize_whitespace : Callable[[str], str]
        The layout-whitespace-removal fixture from `conftest.py`.

    Returns
    -------
    int
        0 when the two agree entirely (after normalisation); otherwise the number of
        disagreeing positions in the shared prefix, plus `abs(len(old) - len(new))`.
    """
    common = min(len(old_lines), len(new_lines))
    mismatches = sum(
        1
        for old_line, new_line in zip(old_lines[:common], new_lines[:common], strict=True)
        if normalize_whitespace(old_line) != normalize_whitespace(new_line)
    )
    return mismatches + abs(len(old_lines) - len(new_lines))


def _walk_assignments(statements: list[Statement], depth: int = 0) -> Iterator[tuple[Assignment, int]]:
    """Every `Assignment` inside `statements`, paired with its indent depth, in source order.

    Recurses into `If` branches and `else_body`, `Case` arms and `default`, and
    `For`/`While` bodies -- the same nesting `generate_statements` itself walks (one
    level deeper per body) -- so an `Assignment` nested inside any depth of control flow
    is still found. `Call`, `Return`, `Exit`, and the `If`/`For`/`While`/`Case` header
    expressions themselves are not `Assignment`s and are not yielded: per the module
    docstring, they are rendered by byte-identical code on both generator entry points
    at this stage, so they can never be the source of a unit's divergence.

    Parameters
    ----------
    statements : list[Statement]
        The statements to walk -- typically one unit's full statement list.
    depth : int, optional
        The indent depth `statements` themselves sit at; each nested body is walked at
        `depth + 1`. Default 0, matching a unit's own top-level statements (the whole
        unit is itself generated with `indent=0`).

    Yields
    ------
    tuple[Assignment, int]
        Each `Assignment` found, and the indent depth it would be generated at.
    """
    for statement in statements:
        if isinstance(statement, Assignment):
            yield statement, depth
        elif isinstance(statement, If):
            for branch in statement.branches:
                yield from _walk_assignments(branch.body, depth + 1)
            yield from _walk_assignments(statement.else_body, depth + 1)
        elif isinstance(statement, Case):
            for arm in statement.branches:
                yield from _walk_assignments(arm.body, depth + 1)
            yield from _walk_assignments(statement.default, depth + 1)
        elif isinstance(statement, For):
            yield from _walk_assignments(statement.body, depth + 1)
        elif isinstance(statement, While):
            yield from _walk_assignments(statement.body, depth + 1)


def _walk_control_flow_headers(
    statements: list[Statement], depth: int = 0
) -> Iterator[tuple[str, Statement, int]]:
    """Every `If`/`For`/`While`/`Case` header inside `statements`, as an isolated one-line unit.

    Task 7's counterpart to `_walk_assignments`: now that a header (a condition, a `For`
    bound, a `Case` selector/label) renders natively too, a divergence there needs the same
    per-slice attribution an `Assignment` already gets. A header cannot be compared in
    isolation the way a bare `Assignment` can, though -- an `If`/`For`/`While`/`Case`
    statement's own line is inseparable from generating its body (both generator entry
    points always emit *something* under a header, even an empty body becomes `pass`). So
    each yielded statement is a *shallow* copy of the original: same condition/bounds/
    selector/label token slices and parsed trees, but an empty body (and, for `If`/`Case`,
    only the *one* branch/arm being isolated, no other branches, no `else`/default) -- since
    an empty body generates identically to `pass` on both generator entry points regardless
    of what the real body contained (see `_generate_body`/`_generate_body_via_strings`'s
    shared padding rule), comparing `_generate_statements_via_strings([shallow])` against
    `generate_statements([shallow])` isolates exactly the header line's own rendering, with
    no contribution from sibling branches or the real (possibly also-diverging) body.

    Recurses into every body at `depth + 1` -- `If.branches[*].body` and `else_body`,
    `Case.branches[*].body` and `default`, `For.body`, `While.body` -- the same nesting
    `generate_statements` itself walks, so a header nested inside any depth of control flow
    is still found and isolated on its own.

    Parameters
    ----------
    statements : list[Statement]
        The statements to walk -- typically one unit's full statement list.
    depth : int, optional
        The indent depth `statements` themselves sit at. Default 0, matching a unit's own
        top-level statements.

    Yields
    ------
    tuple[str, Statement, int]
        A label suffix identifying which header this is (e.g. `"If.branches[0].condition"`,
        `"Case.branches[1]"`), the shallow one-branch/one-arm statement to generate in
        isolation, and the indent depth to generate it at.
    """
    for statement in statements:
        if isinstance(statement, If):
            for index, branch in enumerate(statement.branches):
                shallow_branch = Branch(
                    condition=branch.condition, body=[], condition_expr=branch.condition_expr
                )
                shallow = If(line=statement.line, branches=[shallow_branch], else_body=[])
                yield f"If.branches[{index}].condition", shallow, depth
                yield from _walk_control_flow_headers(branch.body, depth + 1)
            yield from _walk_control_flow_headers(statement.else_body, depth + 1)
        elif isinstance(statement, For):
            shallow_for = For(
                line=statement.line,
                variable=statement.variable,
                start=statement.start,
                end=statement.end,
                step=statement.step,
                body=[],
                start_expr=statement.start_expr,
                end_expr=statement.end_expr,
                step_expr=statement.step_expr,
            )
            yield "For.bounds", shallow_for, depth
            yield from _walk_control_flow_headers(statement.body, depth + 1)
        elif isinstance(statement, While):
            shallow_while = While(
                line=statement.line,
                condition=statement.condition,
                body=[],
                condition_expr=statement.condition_expr,
            )
            yield "While.condition", shallow_while, depth
            yield from _walk_control_flow_headers(statement.body, depth + 1)
        elif isinstance(statement, Case):
            for index, arm in enumerate(statement.branches):
                shallow_arm = CaseBranch(values=arm.values, body=[], values_expr=arm.values_expr)
                shallow_case = Case(
                    line=statement.line,
                    selector=statement.selector,
                    branches=[shallow_arm],
                    default=[],
                    selector_expr=statement.selector_expr,
                )
                yield f"Case.branches[{index}]", shallow_case, depth
                yield from _walk_control_flow_headers(arm.body, depth + 1)
            yield from _walk_control_flow_headers(statement.default, depth + 1)


def _attribute_unit_divergence(
    statements: list[Statement],
    label: str,
    string_constants: dict[str, int] | None,
    unit_diff_count: int,
    normalize_whitespace: Callable[[str], str],
    statement_expression_slices: _StatementExpressionSlices,
    expression_slice_diverges: _ExpressionSliceDiverges,
) -> list[str]:
    """Whether every differing line of one diverging unit is explained by its own diverging residual.

    Per-statement attribution -- see the module docstring for why "some slice anywhere
    in the unit diverges" is too weak a bar and how this replaces it. Two walks, both
    exhaustive over `statements` and both required to add up: `_walk_assignments` for
    every `Assignment` (the Task 6 walk, unchanged), and `_walk_control_flow_headers` for
    every `If`/`For`/`While`/`Case` header (Task 7's own construct). Each unit found by
    either walk is compared **in isolation** against its own dispatcher output, and each
    isolated divergence requires that unit's own expression slice(s) -- and only those
    slices, via `statement_expression_slices` on the same isolated (`[assignment]` or
    shallow header) statement list -- to be flagged by `expression_slice_diverges`. Every
    explained unit's own differing-line count is summed; the whole diverging line is
    fully attributed only when that sum equals `unit_diff_count` exactly and nothing
    (from either walk) was left unflagged. A line neither walk's own isolated comparison
    reproduces is not covered by this function at all and surfaces as a shortfall in the
    final sum -- exactly the "unattributed" outcome the module docstring's bar requires.

    Parameters
    ----------
    statements : list[Statement]
        One unit's full statement list.
    label : str
        The unit's own label, used as `statement_expression_slices`'s `label_prefix`
        for each isolated walk (suffixed with an index so two units of the same kind in
        the same unit are still distinguishable in a reported problem).
    string_constants : dict[str, int] | None
        The block's string-constant mapping, forwarded unchanged to every generator
        call and to `expression_slice_diverges`.
    unit_diff_count : int
        `_differing_line_count` already computed for the whole unit's
        `_generate_statements_via_strings`/`generate_statements` outputs -- passed in
        rather than recomputed, since the caller already has both.
    normalize_whitespace : Callable[[str], str]
        The layout-whitespace-removal fixture from `conftest.py`.
    statement_expression_slices : _StatementExpressionSlices
        The per-unit expression-slice walker fixture from `conftest.py`.
    expression_slice_diverges : _ExpressionSliceDiverges
        The shared per-slice divergence judgement fixture from `conftest.py`.

    Returns
    -------
    list[str]
        Empty when the unit is fully attributed. Otherwise, one entry per problem: an
        `Assignment` or header that diverges in isolation but whose own slice is not
        flagged, or (appended last, if it happens) a mismatch between `unit_diff_count`
        and the total explained -- the material for a STOP-and-report finding, since
        either means a differing line exists that no residual explains.
    """
    problems: list[str] = []
    explained_diff_total = 0

    for index, (assignment, depth) in enumerate(_walk_assignments(statements)):
        assignment_label = f"{label}: Assignment#{index}"
        old_one = _generate_statements_via_strings(
            [assignment], indent=depth, string_constants=string_constants
        )
        new_one = generate_statements([assignment], indent=depth, string_constants=string_constants)
        diff_count = _differing_line_count(old_one, new_one, normalize_whitespace)
        if diff_count == 0:
            continue
        flagged = any(
            expression_slice_diverges(tokens, tree, string_constants)
            for _slice_label, tokens, tree in statement_expression_slices([assignment], assignment_label)
        )
        if not flagged:
            problems.append(f"{assignment_label}: diverges in isolation but its own slice is not flagged")
            continue
        explained_diff_total += diff_count

    for index, (kind_label, shallow, depth) in enumerate(_walk_control_flow_headers(statements)):
        header_label = f"{label}: {kind_label}#{index}"
        old_one = _generate_statements_via_strings([shallow], indent=depth, string_constants=string_constants)
        new_one = generate_statements([shallow], indent=depth, string_constants=string_constants)
        diff_count = _differing_line_count(old_one, new_one, normalize_whitespace)
        if diff_count == 0:
            continue
        flagged = any(
            expression_slice_diverges(tokens, tree, string_constants)
            for _slice_label, tokens, tree in statement_expression_slices([shallow], header_label)
        )
        if not flagged:
            problems.append(f"{header_label}: diverges in isolation but its own slice is not flagged")
            continue
        explained_diff_total += diff_count

    if explained_diff_total != unit_diff_count:
        problems.append(
            f"{label}: unit shows {unit_diff_count} differing line(s) but only "
            f"{explained_diff_total} accounted for by flagged, diverging residuals"
        )
    return problems


def test_generator_native_differential_over_the_corpus(
    corpus_blocks: tuple[tuple[Path, Block], ...],
    normalize_whitespace: Callable[[str], str],
    statement_expression_slices: _StatementExpressionSlices,
    expression_slice_diverges: _ExpressionSliceDiverges,
) -> None:
    """`_generate_statements_via_strings` against `generate_statements`, over every unit found.

    Zero *unattributed* divergences is the bar, not zero divergences outright -- see the
    module docstring for why a divergence attributable to an expression-level residual
    is not a new generator bug, and how `_attribute_unit_divergence` decides attribution
    per `Assignment`/header rather than per unit. Also reports both native/fallback
    splits -- `generator.assignment_render_counts` and (Task 7)
    `generator.control_flow_render_counts` -- so "N agree" cannot be read as "N units
    exercised the new path" when some fraction fell back to the dispatcher and so could
    only ever agree with itself.

    Parameters
    ----------
    corpus_blocks : tuple[tuple[Path, Block], ...]
        The session-scoped, once-parsed corpus fixture from `conftest.py`.
    normalize_whitespace : Callable[[str], str]
        The layout-whitespace-removal fixture from `conftest.py`.
    statement_expression_slices : _StatementExpressionSlices
        The per-unit expression-slice walker fixture from `conftest.py`.
    expression_slice_diverges : _ExpressionSliceDiverges
        The shared per-slice divergence judgement fixture from `conftest.py`.
    """
    blocks_seen = 0
    units_seen = 0
    agreements = 0
    attributed_divergences: list[str] = []
    unattributed_divergences: list[str] = []
    total_native = 0
    total_fallback = 0
    total_control_flow_native = 0
    total_control_flow_fallback = 0

    for _path, block in corpus_blocks:
        blocks_seen += 1
        string_constants = _block_string_constants(block)
        for label, statements in _corpus_statement_lists(block):
            units_seen += 1
            reset_assignment_render_counters()
            reset_control_flow_render_counters()
            old_lines = _generate_statements_via_strings(statements, string_constants=string_constants)
            new_lines = generate_statements(statements, string_constants=string_constants)
            native_delta, fallback_delta = assignment_render_counts()
            total_native += native_delta
            total_fallback += fallback_delta
            cf_native_delta, cf_fallback_delta = control_flow_render_counts()
            total_control_flow_native += cf_native_delta
            total_control_flow_fallback += cf_fallback_delta

            unit_diff_count = _differing_line_count(old_lines, new_lines, normalize_whitespace)
            if unit_diff_count == 0:
                agreements += 1
                continue

            problems = _attribute_unit_divergence(
                statements,
                label,
                string_constants,
                unit_diff_count,
                normalize_whitespace,
                statement_expression_slices,
                expression_slice_diverges,
            )
            if problems:
                unattributed_divergences.extend(problems)
            else:
                attributed_divergences.append(label)

    if blocks_seen == 0:
        pytest.skip("PLC_CORPUS_ROOTS is unset or names no readable project")

    print(
        f"\ngenerator native differential: {units_seen} unit(s) examined across "
        f"{blocks_seen} block(s), {agreements} agree, "
        f"{len(attributed_divergences)} diverge (attributed), "
        f"{len(unattributed_divergences)} problem(s) (UNATTRIBUTED), "
        f"native={total_native} fell_back={total_fallback}, "
        f"control_flow_native={total_control_flow_native} "
        f"control_flow_fell_back={total_control_flow_fallback}"
    )
    assert unattributed_divergences == []
    assert units_seen > 0
