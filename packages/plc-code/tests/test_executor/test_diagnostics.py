"""Tests for transpile diagnostics.

The executor transpiles SCL by rewriting text, with no statement-level AST, so
a construct it does not recognise falls through ``_translate_simple_statement``
and is emitted as-is. ``transpile_block`` reports ``success=True`` with zero
errors and zero warnings for such a block — the damage only shows up as a
``SyntaxError`` at compile time or a ``NameError`` the first time the branch
runs, in the downstream project.

These diagnostics look at the *generated Python* instead of trying to prove
anything about the SCL:

- it does not parse            -> the block cannot load at all
- it references a name nothing provides -> NameError when that line runs

Both are cheap, and between them they catch the constructs the translator has
no support for (REPEAT/UNTIL, GOTO, unmapped builtins like SEL or LIMIT).
"""

from __future__ import annotations

from pathlib import Path

from plc_core.reporting import Severity

from plc_code.executor.diagnostics import (
    CODE_SYNTAX,
    CODE_TRANSPILE,
    CODE_UNDEFINED_NAME,
    check_block,
)
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser

_TEMPLATE = """
FUNCTION_BLOCK "{name}"
    VAR_INPUT
        a : Int;
    END_VAR
    VAR_OUTPUT
        b : Int;
    END_VAR
    {{ S7_Language := "SCL" }}
    NETWORK
        REGION Logic
{body}
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


def _check(body: str, name: str = "Probe") -> list:
    """Transpile an inline SCL body and return its diagnostics."""
    source = _TEMPLATE.format(name=name, body=body)
    block = SCLParser(tokenize_with_newlines(source)).parse()
    return check_block(block)


def _codes(body: str) -> set[str]:
    return {d.code for d in _check(body)}


class TestSupportedConstructsAreClean:
    """No false positives: anything the translator handles must report nothing.

    A noisy detector is a useless one — these are the tests that decide whether
    the command is worth running.
    """

    def test_if_elsif_else(self) -> None:
        body = (
            "            IF #a > 1 THEN\n"
            "                #b := 2;\n"
            "            ELSIF #a = 0 THEN\n"
            "                #b := 3;\n"
            "            ELSE\n"
            "                #b := 4;\n"
            "            END_IF;"
        )
        assert _check(body) == []

    def test_case_with_else(self) -> None:
        body = (
            "            CASE #a OF\n"
            "                1: #b := 10;\n"
            "                2: #b := 20;\n"
            "            ELSE\n"
            "                #b := 0;\n"
            "            END_CASE;"
        )
        assert _check(body) == []

    def test_for_loop_with_exit(self) -> None:
        body = (
            "            FOR #a := 1 TO 3 DO\n"
            "                #b := #b + 1;\n"
            "                EXIT;\n"
            "            END_FOR;"
        )
        assert _check(body) == []

    def test_while_loop(self) -> None:
        body = "            WHILE #b < 5 DO\n                #b := #b + 1;\n            END_WHILE;"
        assert _check(body) == []

    def test_mapped_builtins_and_math_import(self) -> None:
        """``math`` is imported by the generated module — not an undefined name."""
        body = "            #b := REAL_TO_INT(SIN(1.0) + COS(2.0) + ABS(-1.0));"
        assert _check(body) == []

    def test_runtime_helpers_are_not_reported(self) -> None:
        """``_clone_value`` and friends are imported by generated code."""
        body = "            #b := #a;"
        assert _check(body) == []


class TestGeneratedPythonDoesNotParse:
    """Constructs that produce Python which cannot even be compiled."""

    def test_repeat_until(self) -> None:
        body = (
            "            REPEAT\n"
            "                #b := #b + 1;\n"
            "            UNTIL #b > 5\n"
            "            END_REPEAT;"
        )
        diagnostics = _check(body)
        assert [d.code for d in diagnostics] == [CODE_SYNTAX]
        assert diagnostics[0].severity is Severity.ERROR

    def test_syntax_diagnostic_points_at_the_generated_line(self) -> None:
        body = (
            "            REPEAT\n"
            "                #b := #b + 1;\n"
            "            UNTIL #b > 5\n"
            "            END_REPEAT;"
        )
        diagnostic = _check(body)[0]
        assert diagnostic.line is not None and diagnostic.line > 0
        assert diagnostic.generated_line != ""

    def test_goto(self) -> None:
        assert CODE_SYNTAX in _codes("            GOTO done;")


class TestGeneratedPythonReferencesUnknownNames:
    """Constructs that compile but blow up with NameError when they run."""

    def test_unmapped_builtin_sel(self) -> None:
        diagnostics = _check("            #b := SEL(G := TRUE, IN0 := 1, IN1 := 2);")
        assert {d.code for d in diagnostics} == {CODE_UNDEFINED_NAME}
        assert any("SEL" in d.message for d in diagnostics)

    def test_unmapped_builtin_limit(self) -> None:
        diagnostics = _check("            #b := LIMIT(MN := 0, IN := #a, MX := 9);")
        assert any("LIMIT" in d.message for d in diagnostics)

    def test_continue_statement(self) -> None:
        body = "            FOR #a := 1 TO 3 DO\n                CONTINUE;\n            END_FOR;"
        diagnostics = _check(body)
        assert {d.code for d in diagnostics} == {CODE_UNDEFINED_NAME}
        assert any("CONTINUE" in d.message for d in diagnostics)

    def test_undefined_name_is_a_warning(self) -> None:
        """It only fails if the branch runs, unlike a syntax error."""
        diagnostics = _check("            #b := SEL(G := TRUE, IN0 := 1, IN1 := 2);")
        assert all(d.severity is Severity.WARNING for d in diagnostics)

    def test_undefined_name_carries_a_line_number(self) -> None:
        diagnostics = _check("            #b := SEL(G := TRUE, IN0 := 1, IN1 := 2);")
        assert all(d.line is not None and d.line > 0 for d in diagnostics)

    def test_each_unknown_name_is_reported_once(self) -> None:
        """Two uses of the same unknown builtin are one finding, not two."""
        body = (
            "            #b := SEL(G := TRUE, IN0 := 1, IN1 := 2);\n"
            "            #b := SEL(G := FALSE, IN0 := 3, IN1 := 4);"
        )
        names = [d.message for d in _check(body) if "SEL" in d.message]
        assert len(names) == 1


class TestDiagnosticMetadata:
    """Every diagnostic must be attributable."""

    def test_block_name_is_carried(self) -> None:
        diagnostics = _check("            #b := SEL(G := TRUE, IN0 := 1, IN1 := 2);", name="ArmKinematics")
        assert all(d.block_name == "ArmKinematics" for d in diagnostics)

    def test_source_file_is_carried_when_given(self) -> None:
        source = _TEMPLATE.format(name="Probe", body="            #b := SEL(G := TRUE);")
        block = SCLParser(tokenize_with_newlines(source)).parse()
        path = Path("program-blocks/Probe.s7dcl")
        diagnostics = check_block(block, source_file=path)
        assert all(d.source_file == path for d in diagnostics)

    def test_codes_are_distinct(self) -> None:
        assert len({CODE_TRANSPILE, CODE_SYNTAX, CODE_UNDEFINED_NAME}) == 3
