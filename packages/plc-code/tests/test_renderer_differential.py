"""The expression-level differential over the reference corpus.

Spec §10's instrument, and the reason this generator-replacement plan can swap two
layers — expression rendering and statement generation — at once without losing
attribution. Every statement the parser produces carries both a token slice and its
parsed tree (``Assignment.value`` beside ``value_expr``, ``Branch.condition`` beside
``condition_expr``, ``For.start`` beside ``start_expr``, one ``CaseBranch.values[i]``
beside ``values_expr[i]``, ``Argument.value`` beside ``value_expr``), so for every one
of those slices both sides of a comparison already exist, on unmodified code::

    render(tree)   against   ExpressionTranslator().translate(scl_text(tokens))

``render`` now exists (``plc_code.executor.renderer``) but only has visitors for
``Literal``, ``TypedLiteral``, ``VariableRef``, ``Member``, ``Index`` and
``Grouping`` — operators and calls are later tasks in the same plan. A slice whose
tree needs a visitor that does not exist yet raises ``UnsupportedExpression``, which
counts as a divergence here rather than failing the test: the point of this test at
this stage is the *count*, not a green run. Once every visitor lands (the last of
which is Task 5), the count of divergences must be zero and this test starts
asserting that.

The comparison is made after ``_normalize_whitespace`` on both sides, never before
and never on one side only. ``reference`` is built from ``scl_text(tokens)``, which
joins every token with a single space — the same lossy join ``Region.content`` does
— so a spaced-out reconstruction like ``self.a . b`` differs from the renderer's
compact ``self.a.b`` on whitespace alone, for a large share of the corpus (printed by
this test's own ``-s`` output as the gap between "agree" and what a strict
``reference == candidate`` would have counted). That gap is the reconstruction's
artefact, not a disagreement about what the expression means, so it is not what this
differential is for: the bar it should apply is semantic-text equivalence, not
byte-for-byte equivalence with a serialisation neither side is trying to reproduce.
Whitespace *inside* a quoted run (a string literal's own text) is never touched by
the normalisation — see ``_normalize_whitespace`` — so this is not a laxer bar in
general, only a blind spot for the one kind of noise that ``scl_text`` itself
introduces.

One divergence this bar deliberately still counts, and which is not fixed here: the
current translator renders ``#notReady`` as ``self.not Ready`` — invalid Python,
because its ``NOT``-detection matches the identifier's ``not`` prefix by text. The
tree-based renderer does not reproduce that bug (there is no visitor for it to
reproduce; ``VariableRef`` renders the name whole), so the two sides read as
different text and the slice diverges under any normalisation. That is correct: the
bug is real, acknowledged, and intentionally not carried forward into the new path.

The shipped fixtures are small and written to exercise specific shapes; the real
evidence is production SCL. Those projects are read-only siblings of this repository
and are absent on CI, so this test skips rather than fails when they are not there —
and nothing about them (paths, block names, SCL text, generated Python) is ever
written into this repository. See ``tests/test_no_confidential_references.py``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from plc_code.executor.codegen import ExpressionTranslator
from plc_code.executor.generator import scl_text
from plc_code.executor.renderer import UnsupportedExpression, render
from plc_code.parser import parse_scl_file
from plc_code.parser.expressions import Expression
from plc_code.parser.lexer import Token
from plc_code.parser.models import Block


def _roots() -> list[Path]:
    """Corpus roots, from ``PLC_CORPUS_ROOTS`` (``os.pathsep``-separated).

    Read from the environment rather than written down: the directories are customer
    projects and this repository is public.

    Returns
    -------
    list[Path]
        One entry per non-empty segment of ``PLC_CORPUS_ROOTS``.
    """
    raw = os.environ.get("PLC_CORPUS_ROOTS", "")
    return [Path(part) for part in raw.split(os.pathsep) if part]


#: A single- or double-quoted run, kept intact by `_normalize_whitespace` below.
#: Matches the same two token shapes `expression_parser._parse_primary` reads —
#: `'text'` (a string literal, whose internal spacing is part of what it means)
#: and `"Name"` (a symbol reference, unlikely to carry internal spacing but
#: protected on the same terms, since both are one token in the source and
#: normalisation must not reach inside either).
_QUOTED_RUN = re.compile(r"\"[^\"]*\"|'[^']*'")


def _normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace to one space, and strip the ends — outside quotes.

    `scl_text` reconstructs a token slice by joining every token with a single
    space (mirroring `Region.content`'s own lossy join), so `#a . b` and `#a.b`
    are the same tokens and the same meaning, differing only in this
    reconstruction's spacing. The renderer works from the tree and never
    introduces that spacing, so a whitespace-only difference between the two
    sides is the reconstruction's artefact, not a divergence in what either
    side computed — see the module docstring for the count this bar closes.

    Text inside a quoted run is left untouched: a string literal's internal
    whitespace is part of its value (`'a  b'` and `'a b'` are different SCL),
    and a quoted symbol name is protected on the same terms even though the
    corpus is not expected to put whitespace inside one. `_QUOTED_RUN` finds
    both quoting conventions; only the text between and around those runs is
    collapsed.

    Parameters
    ----------
    text : str
        Either side of the comparison: `scl_text(tokens)` run through
        `ExpressionTranslator.translate`, or `render(tree)`.

    Returns
    -------
    str
        `text` with whitespace outside quoted runs collapsed to single spaces
        and the whole result stripped.
    """
    pieces: list[str] = []
    cursor = 0
    for match in _QUOTED_RUN.finditer(text):
        pieces.append(re.sub(r"\s+", " ", text[cursor : match.start()]))
        pieces.append(match.group())
        cursor = match.end()
    pieces.append(re.sub(r"\s+", " ", text[cursor:]))
    return "".join(pieces).strip()


def _blocks() -> Iterator[tuple[Path, Block]]:
    """Every parsable, named block under the configured corpus roots.

    A file that fails to parse at all is skipped rather than failing the run: this
    differential measures the expression layer, not file-level parse robustness (that
    is ``test_statement_parser_corpus.py``'s and ``parser.conformance``'s job).

    Yields
    ------
    tuple[Path, Block]
        The source file and the block it parsed to.
    """
    for root in _roots():
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.s7dcl")):
            try:
                block = parse_scl_file(path)
            except Exception:  # noqa: BLE001 - a corpus file that fails to parse is skipped, not fatal
                continue
            if block is not None and block.name:
                yield path, block


def test_expression_level_differential_over_the_corpus(
    expression_slices: Callable[[Block], Iterator[tuple[str, list[Token], Expression | None]]],
) -> None:
    """``render(tree)`` against ``translate(scl_text(tokens))``, over every slice found.

    Not yet a pass/fail gate on correctness: ``render`` has visitors for only six of
    the nine expression node types (see the module docstring), so most slices are
    still expected to diverge — either because ``render`` raised
    ``UnsupportedExpression`` for a node it does not cover yet, or because it produced
    something different from the current translator, after both sides are run through
    ``_normalize_whitespace`` (see the module docstring for why the bar is
    whitespace-insensitive and what stays protected inside a quoted run). Both count
    as a divergence here; they are not distinguished, because from a caller's
    perspective they are the same outcome (the new path cannot be trusted for that
    slice yet). What this run reports is the *count*, printed via ``-s`` — the
    progress measure for the tasks that add the remaining visitors, until it reaches
    zero and this test starts asserting that.

    Parameters
    ----------
    expression_slices : Callable[[Block], Iterator[tuple[str, list[Token], Expression | None]]]
        The walker fixture from ``conftest.py``.
    """
    translator = ExpressionTranslator()
    blocks_seen = 0
    slices_seen = 0
    slices_without_tree = 0
    agreements = 0
    divergences: list[str] = []

    for _path, block in _blocks():
        blocks_seen += 1
        for label, tokens, tree in expression_slices(block):
            slices_seen += 1
            if tree is None:
                slices_without_tree += 1
                continue
            text = scl_text(tokens)
            reference = translator.translate(text)
            try:
                candidate = render(tree)
            except UnsupportedExpression:
                divergences.append(label)
                continue
            if _normalize_whitespace(reference) == _normalize_whitespace(candidate):
                agreements += 1
            else:
                divergences.append(label)

    if blocks_seen == 0:
        pytest.skip("PLC_CORPUS_ROOTS is unset or names no readable project")

    # Surfaced via `-s`; not asserted on an absolute value (the corpus is external and
    # regenerated by its owner, so the count moves independently of this repository,
    # and — until every visitor lands — divergences are expected, not a failure).
    print(
        f"\nexpression-level differential: {slices_seen} slice(s) examined across "
        f"{blocks_seen} block(s), {slices_without_tree} without a parsed tree, "
        f"{agreements} agree, {len(divergences)} diverge"
    )
    assert agreements + len(divergences) + slices_without_tree == slices_seen
    assert slices_seen > 0
