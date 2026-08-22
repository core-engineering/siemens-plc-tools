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
everything else is layout, and is removed** — outside a quoted run (see
``_normalize_whitespace`` and ``TestNormalizeWhitespace``). A general whitespace
*collapse* would still be wrong even under this principle — it is a no-op on the
single spaces ``scl_text`` actually produces and would swallow the divergence the
next paragraph documents, which is exactly why removal, not collapsing, is the rule.

One divergence this bar deliberately still counts, and which is not fixed here: the
current translator renders ``#notReady`` as ``self.not Ready`` — invalid Python,
because its ``NOT``-detection matches the identifier's ``not`` prefix by text. That
space sits between two word characters (``t`` and ``R``), so ``_normalize_whitespace``
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

import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from plc_code.executor.codegen import ExpressionTranslator
from plc_code.executor.generator import scl_text
from plc_code.executor.renderer import UnsupportedExpression, render
from plc_code.parser.expressions import Expression
from plc_code.parser.lexer import Token
from plc_code.parser.models import Block

#: A single- or double-quoted run, kept intact by `_normalize_whitespace` below.
#: Matches the same two token shapes `expression_parser._parse_primary` reads —
#: `'text'` (a string literal, whose internal spacing is part of what it means)
#: and `"Name"` (a symbol reference, unlikely to carry internal spacing but
#: protected on the same terms, since both are one token in the source and
#: normalisation must not reach inside either).
_QUOTED_RUN = re.compile(r"\"[^\"]*\"|'[^']*'")

#: A run of one or more whitespace characters, outside a quoted run. Whether one
#: is layout (removed) or meaningful (kept) depends only on what sits immediately
#: on either side of it — see `_normalize_whitespace`.
_WHITESPACE_RUN = re.compile(r"\s+")


def _is_word_character(char: str) -> bool:
    """Whether `char` is a letter, digit, or underscore.

    Parameters
    ----------
    char : str
        A single character, or `""` for "off the end of the segment" — which is
        never a word character, so whitespace flush against either end of a
        segment between quoted runs is always layout, never protected.

    Returns
    -------
    bool
        `char.isalnum() or char == "_"` for a non-empty `char`; `False` for `""`.
    """
    return char != "" and (char.isalnum() or char == "_")


def _normalize_whitespace(text: str) -> str:
    """Remove layout whitespace outside quoted runs; keep whitespace between two words.

    `scl_text` reconstructs a token slice by joining every token with a single
    space (mirroring `Region.content`'s own lossy join), so `#a . b` and `#a.b`
    are the same tokens and the same meaning, differing only in whether that
    reconstruction put a space next to the `.`. The renderer works from the tree
    and never introduces such a space, so a difference that is nothing but this
    kind of join-spacing is the reconstruction's artefact, not a divergence in
    what either side computed — see the module docstring for the count this bar
    closes.

    The rule is a principle, not a punctuation list — a list was tried twice here
    and was incomplete both times (see the module docstring). The principle:
    **whitespace between two word characters is meaningful and is kept exactly as
    written; every other whitespace run is layout and is removed entirely** (not
    collapsed to one space — `scl_text` never produces a run longer than one space
    outside a quoted run, so removal and collapsing agree there, but removal is
    also correct for the case a collapse would get wrong: whitespace flush against
    the start or end of a segment, where there is no *word* character on one side
    to collapse a run down to, only nothing).

    A space between two word characters is left exactly as written on both sides,
    so `self.not Ready` and `self.notReady` keep comparing unequal — see the module
    docstring's note on the `#notReady` translator bug this bar must not paper over.

    Text inside a quoted run is left untouched: a string literal's internal
    whitespace is part of its value (`'a  b'` and `'a b'` are different SCL), and a
    quoted symbol name is protected on the same terms even though the corpus is
    not expected to put whitespace inside one. `_QUOTED_RUN` finds both quoting
    conventions; only the text between and around those runs is examined.

    Parameters
    ----------
    text : str
        Either side of the comparison: `scl_text(tokens)` run through
        `ExpressionTranslator.translate`, or `render(tree)`.

    Returns
    -------
    str
        `text` with every whitespace run removed except one with a word character
        immediately on both sides, outside quoted runs; quoted runs unchanged.
    """

    def _strip_layout_whitespace(segment: str) -> str:
        def _replace(match: re.Match[str]) -> str:
            start, end = match.span()
            before = segment[start - 1] if start > 0 else ""
            after = segment[end] if end < len(segment) else ""
            if _is_word_character(before) and _is_word_character(after):
                return match.group()
            return ""

        return _WHITESPACE_RUN.sub(_replace, segment)

    pieces: list[str] = []
    cursor = 0
    for match in _QUOTED_RUN.finditer(text):
        pieces.append(_strip_layout_whitespace(text[cursor : match.start()]))
        pieces.append(match.group())
        cursor = match.end()
    pieces.append(_strip_layout_whitespace(text[cursor:]))
    return "".join(pieces)


class TestNormalizeWhitespace:
    """Regression pins for `_normalize_whitespace`'s principle, not a punctuation list.

    Fix-round history: the first cut of this bar collapsed whitespace *runs*, a
    no-op on the single spaces `scl_text`'s token-join actually produces
    (`'self.a . b'` has one space either side of the `.`, not a run). The second
    cut named the punctuation it stripped whitespace next to and was incomplete —
    it missed `%`-address spacing and a fused negative number's own `-`. Rather
    than try a third list and likely miss a fourth thing, the rule is now the
    principle these six pin: whitespace between two word characters is meaningful
    and kept; every other whitespace run is layout and is removed. The third case
    is the one a wholesale collapse-or-strip would silently swallow — it must keep
    failing on its own, not because some other case happens to fail alongside it.
    """

    def test_dot_spacing_around_a_member_access_is_removed(self) -> None:
        assert _normalize_whitespace("self.a . b") == _normalize_whitespace("self.a.b")

    def test_bracket_and_dot_spacing_around_indexing_is_removed(self) -> None:
        assert _normalize_whitespace("self.arr [ self.i ] . v") == _normalize_whitespace("self.arr[self.i].v")

    def test_word_adjacent_spacing_is_not_touched(self) -> None:
        """The acknowledged `#notReady` -> `self.not Ready` translator bug must keep diverging."""
        assert _normalize_whitespace("self.not Ready") != _normalize_whitespace("self.notReady")

    def test_whitespace_inside_a_string_literal_is_untouched(self) -> None:
        assert _normalize_whitespace("'a  b'") == "'a  b'"

    def test_percent_address_spacing_is_removed(self) -> None:
        assert _normalize_whitespace("% DB150 . % DBX31") == _normalize_whitespace("%DB150.%DBX31")

    def test_fused_negative_number_spacing_is_removed(self) -> None:
        assert _normalize_whitespace("self.x - 1") == _normalize_whitespace("self.x-1")


def test_expression_level_differential_over_the_corpus(
    expression_slices: Callable[[Block], Iterator[tuple[str, list[Token], Expression | None]]],
    corpus_blocks: tuple[tuple[Path, Block], ...],
) -> None:
    """``render(tree)`` against ``translate(scl_text(tokens))``, over every slice found.

    Not yet a pass/fail gate on correctness: ``render`` has visitors for only six of
    the nine expression node types (see the module docstring), so most slices are
    still expected to diverge — either because ``render`` raised
    ``UnsupportedExpression`` for a node it does not cover yet, or because it produced
    something different from the current translator, after both sides are run through
    ``_normalize_whitespace`` (see the module docstring for why the bar ignores
    punctuation-adjacent spacing specifically, what stays protected inside a quoted
    run, and what stays deliberately unprotected). Both count as a divergence here;
    they are not distinguished, because from a caller's
    perspective they are the same outcome (the new path cannot be trusted for that
    slice yet). What this run reports is the *count*, printed via ``-s`` — the
    progress measure for the tasks that add the remaining visitors, until it reaches
    zero and this test starts asserting that.

    Parameters
    ----------
    expression_slices : Callable[[Block], Iterator[tuple[str, list[Token], Expression | None]]]
        The walker fixture from ``conftest.py``.
    corpus_blocks : tuple[tuple[Path, Block], ...]
        The session-scoped, once-parsed corpus fixture from ``conftest.py`` — see its
        docstring for why parsing is shared across the session rather than repeated
        per test.
    """
    translator = ExpressionTranslator()
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
