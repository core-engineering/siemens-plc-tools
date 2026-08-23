"""Permanent regression coverage for defects the deleted text-path translator had.

Before this repository switched to generating Python from the statement AST
(``generate_statements``), a now-deleted ``ControlFlowTranslator`` rewrote a
region's flattened text with regular expressions. A one-time differential sweep
of the AST path against that text path, run over 646 real production blocks
before the switch, found 45 diverging code units, classified into seven root
causes -- every one of them a bug in the deleted path, never a case where the
AST path was wrong. That sweep, and the text path it compared against, are gone
(deleted alongside ``ControlFlowTranslator`` itself): the differential was a
ratchet on the *count* of known divergences and carried no block names (this
repository is public), so once the old path was deleted the specific evidence
for each of the seven defect shapes would have gone with it.

This module keeps that evidence alive independently of the deleted path. Each
test below feeds a small, fully generic (no customer, project, or block name)
SCL snippet through the statement AST -- ``tokenize`` -> ``parse_statements`` ->
``generate_statements`` -- the same pipeline ``transpile`` now uses, and asserts
the *correct* Python it produces, plus a targeted assertion on the specific
thing the deleted path used to drop, garble, or leak, so a future regression
names itself instead of only showing up as "the list changed".

Six of the seven snippets here are transcribed unchanged from the verified
minimal reproductions recorded in the original differential task's report (each
one was run there through both paths and the shown old/new output confirmed
real, not guessed). The seventh (see
``test_a_multi_value_case_label_with_an_inline_if_body``) was described there
only in prose, without a concrete snippet -- it was reconstructed from that
description and independently re-verified here against the deleted path's own
source (while it still existed) before being written down as a permanent test.
"""

from __future__ import annotations

from plc_code.executor.generator import generate_statements
from plc_code.executor.transpiler import transpile_block
from plc_code.parser.lexer import TokenType, tokenize, tokenize_with_newlines
from plc_code.parser.parser import SCLParser
from plc_code.parser.statement_parser import parse_statements
from plc_code.parser.statements import Statement


def _statements(source: str) -> list[Statement]:
    """Tokenize and parse a snippet of SCL statements.

    Extends the helper used in ``test_generator_statements.py`` by also dropping
    comment tokens (``COMMENT`` / ``BLOCK_COMMENT``) before parsing. That mirrors
    what the real pipeline does: ``Network.tokens`` / ``Region.tokens`` (built in
    ``parser.py``) already exclude comment tokens before the statement parser ever
    sees them, which is the whole reason a comment-only snippet parses to zero
    statements instead of failing. Without the same filtering here, a pure-comment
    snippet would raise instead of demonstrating that.

    Parameters
    ----------
    source : str
        Raw SCL statement text (not a full ``FUNCTION_BLOCK`` -- just the body).

    Returns
    -------
    list[Statement]
        The parsed statement AST.
    """
    tokens = [
        t
        for t in tokenize(source)
        if t.type not in (TokenType.EOF, TokenType.COMMENT, TokenType.BLOCK_COMMENT)
    ]
    result = parse_statements(tokens)
    assert result.errors == [], result.errors
    return result.statements


def test_a_case_no_longer_drops_its_leading_branch() -> None:
    """Old's ``CASE`` -> ``if``/``elif`` translation lost the label written first.

    The old text path's ``CASE`` block reader glued the ``CASE ... OF`` header and
    the first branch's label onto the same reconstructed line whenever nothing
    separated them, then discarded that whole line's first label when starting the
    ``if``/``elif`` chain -- the next label it saw was treated as the *first* ``if``,
    silently losing the branch that came first in the source (real, sanitised
    example: a two-state alarm cascade whose ``NO_ALARM`` branch vanished from both
    of its ``CASE`` statements). The AST path parses the ``CASE`` as one structure
    up front and has no such off-by-one -- it emits every branch, in source order.
    """
    source = """
        CASE #state OF
            #IDLE:
                #state := #RUN;
            #RUN:
                #state := #IDLE;
        END_CASE;
    """
    lines = generate_statements(_statements(source))
    assert lines == [
        "if self.state == self.IDLE:",
        "    self.state = self.RUN",
        "elif self.state == self.RUN:",
        "    self.state = self.IDLE",
    ]
    # The specific thing the old path dropped: an `if` branch keyed on IDLE, ahead
    # of the RUN branch, with RUN's own arm downgraded from `if` to `elif`.
    assert lines[0] == "if self.state == self.IDLE:"
    assert "elif self.state == self.RUN:" in lines


def test_an_empty_else_no_longer_emits_a_stray_pass() -> None:
    """A bare ``;`` as an ``ELSE`` body is a no-op branch; old still rendered it.

    When an SCL ``IF``'s ``ELSE`` arm is a single empty statement (``;``), the old
    path still emitted a Python ``else:`` header followed by ``pass`` -- a
    do-nothing branch that adds two lines of dead control flow with no effect. The
    AST path parses the ``ELSE`` arm to zero statements and correctly omits the
    branch entirely rather than manufacturing a placeholder for it.
    """
    source = """
        IF #flag = FALSE THEN
            #x := TRUE;
        ELSE
            ;
        END_IF;
        #y := 1;
    """
    lines = generate_statements(_statements(source))
    assert lines == [
        "if self.flag == False:",
        "    self.x = True",
        "self.y = 1",
    ]
    # The specific thing the old path added and the new path correctly omits.
    assert "else:" not in lines
    assert "pass" not in lines


def test_a_comment_only_snippet_emits_nothing() -> None:
    """A block comment with no code was passed through by old as a literal line.

    A region (or network) whose only content is a ``(* ... *)`` block comment is not
    a statement at all -- there is nothing to execute. The old path's line-based
    reader nonetheless emitted the raw comment text as one more line of "generated
    Python" (which is not valid Python and does nothing useful downstream). The new
    path never sees the comment as a token in the first place.

    Unlike the other tests in this module, this one goes through ``transpile_block``
    on a real, fully parsed block rather than ``generate_statements(_statements(...))``:
    ``_statements`` filters ``COMMENT``/``BLOCK_COMMENT`` itself, which would make this
    test pass even if the real pipeline (``Region.tokens``, built by ``parser.py``,
    filtering those tokens before the statement parser ever runs) regressed. Routing
    through the real block guards the pipeline, not the test helper.
    """
    source = """
FUNCTION_BLOCK "CommentOnlyProbe"
    VAR_INPUT
        a : Int;
    END_VAR
    VAR_OUTPUT
        b : Int;
    END_VAR
    {{ S7_Language := "SCL" }}
    NETWORK
        REGION Logic
            (* This block does a thing. *)
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
    block = SCLParser(tokenize_with_newlines(source)).parse()
    result = transpile_block(block)
    assert result.success, result.errors
    # The specific thing the old path leaked: the comment text itself must not
    # appear anywhere in the generated output.
    assert "This block does a thing" not in result.python_code


def test_an_empty_bodied_if_no_longer_vanishes_entirely() -> None:
    """Old showed *no trace at all* of an ``IF`` whose body produced zero lines.

    Task 8's report reaches this defect through an ``IF`` whose entire body is a
    nested ``REGION`` (a common way to group a single action under a heading): the
    ``REGION``'s content is parsed and translated as its own separate code unit, so
    from the surrounding ``IF``'s point of view its own body is empty. That is not
    reachable through ``generate_statements(_statements(...))`` alone (there is no
    ``REGION`` machinery at this level), but a plain ``IF`` with a genuinely empty
    body hits the identical underlying bug: the old path's line-based ``IF`` reader
    matches ``IF cond THEN`` and, finding nothing but ``END_IF`` glued onto the same
    line after ``THEN`` (no ``;`` or comment ever separated them), treats that
    ``END_IF`` text as the branch's *inline body* rather than as the statement's
    terminator -- so the loop runs out of input before it ever reaches the code path
    that emits the header, and nothing is emitted at all: not even the ``pass``
    fallback the old path uses for every other empty branch (see the ``ELSE``
    no-op test above). The AST path keeps the ``IF`` header regardless of whether
    its body is empty, exactly as it does when the body is a whole nested region --
    and, unlike the old path, backs that header with an explicit ``pass``: a header
    with nothing indented under it is not valid Python, and a comment-only branch
    (the real-world shape of "empty body") is ordinary SCL, not a corner case.
    """
    source = "IF #a AND #b THEN END_IF;"
    lines = generate_statements(_statements(source))
    # The specific thing the old path showed no trace of at all: the `if` header
    # must survive on its own, backed by a `pass` so the module still compiles.
    assert lines == ["if self.a and self.b:", "    pass"]


def test_dead_code_inside_a_comment_is_no_longer_executed() -> None:
    """Old leaked commented-out SCL as if it were live code; new treats it as prose.

    A multi-line ``(* ... *)`` comment whose inner lines happen to look like real
    assignment statements is not code -- by definition, everything between the
    delimiters is disabled. The old path's comment handling lost track of where the
    comment ended, and translated the enclosed dead statements as if they were live,
    wrapping them with the literal ``(*``/``*)`` boundary lines left untranslated
    around them. This is worse than simply dropping comment text (the previous
    test): it is comment *content* leaking through as *executable-looking* output.
    The new path treats comment tokens as invisible to the statement parser, so the
    whole thing -- boundary and enclosed dead assignments alike -- produces nothing.
    """
    source = """
        (* disabled block, not in use

        #x := 1;
        #y := 2;

        *)
    """
    lines = generate_statements(_statements(source))
    assert lines == []
    # The specific thing the old path executed: neither dead assignment, nor the
    # comment's boundary markers, may appear in the generated output.
    assert not any("self.x" in line or "self.y" in line for line in lines)
    assert not any("(*" in line or "*)" in line for line in lines)


def test_a_compound_assignment_is_desugared_instead_of_garbled() -> None:
    """Old mistranslated ``+=`` into a broken, non-executing token sequence.

    SCL's compound-assignment operator (``#i += 1;``) needs to be desugared into an
    ordinary Python assignment (``self.i = self.i + 1``). The old text path's
    operator handling instead produced ``self.i + == 1`` -- the compound operator
    split apart and reassembled in the wrong order, a token sequence that is not
    valid Python and would raise ``SyntaxError`` if it were ever executed. The AST
    path parses the compound assignment as its own statement kind and desugars it
    correctly.
    """
    source = "#i += 1;"
    lines = generate_statements(_statements(source))
    assert lines == ["self.i = self.i + 1"]
    # The specific thing the old path garbled: no stray `+ ==` token sequence, and
    # the right-hand side must actually read `self.i` (the desugared operand), not
    # merely the plain literal.
    assert "+ ==" not in lines[0]
    assert lines[0] == "self.i = self.i + 1"


def test_a_multi_value_case_label_with_an_inline_if_body() -> None:
    """A ``CASE`` branch with a comma-joined label and an inline ``IF`` body leaked.

    This is a variant of the leading-branch drop above, not one of the six the
    differential task reported by name, but the same round of measurement flagged
    and minimised it too: a multi-value ``CASE`` label (``"S2", "S3":``) whose body
    is itself an ``IF``/``ELSIF``/``ELSE``/``END_IF`` was never matched by the old
    path's case-label pattern at all (a deliberate, documented gap in
    ``control_flow.py`` -- matching it without resolving the constant list would
    have been worse: an unresolved value silently dropped). Every line of that
    unmatched branch -- including the raw ``IF``/``ELSIF``/``ELSE``/``END_IF``
    keywords, never recognised as control flow -- gets appended as if it were extra
    body text of the *previous* branch instead. The ``CASE``-level ``ELSE:`` default
    (with its body on the next line) suffers the same fate, leaking its own literal
    ``ELSE`` keyword into whichever branch happened to precede it. The AST path
    parses the multi-value label and the nested ``IF`` as what they are and keeps
    the ``ELSE`` default as an ordinary Python ``else``.
    """
    source = """
        CASE #state OF
            "S0":
                #out := "V0";
            "S1":
                #out := "V1";
            "S2", "S3":
                IF #cond = "C1" THEN
                    #out := "V2";
                ELSIF #cond = "C2" THEN
                    #out := "V3";
                ELSE
                    #out := "V4";
                END_IF;
            "S4":
                #out := "V5";
            ELSE:
                #out := "DEFAULT";
        END_CASE;
    """
    lines = generate_statements(_statements(source))
    assert lines == [
        'if self.state == self._runtime.tags["S0"]:',
        '    self.out = self._runtime.tags["V0"]',
        'elif self.state == self._runtime.tags["S1"]:',
        '    self.out = self._runtime.tags["V1"]',
        'elif self.state in (self._runtime.tags["S2"], self._runtime.tags["S3"]):',
        '    if self.cond == self._runtime.tags["C1"]:',
        '        self.out = self._runtime.tags["V2"]',
        '    elif self.cond == self._runtime.tags["C2"]:',
        '        self.out = self._runtime.tags["V3"]',
        "    else:",
        '        self.out = self._runtime.tags["V4"]',
        'elif self.state == self._runtime.tags["S4"]:',
        '    self.out = self._runtime.tags["V5"]',
        "else:",
        '    self.out = self._runtime.tags["DEFAULT"]',
    ]
    # The specific things the old path leaked as raw, untranslated keyword text
    # instead of real control flow: none of these bare keywords may appear as their
    # own token in the output, and the multi-value branch must be a proper nested
    # `if` under its own `elif self.state in (...)`, not text glued onto "S1"'s body.
    assert not any(line.strip() in ("IF", "ELSIF", "ELSE", "END_IF") for line in lines)
    multi = 'elif self.state in (self._runtime.tags["S2"], self._runtime.tags["S3"]):'
    assert multi in lines
    assert lines[lines.index(multi) + 1] == '    if self.cond == self._runtime.tags["C1"]:'
