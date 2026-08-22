"""Shared pytest fixtures for plc-code tests."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from plc_code.executor.codegen import ExpressionTranslator
from plc_code.executor.generator import _has_closing_parenthesis, _map_string_constants, scl_text
from plc_code.executor.renderer import UnsupportedExpression, render
from plc_code.parser import parse_scl_file
from plc_code.parser.expressions import Expression, Index, Member
from plc_code.parser.lexer import Token
from plc_code.parser.models import Block
from plc_code.parser.statement_parser import parse_statements
from plc_code.parser.statements import Assignment, Call, Case, For, If, Statement, While


def _statement_expression_slices(
    statements: list[Statement], label_prefix: str
) -> Iterator[tuple[str, list[Token], Expression | None]]:
    """Yield one entry per non-empty expression-bearing slice, recursing into nested bodies.

    Mirrors ``plc_code.parser.conformance._expression_slice_counts`` field for field and
    recursion site for recursion site — an ``If``'s ``branches`` **and its separate**
    ``else_body``, a ``Case``'s ``branches`` **and its separate** ``default``, a ``For``'s
    and a ``While``'s ``body`` — so matching that enumeration is how this walker is known
    not to miss a slice kind, rather than inventing its own and going quiet on one.

    An empty slice (e.g. a ``For`` loop with no ``BY`` clause) never held an expression to
    parse and is not yielded at all, same as ``_expression_slice_counts`` does not count it.

    Parameters
    ----------
    statements : list[Statement]
        Statements to walk, typically ``ParseResult.statements`` for one region or network.
    label_prefix : str
        Human-readable path to these statements (block, network, region), prepended to
        each yielded label so a divergence can be attributed to where it came from.

    Yields
    ------
    tuple[str, list[Token], Expression | None]
        A label identifying the slice, its token slice, and its parsed tree (``None`` when
        the slice could not be read as an expression).
    """
    for statement in statements:
        if isinstance(statement, Assignment):
            if statement.target:
                yield f"{label_prefix}: Assignment.target", statement.target, statement.target_expr
            if statement.value:
                yield f"{label_prefix}: Assignment.value", statement.value, statement.value_expr
        elif isinstance(statement, Call):
            if statement.callee:
                yield f"{label_prefix}: Call.callee", statement.callee, statement.callee_expr
            for index, argument in enumerate(statement.arguments):
                if argument.value:
                    yield (
                        f"{label_prefix}: Call.arguments[{index}].value",
                        argument.value,
                        argument.value_expr,
                    )
        elif isinstance(statement, If):
            for index, branch in enumerate(statement.branches):
                if branch.condition:
                    yield (
                        f"{label_prefix}: If.branches[{index}].condition",
                        branch.condition,
                        branch.condition_expr,
                    )
                yield from _statement_expression_slices(
                    branch.body, f"{label_prefix}: If.branches[{index}].body"
                )
            yield from _statement_expression_slices(statement.else_body, f"{label_prefix}: If.else_body")
        elif isinstance(statement, Case):
            if statement.selector:
                yield f"{label_prefix}: Case.selector", statement.selector, statement.selector_expr
            for index, case_branch in enumerate(statement.branches):
                for value_index, value in enumerate(case_branch.values):
                    if not value:
                        continue
                    value_expr = (
                        case_branch.values_expr[value_index]
                        if value_index < len(case_branch.values_expr)
                        else None
                    )
                    yield (
                        f"{label_prefix}: Case.branches[{index}].values[{value_index}]",
                        value,
                        value_expr,
                    )
                yield from _statement_expression_slices(
                    case_branch.body, f"{label_prefix}: Case.branches[{index}].body"
                )
            yield from _statement_expression_slices(statement.default, f"{label_prefix}: Case.default")
        elif isinstance(statement, For):
            if statement.start:
                yield f"{label_prefix}: For.start", statement.start, statement.start_expr
            if statement.end:
                yield f"{label_prefix}: For.end", statement.end, statement.end_expr
            if statement.step:
                yield f"{label_prefix}: For.step", statement.step, statement.step_expr
            yield from _statement_expression_slices(statement.body, f"{label_prefix}: For.body")
        elif isinstance(statement, While):
            if statement.condition:
                yield f"{label_prefix}: While.condition", statement.condition, statement.condition_expr
            yield from _statement_expression_slices(statement.body, f"{label_prefix}: While.body")


def _block_expression_slices(block: Block) -> Iterator[tuple[str, list[Token], Expression | None]]:
    """Every expression-bearing slice of a block: every network and every region.

    Walks ``block.networks[*].regions`` (parsing each region's ``tokens``) and each
    network's own out-of-region ``tokens``, same two populations
    ``parser.conformance.build_report`` measures.

    Parameters
    ----------
    block : Block
        A parsed block.

    Yields
    ------
    tuple[str, list[Token], Expression | None]
        Same shape as ``_statement_expression_slices``, labelled with the block name,
        network index, and region name (or "outside any region") the slice came from.
    """
    for index, network in enumerate(block.networks):
        for region in network.regions:
            if not region.tokens:
                continue
            result = parse_statements(region.tokens)
            label_prefix = f"{block.name} network[{index}] region {region.name!r}"
            yield from _statement_expression_slices(result.statements, label_prefix)
        if network.tokens:
            result = parse_statements(network.tokens)
            label_prefix = f"{block.name} network[{index}] outside any region"
            yield from _statement_expression_slices(result.statements, label_prefix)


@pytest.fixture
def expression_slices() -> Callable[[Block], Iterator[tuple[str, list[Token], Expression | None]]]:
    """Expose the expression-slice walker as a fixture.

    A later differential needs this same walker from a second test module; this
    repository forbids ``__init__.py`` in a ``tests/`` directory (see ``CLAUDE.md``
    §6), so a plain cross-file import is not the convention here — a fixture is.

    Returns
    -------
    Callable[[Block], Iterator[tuple[str, list[Token], Expression | None]]]
        ``_block_expression_slices``, so a test calls ``expression_slices(block)`` for
        one ``(label, tokens, tree)`` entry per non-empty expression-bearing slice.
    """
    return _block_expression_slices


@pytest.fixture
def statement_expression_slices() -> (
    Callable[[list[Statement], str], Iterator[tuple[str, list[Token], Expression | None]]]
):
    """Expose the per-unit expression-slice walker as a fixture.

    The per-unit counterpart to ``expression_slices`` above: that fixture walks a
    whole ``Block`` (every network and region); this one walks a single already-parsed
    statement list (one region, or one network's own out-of-region tokens) — exactly
    the granularity ``test_generator_native_differential.py``'s unit-level differential
    needs to ask "which expression slices live inside the one unit that just diverged?"
    without re-parsing the block itself.

    Returns
    -------
    Callable[[list[Statement], str], Iterator[tuple[str, list[Token], Expression | None]]]
        ``_statement_expression_slices``, so a test calls
        ``statement_expression_slices(statements, label_prefix)`` for one
        ``(label, tokens, tree)`` entry per non-empty expression-bearing slice found by
        walking ``statements`` (recursing into nested bodies).
    """
    return _statement_expression_slices


def _corpus_roots() -> list[Path]:
    """Corpus roots, from ``PLC_CORPUS_ROOTS`` (``os.pathsep``-separated).

    Read from the environment rather than written down: the directories are
    customer projects and this repository is public.

    Returns
    -------
    list[Path]
        One entry per non-empty segment of ``PLC_CORPUS_ROOTS``.
    """
    raw = os.environ.get("PLC_CORPUS_ROOTS", "")
    return [Path(part) for part in raw.split(os.pathsep) if part]


@pytest.fixture(scope="session")
def corpus_blocks() -> tuple[tuple[Path, Block], ...]:
    """Every parsable, named block under ``PLC_CORPUS_ROOTS``, parsed exactly once per session.

    ``parse_scl_file`` over the ~650 corpus files is the overwhelming majority of the
    expression- and statement-level differentials' wall time (measured at roughly 80s
    of an ~85s run) — parsing is deterministic and every differential test in this
    session wants the same blocks, so paying that cost once here and sharing the
    result is a session-scope fixture's textbook use, not a premature optimisation.

    Held in memory only, never written to disk: a parsed ``Block`` carries customer
    identifiers (block names, tag names, DB names) from a project this repository
    must never leak into (see ``tests/test_no_confidential_references.py``), so this
    fixture must not pickle, cache, or otherwise persist its result anywhere outside
    the pytest process's memory for the duration of the session.

    A file that fails to parse at all is skipped rather than failing the run: this
    fixture measures the expression/statement layers, not file-level parse
    robustness (that is ``test_statement_parser_corpus.py``'s and
    ``parser.conformance``'s job).

    Returns
    -------
    tuple[tuple[Path, Block], ...]
        The source file and the block it parsed to, one entry per parsable named
        block, in ``rglob`` order per root. A tuple, not a list: every consumer
        shares this same session-scoped result, so nothing here may be mutated by a
        test that reads it — returning an immutable container makes an accidental
        in-place mutation (``.append``, ``.sort``, ...) fail loudly instead of
        corrupting every other test's view of the corpus for the rest of the
        session.
    """
    blocks: list[tuple[Path, Block]] = []
    for root in _corpus_roots():
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.s7dcl")):
            try:
                block = parse_scl_file(path)
            except Exception:  # noqa: BLE001 - a corpus file that fails to parse is skipped, not fatal
                continue
            if block is not None and block.name:
                blocks.append((path, block))
    return tuple(blocks)


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

    `scl_text` (`plc_code.executor.generator`) reconstructs a token slice by joining
    every token with a single space (mirroring `Region.content`'s own lossy join), so
    `#a . b` and `#a.b` are the same tokens and the same meaning, differing only in
    whether that reconstruction put a space next to the `.`. A tree-driven renderer
    never introduces such a space, so a difference that is nothing but this kind of
    join-spacing is the reconstruction's artefact, not a divergence in what either side
    computed — see `test_renderer_differential.py`'s module docstring, which this
    principle was first written for, for the full rationale and fix-round history.

    The rule is a principle, not a punctuation list: **whitespace between two word
    characters is meaningful and is kept exactly as written; every other whitespace run
    is layout and is removed entirely** (not collapsed to one space — `scl_text` never
    produces a run longer than one space outside a quoted run, so removal and collapsing
    agree there, but removal is also correct for the case a collapse would get wrong:
    whitespace flush against the start or end of a segment, where there is no *word*
    character on one side to collapse a run down to, only nothing).

    A space between two word characters is left exactly as written on both sides, so
    `self.not Ready` and `self.notReady` keep comparing unequal — the acknowledged
    `#notReady` → `self.not Ready` translator bug (see `test_renderer_differential.py`)
    must not be papered over by this normalisation.

    Text inside a quoted run is left untouched: a string literal's internal whitespace
    is part of its value (`'a  b'` and `'a b'` are different SCL), and a quoted symbol
    name is protected on the same terms even though the corpus is not expected to put
    whitespace inside one. `_QUOTED_RUN` finds both quoting conventions; only the text
    between and around those runs is examined.

    Parameters
    ----------
    text : str
        Either side of a comparison built from `scl_text(tokens)` (directly, or via a
        translator/generator run over it), or from a tree-driven `render`.

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


@pytest.fixture
def normalize_whitespace() -> Callable[[str], str]:
    """Expose `_normalize_whitespace` as a fixture.

    A second differential (`test_generator_native_differential.py`) needs the same
    layout-whitespace-removal principle this module's docstring on `_normalize_whitespace`
    explains at length; this repository forbids `__init__.py` in a `tests/` directory
    (see `CLAUDE.md` §6), so a plain cross-file import is not the convention here — a
    fixture is, matching `expression_slices` above.

    Returns
    -------
    Callable[[str], str]
        `_normalize_whitespace`.
    """
    return _normalize_whitespace


def _expression_slice_diverges(
    tokens: list[Token],
    tree: Expression | None,
    translator: ExpressionTranslator,
    string_constants: dict[str, int] | None = None,
) -> bool:
    """Whether one expression slice's tree-rendered Python disagrees with the current translator's.

    The single per-slice judgement both ``test_renderer_differential.py``'s corpus
    differential and ``test_generator_native_differential.py``'s unit-level attribution
    check are built from, kept in one place so the two never drift into judging the same
    slice two different ways. A slice with no parsed tree never disagrees here (there is
    nothing to render) — a caller that also tracks "slices without a tree" as its own
    category, the way the expression-level differential does, checks ``tree is None``
    itself before calling this.

    ``string_constants`` is threaded through both sides the same way
    ``generator.py`` threads it for a real ``Assignment``: the reference text is run
    through ``generator._map_string_constants`` before ``translate`` (mirroring
    ``_generate_assignment_via_dispatcher``'s own preprocessing), and the candidate is
    rendered via ``render(tree, string_constants)`` (mirroring
    ``_generate_assignment``'s native call). Without this, a slice whose divergence
    only shows up once a string constant is substituted would compare as "agrees" here
    while the generator-level comparison — which always has ``string_constants`` in
    play — could still disagree, so this parameter exists precisely so the classifier
    answers the same question the differential asks, not a related but narrower one.

    Parameters
    ----------
    tokens : list[Token]
        The slice's raw token run, as a statement node carries it (e.g.
        ``Assignment.value``).
    tree : Expression | None
        The slice's parsed tree, or ``None`` when the slice could not be read as an
        expression.
    translator : ExpressionTranslator
        The reference (text-path) translator to compare against.
    string_constants : dict[str, int] | None, optional
        Mapping from a quoted string-constant literal to its assigned integer, as
        ``SCLTranspiler._collect_string_constants`` produces and ``generate_statements``
        accepts. ``None`` (the default) applies no substitution to either side, matching
        every existing caller's prior behaviour exactly (``_map_string_constants``
        is a no-op for a falsy mapping, and ``render``'s own default is ``None``).

    Returns
    -------
    bool
        True when ``tree`` is not ``None`` and either :func:`render` raised
        :class:`~plc_code.executor.renderer.UnsupportedExpression` or its output,
        after :func:`_normalize_whitespace`, differs from the translator's; False
        otherwise (including when ``tree`` is ``None``).
    """
    if tree is None:
        return False
    text = _map_string_constants(scl_text(tokens), string_constants)
    reference = translator.translate(text)
    try:
        candidate = render(tree, string_constants)
    except UnsupportedExpression:
        return True
    return _normalize_whitespace(reference) != _normalize_whitespace(candidate)


@pytest.fixture
def expression_slice_diverges() -> Callable[[list[Token], Expression | None, dict[str, int] | None], bool]:
    """Expose ``_expression_slice_diverges`` as a fixture, with its own ``ExpressionTranslator``.

    One ``ExpressionTranslator`` is built once per test (mirroring how
    ``test_expression_level_differential_over_the_corpus`` built one and reused it
    across every slice) rather than once per call, since ``translate`` depends only on
    its argument, not on accumulated state.

    Returns
    -------
    Callable[[list[Token], Expression | None, dict[str, int] | None], bool]
        A closure over one ``ExpressionTranslator`` calling ``_expression_slice_diverges``,
        so a test calls ``expression_slice_diverges(tokens, tree)`` — or
        ``expression_slice_diverges(tokens, tree, string_constants)`` — for one slice's
        divergence verdict. ``string_constants`` defaults to ``None`` (no substitution),
        so every caller written before this parameter existed is unaffected.
    """
    translator = ExpressionTranslator()

    def diverges(
        tokens: list[Token], tree: Expression | None, string_constants: dict[str, int] | None = None
    ) -> bool:
        return _expression_slice_diverges(tokens, tree, translator, string_constants)

    return diverges


@pytest.fixture
def fb_call_argument_would_truncate_old_path() -> Callable[[Call], bool]:
    """The fifth attributed residual class's own classifier: does this `Call` contain the shape

    `translate_fb_call`'s paren-truncation bug fires on?

    `generator._generate_fb_instance_call` used to fall back to the text dispatcher on this
    exact shape (an argument's raw value containing a closing parenthesis -- see
    `generator._has_closing_parenthesis`'s own docstring); Task 9 step 3 removes that guard
    and renders the call whole instead, so a `Call` matching this shape now genuinely
    diverges from `_generate_statements_via_strings` (which still truncates, via the
    now-doomed `translate_fb_call`). That divergence is not a new generator bug -- it is the
    old path's own acknowledged truncation bug, not reproduced on purpose -- so the unit-level
    differential's attribution (`test_generator_native_differential.py`) accepts it as
    explained, the same way an expression-level residual explains an `Assignment`/header
    divergence, using this classifier instead of `expression_slice_diverges` (which, run on
    the argument's own isolated token slice, would not flag this shape at all: translating
    just the one argument's own text in isolation is not what triggers the bug -- the bug is
    in how the whole call's text gets re-parsed by one regex).

    Returns
    -------
    Callable[[Call], bool]
        A closure wrapping `generator._has_closing_parenthesis`, so a test calls
        `fb_call_argument_would_truncate_old_path(call)` for one `Call` statement's verdict:
        True when any of its arguments' raw value tokens would have tripped
        `translate_fb_call`'s truncation.
    """

    def check(call: Call) -> bool:
        return any(_has_closing_parenthesis(argument.value) for argument in call.arguments)

    return check


@pytest.fixture
def fb_call_callee_confuses_old_regex() -> Callable[[Call], bool]:
    """Classifier for the *existing* "bare call `:=` mangled to `==`" residual class, reached
    here through a `Call` statement's own callee rather than through a bare `FunctionCall`
    expression.

    `translate_fb_call`'s own regex (`#(\\w+)\\s*\\(`) only recognises a callee spelled as a
    bare `#name` immediately followed by `(` -- an `Index` callee (`#arms[#i](...)`) or a
    `Member` callee (`"db".TON(...)`) never matches it, so the old dispatcher falls through to
    translating the *whole* call as one bare expression instead. That expression path runs
    every argument's `:=` through `OPERATOR_MAP` (`:=` -> `=`, then the standalone-`=`-to-`==`
    rule catches the result) and discards each `:=`/`=>` name, both silently -- the same
    `OPERATOR_MAP`/standalone-`=` mangling `test_renderer_calls.py` already pins for a bare
    *builtin* `FunctionCall` used as an expression, not a new bug.

    `generator._generate_fb_instance_call` (Task 9 step 3) widens its callee shapes to accept
    `Index`/`Member` too, rendering the callee itself through `render` and each `:=`/`=>`
    argument correctly by name -- so a `Call` with this callee shape now genuinely diverges
    from the old dispatcher whenever it binds at least one named argument. Neither
    `Call.callee` nor any `Call.arguments[i].value` slice diverges on its own under
    `expression_slice_diverges` (the callee renders identically either way, and so does each
    argument's bare value -- the difference is only in how the *call syntax itself* wires
    names to values), so this classifier is consulted instead, exactly like
    `fb_call_argument_would_truncate_old_path` above.

    Returns
    -------
    Callable[[Call], bool]
        A closure testing `call.callee_expr`'s type, so a test calls
        `fb_call_callee_confuses_old_regex(call)` for one `Call` statement's verdict: True
        when its callee is an `Index` or a `Member` (the two shapes `translate_fb_call`'s own
        regex cannot recognise as a call at all).
    """

    def check(call: Call) -> bool:
        return isinstance(call.callee_expr, Index | Member)

    return check


@pytest.fixture
def simple_xml_tags_dir(tmp_path: Path) -> Path:
    """Create a minimal XML tags directory in TIA Portal V21 format.

    The fixture produces one ``Station.xml`` file with five I/O tags:

    * ``DI_LCP_LAMP_TEST``   — instrument tag ``DI-001``  at ``%E2.6``
    * ``DI_LCP_ALARM_ACK``   — instrument tag ``DI-002``  at ``%E2.7``
    * ``DI_LCP_SLOW_SPEED``  — instrument tag ``DI-003``  at ``%E2.9``
    * ``DI_LCP_HIGH_TEMP1``  — instrument tag ``DI-004``  at ``%E3.0``
    * ``DI_LCP_HIGH_TEMP2``  — instrument tag ``DI-005``  at ``%E3.1``

    Parameters
    ----------
    tmp_path : Path
        Pytest-provided temporary directory.

    Returns
    -------
    Path
        Directory containing one TIA Portal V21 XML tag table file.
    """
    d = tmp_path / "tags"
    d.mkdir()
    (d / "Station.xml").write_text(
        """\
<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Tags.PlcTagTable>
    <AttributeList><Name>Station</Name></AttributeList>
    <ObjectList>

      <SW.Tags.PlcTag>
        <AttributeList>
          <DataTypeName>Bool</DataTypeName>
          <LogicalAddress>%E2.6</LogicalAddress>
          <Name>DI_LCP_LAMP_TEST</Name>
        </AttributeList>
        <ObjectList>
          <MultilingualText CompositionName="Comment">
            <ObjectList>
              <MultilingualTextItem>
                <AttributeList>
                  <Culture>en-US</Culture>
                  <Text>010-DI-001</Text>
                </AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
        </ObjectList>
      </SW.Tags.PlcTag>

      <SW.Tags.PlcTag>
        <AttributeList>
          <DataTypeName>Bool</DataTypeName>
          <LogicalAddress>%E2.7</LogicalAddress>
          <Name>DI_LCP_ALARM_ACK</Name>
        </AttributeList>
        <ObjectList>
          <MultilingualText CompositionName="Comment">
            <ObjectList>
              <MultilingualTextItem>
                <AttributeList>
                  <Culture>en-US</Culture>
                  <Text>010-DI-002</Text>
                </AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
        </ObjectList>
      </SW.Tags.PlcTag>

      <SW.Tags.PlcTag>
        <AttributeList>
          <DataTypeName>Bool</DataTypeName>
          <LogicalAddress>%E2.9</LogicalAddress>
          <Name>DI_LCP_SLOW_SPEED</Name>
        </AttributeList>
        <ObjectList>
          <MultilingualText CompositionName="Comment">
            <ObjectList>
              <MultilingualTextItem>
                <AttributeList>
                  <Culture>en-US</Culture>
                  <Text>010-DI-003</Text>
                </AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
        </ObjectList>
      </SW.Tags.PlcTag>

      <SW.Tags.PlcTag>
        <AttributeList>
          <DataTypeName>Bool</DataTypeName>
          <LogicalAddress>%E3.0</LogicalAddress>
          <Name>DI_LCP_HIGH_TEMP1</Name>
        </AttributeList>
        <ObjectList>
          <MultilingualText CompositionName="Comment">
            <ObjectList>
              <MultilingualTextItem>
                <AttributeList>
                  <Culture>en-US</Culture>
                  <Text>010-DI-004</Text>
                </AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
        </ObjectList>
      </SW.Tags.PlcTag>

      <SW.Tags.PlcTag>
        <AttributeList>
          <DataTypeName>Bool</DataTypeName>
          <LogicalAddress>%E3.1</LogicalAddress>
          <Name>DI_LCP_HIGH_TEMP2</Name>
        </AttributeList>
        <ObjectList>
          <MultilingualText CompositionName="Comment">
            <ObjectList>
              <MultilingualTextItem>
                <AttributeList>
                  <Culture>en-US</Culture>
                  <Text>010-DI-005</Text>
                </AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
        </ObjectList>
      </SW.Tags.PlcTag>

    </ObjectList>
  </SW.Tags.PlcTagTable>
</Document>
""",
        encoding="utf-8",
    )
    return d


@pytest.fixture
def simple_scl_dir(tmp_path: Path) -> Path:
    """Create a minimal SCL directory exercising both FB declaration forms.

    The fixture produces one ``PumpControl.s7dcl`` file with:

    * ``motorStartCmd``   — instance of ``"MotorStarter"``  (quoted, legacy form)
    * ``pumpFaultAlarm``  — instance of ``_.MotorStarter``  (library-ref form)

    This covers both declaration syntaxes that the resolver must handle:
    quoted (user-defined FB) and underscore-dot library reference (TIA Portal library FB).

    Parameters
    ----------
    tmp_path : Path
        Pytest-provided temporary directory.

    Returns
    -------
    Path
        Directory containing one TIA Portal V21 SCL file.
    """
    d = tmp_path / "scl"
    d.mkdir()
    (d / "PumpControl.s7dcl").write_text(
        """FUNCTION_BLOCK "PumpControl"
{ S7_Optimized := 'TRUE' }
VERSION : 0.1
VAR
    motorStartCmd : "MotorStarter";       // quoted (legacy)
    pumpFaultAlarm : _.MotorStarter;      // library ref
END_VAR
BEGIN
    motorStartCmd(Trigger := input."DI-001",
                  Acknowledge := input.alarmAck,
                  alarmReset := input.alarmReset);
    pumpFaultAlarm(alarmTrigger := input.pumpFault,
                   alarmAcknowledge := TRUE,
                   alarmReset := input.alarmReset);
END_FUNCTION_BLOCK
""",
        encoding="utf-8",
    )
    return d
