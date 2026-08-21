"""Behavioural tests for CASE label forms.

Root cause these pin down
-------------------------
``ControlFlowTranslator`` recognised a CASE label with one regex that required
the label to occupy the whole line *and* end with a colon::

    ^\\s*(#\\s*\\w+(...)|"\\w+"|[\\d,\\s]+|ELSE)\\s*:\\s*$

Two real SCL forms never matched it, both silently:

``ELSE`` (no colon)
    SCL's default branch carries no colon; only ``ELSE:`` matched. The keyword
    became a body line of the *previous* branch, so the default body ran as part
    of that branch and the bare word ``ELSE`` reached the generated Python as an
    undefined name. Seen in production (project-A ``UserMode.s7dcl``).

``1: #b := 10;`` (statement on the label's line)
    No label ever matched, so ``current_values`` stayed empty and the
    ``if current_values and body_lines`` guard dropped **the entire CASE**.
    ``execute()`` did nothing at all, with no diagnostic: the generated Python is
    valid, just empty.

The second is why the earlier "CASE is supported" test passed while being
worthless — asserting that a block produces no diagnostics proves nothing when
the failure mode is producing no code. Every test here asserts the state machine
actually switches.
"""

from __future__ import annotations

import pytest

from plc_code.executor import PLCRuntime, compile_block
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser

_TEMPLATE = """
FUNCTION_BLOCK "CaseProbe"
    VAR_INPUT
        a : Int;
    END_VAR
    VAR_OUTPUT
        b : Int;
    END_VAR
    VAR
        state : Int;
    END_VAR
    {{ S7_Language := "SCL" }}
    NETWORK
        REGION Logic
{body}
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


def _run(body: str, cases: dict[int, int]) -> None:
    """Compile an inline CASE body and assert `a -> b` for every mapping."""
    source = _TEMPLATE.format(body=body)
    block = SCLParser(tokenize_with_newlines(source)).parse()
    result = compile_block(block)
    assert result.success, result.compile_error
    assert result.fb_class is not None

    for given, expected in cases.items():
        instance = result.fb_class(_runtime=PLCRuntime())
        instance.a = given
        instance.execute()
        assert instance.b == expected, f"a={given} gave b={instance.b}, expected {expected}"


_LABEL_OWN_LINE = """            CASE #a OF
                1:
                    #b := 10;
                2:
                    #b := 20;
            ELSE
                    #b := 99;
            END_CASE;"""

_LABEL_SAME_LINE = """            CASE #a OF
                1: #b := 10;
                2: #b := 20;
            ELSE
                #b := 99;
            END_CASE;"""

_ELSE_WITH_COLON = """            CASE #a OF
                1:
                    #b := 10;
            ELSE:
                    #b := 99;
            END_CASE;"""

_NO_ELSE = """            CASE #a OF
                1:
                    #b := 10;
                2:
                    #b := 20;
            END_CASE;"""

_MULTI_VALUE = """            CASE #a OF
                1, 2:
                    #b := 10;
                3:
                    #b := 30;
            ELSE
                    #b := 99;
            END_CASE;"""


class TestLabelOnItsOwnLine:
    """The form TIA Portal exports."""

    def test_branches_and_default(self) -> None:
        _run(_LABEL_OWN_LINE, {1: 10, 2: 20, 7: 99})


class TestLabelOnTheStatementLine:
    """The compact form. Used to drop the whole CASE without a word."""

    def test_branches_and_default(self) -> None:
        _run(_LABEL_SAME_LINE, {1: 10, 2: 20, 7: 99})


class TestElseSpelling:
    """SCL writes ``ELSE`` bare; ``ELSE:`` is tolerated."""

    def test_bare_else(self) -> None:
        _run(_LABEL_OWN_LINE, {7: 99})

    def test_else_with_colon_still_works(self) -> None:
        _run(_ELSE_WITH_COLON, {1: 10, 7: 99})


class TestWithoutDefault:
    """A CASE with no ELSE leaves the output untouched."""

    def test_unmatched_value_changes_nothing(self) -> None:
        _run(_NO_ELSE, {1: 10, 2: 20, 7: 0})


class TestMultiValueLabels:
    def test_comma_separated_values_share_a_branch(self) -> None:
        _run(_MULTI_VALUE, {1: 10, 2: 10, 3: 30, 7: 99})

    def test_comma_separated_symbolic_values_share_a_branch(self) -> None:
        """``"A", "B":`` — seen in production SCL.

        The statement AST parses a comma-separated CASE label as one branch
        with multiple values structurally, so the branch is no longer lost
        the way the old text path lost it (its label regex only recognised a
        single quoted word or a digit list, never this shape, so the line
        fell through as an ordinary body statement instead of a label).

        ``_collect_string_constants`` still only maps a quoted name glued to
        its colon (regex ``"NAME":``), so a value that is *never* referenced
        anywhere else in the block (via ``:=``/``<``/``>``) keeps an
        untranslated string literal instead of its assigned integer. This
        case still passes because ``"MODE_TWO"`` is also the assignment's
        right-hand side, which the constant collector does pick up; it is not
        a demonstration that the collector's own gap is closed.
        """
        body = """            #state := "MODE_TWO";
            CASE #state OF
                "MODE_ONE", "MODE_TWO":
                    #b := 10;
                "MODE_THREE":
                    #b := 30;
            ELSE
                    #b := 99;
            END_CASE;"""
        _run(body, {0: 10})


class TestAssignmentIsNotALabel:
    """``#x := ...`` must not be mistaken for a label — the colon is adjacent."""

    def test_assignment_to_the_case_variable_inside_a_branch(self) -> None:
        body = """            CASE #a OF
                1:
                    #b := 10;
                    #a := 5;
            ELSE
                    #b := 99;
            END_CASE;"""
        _run(body, {1: 10, 7: 99})


class TestSymbolicLabels:
    """Quoted symbolic labels, both layouts.

    A quoted label names a global constant whose numeric value lives outside the
    block, so the transpiler assigns each symbol an integer of its own and uses
    it consistently for every mention. These tests therefore drive the state
    variable *through the same symbols* and assert the branch selected — which
    is exactly how production code uses them (project-A ``UserMode.s7dcl``), and is
    self-consistent whatever integers get invented.
    """

    def test_own_line(self) -> None:
        body = """            #state := "MODE_TWO";
            CASE #state OF
                "MODE_ONE":
                    #b := 10;
                "MODE_TWO":
                    #b := 20;
            ELSE
                    #b := 99;
            END_CASE;"""
        _run(body, {0: 20})

    def test_same_line(self) -> None:
        body = """            #state := "MODE_ONE";
            CASE #state OF
                "MODE_ONE": #b := 10;
                "MODE_TWO": #b := 20;
            ELSE
                #b := 99;
            END_CASE;"""
        _run(body, {0: 10})

    def test_unlisted_symbol_falls_through_to_the_default(self) -> None:
        body = """            #state := "MODE_THREE";
            CASE #state OF
                "MODE_ONE":
                    #b := 10;
                "MODE_TWO":
                    #b := 20;
            ELSE
                    #b := 99;
            END_CASE;"""
        _run(body, {0: 99})

    def test_a_label_symbol_reused_beside_or_in_an_if_condition(self) -> None:
        """The same symbol as both a CASE label and an OR-joined IF condition.

        ``generate_statements`` folds the CASE-label / symbolic-constant
        substitution the deleted text path used to perform as a separate
        regex-rewrite-then-repair pass -- four ``(self\\.\\w+)(OR)(...)``-shaped
        regexes existed purely to glue an ``OR``/``AND`` keyword back onto a
        symbol name the blind text rewrite had crushed against it. Nothing
        differential ever verified this position: the deleted comparison always
        called ``generate_statements`` with ``string_constants=None`` (see the
        coverage gap this test closes alongside
        ``test_generator_statements.py::test_a_case_label_renders_bare_while_the_same_symbol_elsewhere_stays_self_prefixed``),
        so a regression exactly here would not have been caught by anything.
        This drives the real pipeline end to end (``compile_block`` ->
        ``transpile_block``) rather than calling ``generate_statements`` directly,
        and asserts both the generated text and that the branch actually fires.
        """
        body = """            IF #a = 1 THEN
                #state := "MODE_ONE";
            ELSIF #a = 2 THEN
                #state := "MODE_TWO";
            ELSE
                #state := "MODE_THREE";
            END_IF;
            CASE #state OF
                "MODE_ONE":
                    #b := 10;
                "MODE_TWO":
                    #b := 20;
            ELSE
                    #b := 99;
            END_CASE;
            IF #state = "MODE_ONE" OR #state = "MODE_TWO" THEN
                #b := #b + 1;
            END_IF;"""
        source = _TEMPLATE.format(body=body)
        block = SCLParser(tokenize_with_newlines(source)).parse()
        result = compile_block(block)
        assert result.success, result.compile_error
        generated = result.transpile_result.python_code
        assert "if self.state == self.MODE_ONE or self.state == self.MODE_TWO:" in generated

        # a=1 and a=2 land on the two CASE-labelled branches (b=10 / b=20) and then
        # the OR condition must recognise the just-assigned symbol and add 1; a=3
        # falls to the CASE default (b=99) and the OR condition must NOT fire.
        for given, expected in {1: 11, 2: 21, 3: 99}.items():
            instance = result.fb_class(_runtime=PLCRuntime())
            instance.a = given
            instance.execute()
            assert instance.b == expected, f"a={given} gave b={instance.b}, expected {expected}"


class TestRegionsInsideBranches:
    """Regions are stripped in preprocessing; branches must survive it."""

    def test_region_in_branch_and_in_default(self) -> None:
        body = """            CASE #a OF
                1:
                    REGION One
                        #b := 10;
                    END_REGION
            ELSE
                    REGION Fallback
                        #b := 99;
                    END_REGION
            END_CASE;"""
        _run(body, {1: 10, 7: 99})


class TestNestedCase:
    """The depth counter must still hold."""

    def test_inner_case_in_a_branch(self) -> None:
        body = """            CASE #a OF
                1:
                    #b := 10;
                2:
                    CASE #a OF
                        2:
                            #b := 22;
                    ELSE
                            #b := 21;
                    END_CASE;
            ELSE
                    #b := 99;
            END_CASE;"""
        _run(body, {1: 10, 2: 22, 7: 99})


@pytest.mark.parametrize(
    "body",
    [_LABEL_OWN_LINE, _LABEL_SAME_LINE, _MULTI_VALUE],
    ids=["own-line", "same-line", "multi-value"],
)
def test_no_bare_else_reaches_the_generated_python(body: str) -> None:
    """A leftover ``ELSE`` token means the default branch was not recognised."""
    from plc_code.executor import transpile_block

    source = _TEMPLATE.format(body=body)
    block = SCLParser(tokenize_with_newlines(source)).parse()
    generated = transpile_block(block).python_code
    assert not any(line.strip() == "ELSE" for line in generated.splitlines()), generated
