"""Regression tests: ``_normalize_spacing`` must not rewrite quoted text.

Background
----------
``_normalize_spacing`` re-inserts the spaces TIA Portal drops between glued SCL
tokens (``CASE#state`` -> ``CASE #state``).  It ran ~25 ``re.sub`` calls over the
*whole* line, with no notion of string literals, so a keyword appearing inside a
quoted literal was rewritten as if it were code:

    ``#msg := 'DO WHILE loop';``   ->  ``#msg := ' DO WHILE loop';``
    ``#msg := 'CASE#1';``          ->  ``#msg := 'CASE #1';``
    ``#msg := 'a  b';``            ->  ``#msg := 'a b';``

The block still compiled, so nothing failed loudly — the program simply carried a
silently different string, e.g. into an alarm text or a state label.

This is the same class of defect as the ``_INLINE_COMPOUND_SPLIT`` one fixed in
d119b8d, and was recorded there as a known follow-up.  ``"`` is treated as opaque
too: in SCL it delimits symbol names (``"ForwardKinematicMdh"``,
``"DbName".MEMBER``), which must survive normalization just as literally.
"""

from plc_code.executor.codegen import ExpressionTranslator
from plc_code.executor.control_flow import ControlFlowTranslator
from plc_code.executor.harness import FBTestHarness
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser


def _norm(line: str) -> str:
    """Run the spacing normalizer over a single preprocessed line."""
    return ControlFlowTranslator()._normalize_spacing(line)


def _harness(scl: str) -> FBTestHarness:
    """Compile inline SCL source into a test harness."""
    block = SCLParser(tokenize_with_newlines(scl)).parse()
    return FBTestHarness.from_block(block)


class TestSingleQuotedLiteralsAreOpaque:
    """An SCL string literal is data; no spacing rule may touch it."""

    def test_glued_do_keyword_inside_literal(self) -> None:
        """``'DO WHILE loop'`` must not gain a space before ``DO``."""
        line = "#msg := 'DO WHILE loop' ;"
        assert _norm(line) == line

    def test_glued_of_to_by_keywords_inside_literal(self) -> None:
        """The ``OF``/``TO``/``BY`` rules are equally quote-blind."""
        line = "#msg := '1:OF 2:TO 3:BY' ;"
        assert _norm(line) == line

    def test_keyword_glued_to_hash_inside_literal(self) -> None:
        """``'CASE#1'`` is a label, not a CASE statement."""
        line = "#label := 'CASE#1' ;"
        assert _norm(line) == line

    def test_keyword_glued_to_parenthesis_inside_literal(self) -> None:
        """``'IF(x)'`` inside a literal keeps its exact shape."""
        line = "#expr := 'IF(x)' ;"
        assert _norm(line) == line

    def test_boolean_operators_inside_literal(self) -> None:
        """``AND#`` / ``ORNOT`` rules must not fire inside a literal."""
        line = "#expr := 'a AND#b ORNOT c' ;"
        assert _norm(line) == line

    def test_repeated_spaces_inside_literal_are_preserved(self) -> None:
        """The trailing double-space cleanup must stop at the quote."""
        line = "#msg := 'column A    column B' ;"
        assert _norm(line) == line

    def test_doubled_quote_escape_is_handled(self) -> None:
        """``''`` escapes a quote; the literal does not end there."""
        line = "#msg := 'it''s a DO WHILE loop' ;"
        assert _norm(line) == line

    def test_unterminated_literal_is_left_alone(self) -> None:
        """A malformed line must degrade quietly, not get mangled."""
        line = "#msg := 'unterminated DO"
        assert _norm(line) == line


class TestDoubleQuotedNamesAreOpaque:
    """``"..."`` delimits an SCL symbol name — also opaque."""

    def test_quoted_block_name_with_keyword_head(self) -> None:
        """The guard that motivated the ``(?<!")`` hack still holds."""
        line = '"ForwardKinematicMdh"()'
        assert _norm(line) == line

    def test_quoted_db_member_access(self) -> None:
        """``"DbSettings".doorOpenTimeout`` survives intact."""
        line = '#t := "DbSettings" . doorOpenTimeout ;'
        assert _norm(line) == line

    def test_quoted_name_containing_case_keyword(self) -> None:
        """A block named ``"CaseSelector"`` is not a CASE statement."""
        line = '"CaseSelector"(state := #s)'
        assert _norm(line) == line


class TestCodeOutsideQuotesStillNormalized:
    """Opacity must be scoped to the literal, not the whole line."""

    def test_glued_keyword_before_a_literal(self) -> None:
        """Code preceding a literal is still normalized."""
        assert _norm("IF#flag THEN #msg := 'DO nothing' ;").startswith("IF #flag")

    def test_literal_does_not_disable_the_rest_of_the_line(self) -> None:
        """``CASE#state`` after a literal still gets its space."""
        out = _norm("#msg := 'DO WHILE loop' ; CASE#state OF")
        assert "'DO WHILE loop'" in out
        assert "CASE #state" in out

    def test_two_literals_with_code_between_them(self) -> None:
        """Every unquoted span is normalized; every quoted span is not."""
        out = _norm("#a := 'IF(x)' ; IF#flag THEN #b := 'CASE#1' ;")
        assert "'IF(x)'" in out
        assert "'CASE#1'" in out
        assert "IF #flag" in out


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
