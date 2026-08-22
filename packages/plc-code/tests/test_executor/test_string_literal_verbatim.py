"""Regression test: a string literal reaches the executed output byte-identical.

Background
----------
`plc_code.parser.expression_parser._parse_primary` used to emit `VariableRef` for
both a double-quoted symbol reference (`"Db"`) and a single-quoted string literal
(`'text'`), because the lexer tokenizes both as `STRING` and the parser did not
distinguish them further -- a *parser* defect, not a rendering one, fixed in an
earlier task in this same generator-rewrite series (`Literal` and `VariableRef`
are now genuinely different node types). Left unfixed, that conflation would have
been silent: `render`'s `_render_variable_ref` renders a local `VariableRef` as
`self.{name}`, so a mistaken literal would have read as a reference to an
attribute nothing assigns, rather than as the literal's own text -- corpus impact
measured at the time: 177 single-quoted literals, 45 of them empty.

This test does not exercise the parser fix directly (that has its own unit
tests); it is the end-to-end guard that the property the fix restored still
holds through the real (AST) pipeline: a string literal assigned to an output
must reach the harness verbatim, including an empty string and a literal
containing internal spaces -- the two shapes most likely to go unnoticed if a
future change reintroduced this conflation (an empty string parsing as a
zero-length identifier, or internal spaces surviving only because nothing
rewrites the token's text at all).
"""

from plc_code.executor.harness import FBTestHarness
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser


def _harness(scl: str) -> FBTestHarness:
    """Compile inline SCL source into a test harness."""
    block = SCLParser(tokenize_with_newlines(scl)).parse()
    return FBTestHarness.from_block(block)


_FB_STRING_LITERALS = """
FUNCTION_BLOCK "StringLiteralOutput"
    VAR_INPUT
        trigger : Bool;
    END_VAR
    VAR_OUTPUT
        message : String;
        empty : String;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            IF #trigger THEN
                #message := 'DO WHILE loop';
                #empty := '';
            END_IF;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


def test_string_literals_reach_the_output_verbatim() -> None:
    """A literal with internal spaces, and an empty literal, both survive unchanged."""
    h = _harness(_FB_STRING_LITERALS)
    h.set_inputs(trigger=True)
    h.execute()
    assert h.get_output("message") == "DO WHILE loop"
    assert h.get_output("empty") == ""
