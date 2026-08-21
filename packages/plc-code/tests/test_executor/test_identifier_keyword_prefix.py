"""Regression tests for identifiers that begin with a control-flow keyword.

Background
----------
The old text path re-inserted the space TIA Portal drops between a control
keyword and what follows it (``CASE#state`` -> ``CASE #state``) with a regex
using ``\\bIF(?=[^\\s])``: a lookahead for "anything but a space". A ``#``
before the identifier supplied the left word boundary, so the rule also fired
in the middle of an identifier that merely *starts* with the keyword:

    ``#forcePrimaryCondition := TRUE;``  ->  ``#FOR cePrimaryCondition := TRUE;``
    ``#forward := 2;``                   ->  ``#FOR ward := 2;``
    ``#ifValid := FALSE;``               ->  ``#IF Valid := FALSE;``

The variable was silently renamed, so it no longer matched its declaration and
the block either failed to compile or wrote to a variable nobody read. The
statement AST reads a token stream, where ``#forcePrimaryCondition`` is
already one token distinct from ``FOR``, so this class of bug has no way to
recur; this test guards the real (AST) pipeline end to end rather than a
regex that no longer exists.
"""

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
