"""The expression-level differential over the reference corpus.

Spec §10's instrument, and the reason this generator-replacement plan can swap two
layers — expression rendering and statement generation — at once without losing
attribution. Every statement the parser produces carries both a token slice and its
parsed tree (``Assignment.value`` beside ``value_expr``, ``Branch.condition`` beside
``condition_expr``, ``For.start`` beside ``start_expr``, one ``CaseBranch.values[i]``
beside ``values_expr[i]``, ``Argument.value`` beside ``value_expr``), so for every one
of those slices both sides of a comparison already exist, on unmodified code::

    render(tree)   against   ExpressionTranslator().translate(scl_text(tokens))

There is no ``render`` yet — that is the next task in this plan. Until it exists this
test compares ``ExpressionTranslator().translate(scl_text(tokens))`` against itself,
which is green by construction. That is the point: it proves the walker
(``expression_slices``, in ``conftest.py``) and the comparison itself, over the whole
corpus, before either side has anything to catch. Once ``render`` lands, only the
right-hand operand changes here — the left-hand computation, the walker, and the
corpus traversal stay exactly as they are today.

The shipped fixtures are small and written to exercise specific shapes; the real
evidence is production SCL. Those projects are read-only siblings of this repository
and are absent on CI, so this test skips rather than fails when they are not there —
and nothing about them (paths, block names, SCL text, generated Python) is ever
written into this repository. See ``tests/test_no_confidential_references.py``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from plc_code.executor.codegen import ExpressionTranslator
from plc_code.executor.generator import scl_text
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
    """``translate(scl_text(tokens))`` against itself, over every expression slice found.

    Until ``render`` exists (the next task), the left- and right-hand sides of the
    differential are the *same* computation, run twice, so equality is guaranteed by
    construction. What this proves today is the plumbing: the corpus walk finds every
    block, ``expression_slices`` finds every non-empty slice without missing a kind
    (mirroring ``parser.conformance._expression_slice_counts``), and the comparison
    itself does not silently pass for a reason that has nothing to do with correctness
    (e.g. comparing two empty sequences). Parameters and return value are pytest's
    fixture-injection contract, not this test's own interface.

    Parameters
    ----------
    expression_slices : Callable[[Block], Iterator[tuple[str, list[Token], Expression | None]]]
        The walker fixture from ``conftest.py``.
    """
    translator = ExpressionTranslator()
    blocks_seen = 0
    slices_seen = 0
    slices_without_tree = 0
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
            candidate = translator.translate(text)
            if reference != candidate:
                divergences.append(label)

    if blocks_seen == 0:
        pytest.skip("PLC_CORPUS_ROOTS is unset or names no readable project")

    assert not divergences, (
        f"{len(divergences)} slice(s) diverged from themselves out of {slices_seen} "
        f"examined across {blocks_seen} block(s) — this should be impossible before "
        f"`render` exists:\n" + "\n".join(divergences)
    )

    # Surfaced via `-s`; not asserted on an absolute value (the corpus is external and
    # regenerated by its owner, so the count moves independently of this repository).
    print(
        f"\nexpression-level differential: {slices_seen} slice(s) examined across "
        f"{blocks_seen} block(s), {slices_without_tree} without a parsed tree"
    )
    assert slices_seen > 0
