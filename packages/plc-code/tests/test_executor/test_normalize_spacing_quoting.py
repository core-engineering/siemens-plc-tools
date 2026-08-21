"""Regression tests: expression translation must not rewrite quoted text.

Background
----------
The generator reads SCL from a token stream, so a keyword the tokenizer put
inside a ``STRING`` token (``'DO WHILE loop'``) can never be mistaken for code
the way the old text path's ~25 quote-blind ``re.sub`` passes over a whole
line once could:

    ``#msg := 'DO WHILE loop';``   ->  ``#msg := ' DO WHILE loop';``
    ``#msg := 'CASE#1';``          ->  ``#msg := 'CASE #1';``
    ``#msg := 'a  b';``            ->  ``#msg := 'a b';``

The block still compiled under that defect, so nothing failed loudly — the
program simply carried a silently different string, e.g. into an alarm text
or a state label. ``ExpressionTranslator.translate`` still runs its own
rewriting passes over reconstructed expression text (unchanged by the switch
to the statement AST — see ``plc_code.executor.generator``'s module
docstring), so it keeps its own literal-opacity tests here; the end-to-end
case is the harness test at the bottom, run through the real (AST) pipeline.
"""

from plc_code.executor.codegen import ExpressionTranslator
from plc_code.executor.harness import FBTestHarness
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser


def _harness(scl: str) -> FBTestHarness:
    """Compile inline SCL source into a test harness."""
    block = SCLParser(tokenize_with_newlines(scl)).parse()
    return FBTestHarness.from_block(block)


class TestExpressionTranslatorLeavesLiteralsAlone:
    """``ExpressionTranslator.translate`` runs ~12 rewriting passes over the raw
    expression text.  Every one of them was quote-blind, so a string literal was
    translated as if it were code.  The block still compiled; only the string
    content came out wrong."""

    def test_hash_inside_literal_is_not_an_instance_variable(self) -> None:
        """``'CASE#1'`` must not become ``'CASEself.1'``."""
        assert ExpressionTranslator().translate("'CASE#1'") == "'CASE#1'"

    def test_equality_operator_inside_literal(self) -> None:
        """``'a = b'`` must not become ``'a == b'``."""
        assert ExpressionTranslator().translate("'a = b'") == "'a = b'"

    def test_boolean_literal_inside_literal(self) -> None:
        """``'TRUE'`` as text must not become Python's ``True``."""
        assert ExpressionTranslator().translate("'TRUE'") == "'TRUE'"

    def test_boolean_operators_inside_literal(self) -> None:
        """``'a AND NOT b'`` is a message, not an expression."""
        assert ExpressionTranslator().translate("'a AND NOT b'") == "'a AND NOT b'"

    def test_doubled_quote_escape_inside_literal(self) -> None:
        """The scan must not stop at the escaped quote."""
        assert ExpressionTranslator().translate("'it''s #ok'") == "'it''s #ok'"

    def test_code_around_a_literal_is_still_translated(self) -> None:
        """Protection is scoped to the literal, not to the expression."""
        out = ExpressionTranslator().translate("#state = 1 AND #msg = 'CASE#1'")
        assert "self.state" in out
        assert "'CASE#1'" in out
        assert "==" in out

    def test_two_literals_keep_their_own_content(self) -> None:
        """Placeholders must not cross-contaminate."""
        out = ExpressionTranslator().translate("'#a' <> '#b'")
        assert "'#a'" in out
        assert "'#b'" in out
        assert "self." not in out


_FB_STRING_LITERALS = """
FUNCTION_BLOCK "LiteralKeywords"
    VAR_INPUT
        trigger : Bool;
    END_VAR
    VAR_OUTPUT
        message : String;
        label : String;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            IF #trigger THEN
                #message := 'DO WHILE loop';
                #label := 'CASE#1';
            END_IF;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


class TestStringLiteralsSurviveExecution:
    """End-to-end: the literal reaching the output is byte-identical."""

    def test_literals_are_written_verbatim(self) -> None:
        """Neither output may carry a normalizer-inserted space."""
        h = _harness(_FB_STRING_LITERALS)
        h.set_inputs(trigger=True)
        h.execute()
        assert h.get_output("message") == "DO WHILE loop"
        assert h.get_output("label") == "CASE#1"
