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

The comparison is made after ``normalize_whitespace`` on both sides, never before
and never on one side only. ``reference`` is built from ``scl_text(tokens)``, which
joins every token with a single space — the same lossy join ``Region.content`` does
— so a spaced-out reconstruction like ``self.a . b`` differs from the renderer's
compact ``self.a.b`` purely by a space next to the ``.`` (printed by this test's own
``-s`` output as the gap between "agree" and what a strict ``reference == candidate``
would have counted). That gap is the reconstruction's artefact, not a disagreement
about what the expression means, so it is not what this differential is for: the bar
it should apply is semantic-text equivalence, not byte-for-byte equivalence with a
serialisation neither side is trying to reproduce. The rule is a principle, not a
punctuation list — a list was tried twice here and was incomplete both times (first
missing the presence-vs-absence case entirely, then missing ``%``-address spacing and
a fused negative number's own ``-``; a third list would likely miss a fourth thing).
The principle instead: **whitespace between two word characters is meaningful;
everything else is layout, and is removed** — outside a quoted run (see the
``normalize_whitespace`` fixture in ``conftest.py`` and ``TestNormalizeWhitespace``
below). A general whitespace
*collapse* would still be wrong even under this principle — it is a no-op on the
single spaces ``scl_text`` actually produces and would swallow the divergence the
next paragraph documents, which is exactly why removal, not collapsing, is the rule.

One divergence this bar deliberately still counts, and which is not fixed here: the
current translator renders ``#notReady`` as ``self.not Ready`` — invalid Python,
because its ``NOT``-detection matches the identifier's ``not`` prefix by text. That
space sits between two word characters (``t`` and ``R``), so ``normalize_whitespace``
leaves it alone and the tree-based renderer's ``self.notReady`` (``VariableRef``
renders the name whole; there is no bug to reproduce) keeps comparing unequal to it.
That is correct: the bug is real, acknowledged, and intentionally not carried forward
into the new path — a broader normalisation that erased this difference would hide
the finding instead of just not fixing it.

The shipped fixtures are small and written to exercise specific shapes; the real
evidence is production SCL. Those projects are read-only siblings of this repository
and are absent on CI, so this test skips rather than fails when they are not there —
and nothing about them (paths, block names, SCL text, generated Python) is ever
written into this repository. See ``tests/test_no_confidential_references.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from plc_code.parser.expressions import Expression
from plc_code.parser.lexer import Token
from plc_code.parser.models import Block


class TestNormalizeWhitespace:
    """Regression pins for `normalize_whitespace`'s principle, not a punctuation list.

    `normalize_whitespace` (the fixture wrapping `conftest._normalize_whitespace`) is
    used by both differentials in this package; its docstring in `conftest.py` carries
    the full rationale and fix-round history this class pins six properties of:
    whitespace between two word characters is meaningful and kept; every other
    whitespace run is layout and is removed. The third case (`test_fused_negative_...`)
    is the one a wholesale collapse-or-strip would silently swallow — it must keep
    failing on its own, not because some other case happens to fail alongside it.
    """

    def test_dot_spacing_around_a_member_access_is_removed(
        self, normalize_whitespace: Callable[[str], str]
    ) -> None:
        assert normalize_whitespace("self.a . b") == normalize_whitespace("self.a.b")

    def test_bracket_and_dot_spacing_around_indexing_is_removed(
        self, normalize_whitespace: Callable[[str], str]
    ) -> None:
        assert normalize_whitespace("self.arr [ self.i ] . v") == normalize_whitespace("self.arr[self.i].v")

    def test_word_adjacent_spacing_is_not_touched(self, normalize_whitespace: Callable[[str], str]) -> None:
        """The acknowledged `#notReady` -> `self.not Ready` translator bug must keep diverging."""
        assert normalize_whitespace("self.not Ready") != normalize_whitespace("self.notReady")

    def test_whitespace_inside_a_string_literal_is_untouched(
        self, normalize_whitespace: Callable[[str], str]
    ) -> None:
        assert normalize_whitespace("'a  b'") == "'a  b'"

    def test_percent_address_spacing_is_removed(self, normalize_whitespace: Callable[[str], str]) -> None:
        assert normalize_whitespace("% DB150 . % DBX31") == normalize_whitespace("%DB150.%DBX31")

    def test_fused_negative_number_spacing_is_removed(
        self, normalize_whitespace: Callable[[str], str]
    ) -> None:
        assert normalize_whitespace("self.x - 1") == normalize_whitespace("self.x-1")


def test_expression_level_differential_over_the_corpus(
    expression_slices: Callable[[Block], Iterator[tuple[str, list[Token], Expression | None]]],
    corpus_blocks: tuple[tuple[Path, Block], ...],
    expression_slice_diverges: Callable[[list[Token], Expression | None], bool],
) -> None:
    """``render(tree)`` against ``translate(scl_text(tokens))``, over every slice found.

    Not yet a pass/fail gate on correctness: ``render`` has visitors for only six of
    the nine expression node types (see the module docstring), so most slices are
    still expected to diverge — either because ``render`` raised
    ``UnsupportedExpression`` for a node it does not cover yet, or because it produced
    something different from the current translator, after both sides are run through
    ``normalize_whitespace`` (see its docstring in ``conftest.py`` for why the bar
    ignores punctuation-adjacent spacing specifically, what stays protected inside a
    quoted run, and what stays deliberately unprotected) -- the exact per-slice
    judgement made by ``expression_slice_diverges``, reused rather than reimplemented
    here so ``test_generator_native_differential.py``'s unit-level attribution check
    judges every slice exactly the same way this differential does. Both raising and
    producing different text count as a divergence here; they are not distinguished,
    because from a caller's perspective they are the same outcome (the new path cannot
    be trusted for that slice yet). What this run reports is the *count*, printed via
    ``-s`` — the progress measure for the tasks that add the remaining visitors, until
    it reaches zero and this test starts asserting that.

    Parameters
    ----------
    expression_slices : Callable[[Block], Iterator[tuple[str, list[Token], Expression | None]]]
        The walker fixture from ``conftest.py``.
    corpus_blocks : tuple[tuple[Path, Block], ...]
        The session-scoped, once-parsed corpus fixture from ``conftest.py`` — see its
        docstring for why parsing is shared across the session rather than repeated
        per test.
    expression_slice_diverges : Callable[[list[Token], Expression | None], bool]
        The shared per-slice divergence judgement fixture from ``conftest.py``.
    """
    blocks_seen = 0
    slices_seen = 0
    slices_without_tree = 0
    agreements = 0
    divergences: list[str] = []

    for _path, block in corpus_blocks:
        blocks_seen += 1
        for label, tokens, tree in expression_slices(block):
            slices_seen += 1
            if tree is None:
                slices_without_tree += 1
                continue
            if expression_slice_diverges(tokens, tree):
                divergences.append(label)
            else:
                agreements += 1

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
