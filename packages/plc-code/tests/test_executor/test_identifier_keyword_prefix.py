"""Regression tests for identifiers that begin with a control-flow keyword.

Background
----------
``_normalize_spacing`` re-inserts the space TIA Portal drops between a control
keyword and what follows it (``CASE#state`` -> ``CASE #state``).  The rules used
``\\bIF(?=[^\\s])``: a lookahead for "anything but a space".  A ``#`` before the
identifier supplies the left word boundary, so the rule also fired in the middle
of an identifier that merely *starts* with the keyword:

    ``#forcePrimaryCondition := TRUE;``  ->  ``#FOR cePrimaryCondition := TRUE;``
    ``#forward := 2;``                   ->  ``#FOR ward := 2;``
    ``#ifValid := FALSE;``               ->  ``#IF Valid := FALSE;``

The variable was silently renamed, so it no longer matched its declaration and
the block either failed to compile or wrote to a variable nobody read.

The mirror-image rule for ``DO``/``OF``/``TO``/``BY`` already guards against this
("a letter before the keyword means it is the tail of an identifier"); these
tests pin the same guarantee on the head side.
"""

from plc_code.executor.control_flow import ControlFlowTranslator
from plc_code.executor.harness import FBTestHarness
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser


def _harness(scl: str) -> FBTestHarness:
    """Compile inline SCL source into a test harness."""
    block = SCLParser(tokenize_with_newlines(scl)).parse()
    return FBTestHarness.from_block(block)


# Every identifier here begins with a control-flow keyword.
_FB_KEYWORD_PREFIXED = """
FUNCTION_BLOCK "KeywordPrefixedNames"
    VAR_INPUT
        trigger : Bool;
    END_VAR
    VAR_OUTPUT
        forcePrimaryCondition : Bool;
        forward : Int;
        ifValid : Bool;
        caseCount : Int;
        whileActive : Bool;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            IF #trigger THEN
                #forcePrimaryCondition := TRUE;
                #forward := 2;
                #ifValid := TRUE;
                #caseCount := 7;
                #whileActive := TRUE;
            END_IF;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


class TestKeywordPrefixedIdentifiers:
    """A keyword glued to letters is an identifier, not a keyword."""

    def test_for_prefixed_identifier_is_untouched(self) -> None:
        """``#forcePrimaryCondition`` must survive normalization intact."""
        line = "#forcePrimaryCondition := TRUE ;"
        assert ControlFlowTranslator()._normalize_spacing(line) == line

    def test_for_prefixed_short_identifier_is_untouched(self) -> None:
        """``#forward`` is a word, not a FOR loop."""
        line = "#forward := 2 ;"
        assert ControlFlowTranslator()._normalize_spacing(line) == line

    def test_if_prefixed_identifier_is_untouched(self) -> None:
        """``#ifValid`` must not become ``#IF Valid``."""
        line = "#ifValid := FALSE ;"
        assert ControlFlowTranslator()._normalize_spacing(line) == line

    def test_case_prefixed_identifier_is_untouched(self) -> None:
        """``#caseCount`` must not become ``#CASE Count``."""
        line = "#caseCount := 1 ;"
        assert ControlFlowTranslator()._normalize_spacing(line) == line

    def test_while_prefixed_identifier_is_untouched(self) -> None:
        """``#whileActive`` must not become ``#WHILE Active``."""
        line = "#whileActive := TRUE ;"
        assert ControlFlowTranslator()._normalize_spacing(line) == line

    def test_elsif_prefixed_identifier_is_untouched(self) -> None:
        """``#elsifDepth`` must not be split either."""
        line = "#elsifDepth := 3 ;"
        assert ControlFlowTranslator()._normalize_spacing(line) == line


class TestGluedKeywordsStillSplit:
    """The spacing rules must keep doing the job they exist for."""

    def test_if_glued_to_variable(self) -> None:
        """``IF#flag`` is a keyword glued to a variable reference."""
        assert "IF #flag" in ControlFlowTranslator()._normalize_spacing("IF#flag THEN")

    def test_if_glued_to_parenthesis(self) -> None:
        """``IF(`` is a keyword glued to a parenthesised condition."""
        assert "IF (" in ControlFlowTranslator()._normalize_spacing("IF(#a > 1) THEN")

    def test_case_glued_to_variable(self) -> None:
        """``CASE#state`` still gets its space."""
        assert "CASE #state" in ControlFlowTranslator()._normalize_spacing("CASE#state OF")

    def test_while_glued_to_variable(self) -> None:
        """``WHILE#running`` still gets its space."""
        assert "WHILE #running" in ControlFlowTranslator()._normalize_spacing("WHILE#running DO")

    def test_for_glued_to_variable(self) -> None:
        """``FOR#i`` still gets its space."""
        assert "FOR #i" in ControlFlowTranslator()._normalize_spacing("FOR#i := 0 TO 9 DO")

    def test_quoted_block_name_is_untouched(self) -> None:
        """The existing guard on quoted block names still holds."""
        line = '"ForwardKinematicMdh"()'
        assert ControlFlowTranslator()._normalize_spacing(line) == line


class TestKeywordPrefixedHarness:
    """End-to-end: the assignments must reach their declared variables."""

    def test_all_keyword_prefixed_outputs_are_written(self) -> None:
        """Each output keeps its name and receives its value."""
        h = _harness(_FB_KEYWORD_PREFIXED)
        h.set_inputs(trigger=True)
        h.execute()
        assert h.get_output("forcePrimaryCondition") is True
        assert h.get_output("forward") == 2
        assert h.get_output("ifValid") is True
        assert h.get_output("caseCount") == 7
        assert h.get_output("whileActive") is True

    def test_outputs_stay_at_rest_without_trigger(self) -> None:
        """The guard still gates the assignments."""
        h = _harness(_FB_KEYWORD_PREFIXED)
        h.set_inputs(trigger=False)
        h.execute()
        assert h.get_output("forcePrimaryCondition") is False
        assert h.get_output("forward") == 0
