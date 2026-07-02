"""Regression tests for the inline nested control-flow bug.

Background
----------
When a nested ``IF`` (or ``CASE``/``WHILE``/``FOR``) is the FIRST statement of an
enclosing ``IF``/``ELSE`` body AND the parser lands it on the same physical line
as the enclosing ``THEN``/``ELSE`` (e.g. ``IF #a THEN IF #b THEN ... ;``), the
inline-body capture in :meth:`ControlFlowTranslator._translate_if_block` used to
grab the nested header WITHOUT its matching ``END_IF``.  The nested statement was
then silently dropped (its branch effect never ran) and a stray ``END_IF`` leaked
into the generated Python.  Observed in the field (project-E WS2) and
worked around by collapsing to ``IF (a) AND (b) THEN``.

The same inline-body path also leaked an inline ``//`` comment placed as the first
token after ``THEN``/``ELSE`` (WS1-B).

These tests pin:
    * the inner branch effect actually happens (harness execution),
    * the glued single-line form and the clean multi-line form both work,
    * the "nested IF not first" and ELSE-body variants,
    * inline comments no longer leak,
    * the ``**`` operator is not mangled into ``* *``.
"""

from plc_code.executor.control_flow import translate_control_flow
from plc_code.executor.harness import FBTestHarness
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser


def _harness(scl: str) -> FBTestHarness:
    """Compile inline SCL source into a test harness."""
    block = SCLParser(tokenize_with_newlines(scl)).parse()
    return FBTestHarness.from_block(block)


# The nested IF sits GLUED on the same physical line as the outer THEN — the exact
# shape that silently dropped the inner branch before the fix.
_FB_GLUED = """
FUNCTION_BLOCK "NestedFirstGlued"
    VAR_INPUT
        status : Int;
        a : Real;
        b : Real;
        limit : Real;
    END_VAR
    VAR_OUTPUT
        out : Int;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            IF #status = 1 THEN IF (#a * #b) > #limit THEN #out := 1;
            END_IF;
            END_IF;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""

# Same logic, clean multi-line layout (already worked; pinned to stay working).
_FB_MULTILINE = """
FUNCTION_BLOCK "NestedFirstMulti"
    VAR_INPUT
        status : Int;
        a : Real;
        b : Real;
        limit : Real;
    END_VAR
    VAR_OUTPUT
        out : Int;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            IF #status = 1 THEN
                IF (#a * #b) > #limit THEN
                    #out := 1;
                END_IF;
            END_IF;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


class TestNestedIfHarness:
    """End-to-end harness tests: the inner branch effect must actually occur."""

    def test_glued_nested_if_first_inner_branch_runs(self) -> None:
        """Inner IF is first stmt, glued after outer THEN — inner effect must run.

        Before the fix this transpiled to ``if ...: pass`` + a leaked ``END_IF``
        (NameError at runtime); ``out`` never became 1.
        """
        h = _harness(_FB_GLUED)
        h.set_inputs(status=1, a=3.0, b=4.0, limit=5.0)  # 3*4=12 > 5 -> out=1
        h.execute()
        assert h.get_output("out") == 1

    def test_glued_nested_if_inner_condition_false(self) -> None:
        """Inner condition false -> inner body skipped, no crash, out stays 0."""
        h = _harness(_FB_GLUED)
        h.set_inputs(status=1, a=1.0, b=1.0, limit=5.0)  # 1 > 5 is False
        h.execute()
        assert h.get_output("out") == 0

    def test_glued_outer_condition_false(self) -> None:
        """Outer condition false -> nothing runs, out stays 0."""
        h = _harness(_FB_GLUED)
        h.set_inputs(status=0, a=3.0, b=4.0, limit=5.0)
        h.execute()
        assert h.get_output("out") == 0

    def test_multiline_nested_if_first_inner_branch_runs(self) -> None:
        """Clean multi-line layout keeps working (pins the already-correct path)."""
        h = _harness(_FB_MULTILINE)
        h.set_inputs(status=1, a=3.0, b=4.0, limit=5.0)
        h.execute()
        assert h.get_output("out") == 1


class TestNestedIfUnit:
    """Fine-grained structural tests on the translator output."""

    def test_glued_nested_if_first_not_dropped(self) -> None:
        """The inner IF must survive and no raw END_IF may leak."""
        scl = "IF #status = 1 THEN IF (#a * #b) > #limit THEN #out := 1 ;\nEND_IF ;\nEND_IF ;"
        result = translate_control_flow(scl)

        if_count = sum(1 for line in result if line.strip().startswith("if "))
        assert if_count == 2, f"Inner IF dropped: {result}"
        assert any("self.out = 1" in line for line in result), f"Inner body lost: {result}"
        # No stray END_IF keyword may leak into the generated Python.
        assert not any("END_IF" in line for line in result), f"Leaked END_IF: {result}"

    def test_nested_if_not_first_still_works(self) -> None:
        """A statement before the nested IF (nested IF NOT first) — pins passing."""
        scl = (
            "IF #status = 1 THEN #pre := 0 ;\n"
            "IF (#a * #b) > #limit THEN #out := 1 ;\n"
            "END_IF ;\n"
            "END_IF ;"
        )
        result = translate_control_flow(scl)

        if_count = sum(1 for line in result if line.strip().startswith("if "))
        assert if_count == 2, f"Structure broken: {result}"
        assert any("self.pre = 0" in line for line in result)
        assert any("self.out = 1" in line for line in result)
        assert not any("END_IF" in line for line in result), f"Leaked END_IF: {result}"

    def test_nested_if_first_in_else_body(self) -> None:
        """Nested IF as first statement of an ELSE body (glued after ELSE)."""
        scl = (
            "IF #status = 1 THEN #out := 5 ;\n"
            "ELSE IF #a > #limit THEN #out := 1 ;\n"
            "END_IF ;\n"
            "END_IF ;"
        )
        result = translate_control_flow(scl)

        assert any(line.strip().startswith("if ") for line in result)
        assert any(line.strip() == "else:" for line in result), f"Missing else: {result}"
        assert any("self.out = 1" in line for line in result), f"ELSE-nested body lost: {result}"
        assert not any("END_IF" in line for line in result), f"Leaked END_IF: {result}"

    def test_deeply_glued_triple_nested_if(self) -> None:
        """Three IFs glued on one line must all survive."""
        scl = "IF #a THEN IF #b THEN IF #c THEN #out := 1 ;\n" "END_IF ;\nEND_IF ;\nEND_IF ;"
        result = translate_control_flow(scl)

        if_count = sum(1 for line in result if line.strip().startswith("if "))
        assert if_count == 3, f"Expected 3 nested ifs, got: {result}"
        assert any("self.out = 1" in line for line in result)
        assert not any("END_IF" in line for line in result)


class TestInlineCommentDoesNotLeak:
    """Secondary bug (same family): an inline ``//`` comment must not leak."""

    def test_comment_first_own_line_in_if_body(self) -> None:
        scl = "IF #flag THEN\n// set output\n#out := 1;\nEND_IF;"
        result = translate_control_flow(scl)
        assert not any("//" in line for line in result), f"Comment leaked: {result}"
        assert any("self.out = 1" in line for line in result)

    def test_comment_glued_after_then(self) -> None:
        scl = "IF #flag THEN // set output\n#out := 1;\nEND_IF;"
        result = translate_control_flow(scl)
        assert not any("//" in line for line in result), f"Comment leaked: {result}"
        assert any("self.out = 1" in line for line in result)

    def test_comment_glued_after_else(self) -> None:
        scl = "IF #f THEN\n#a := 1;\nELSE // otherwise\n#a := 2;\nEND_IF;"
        result = translate_control_flow(scl)
        assert not any("//" in line for line in result), f"Comment leaked: {result}"
        assert any("self.a = 2" in line for line in result)

    def test_inline_comment_does_not_swallow_double_slash_in_string(self) -> None:
        """A ``//`` inside a string literal must NOT be treated as a comment."""
        scl = "#path := 'a//b';"
        result = translate_control_flow(scl)
        assert any("a//b" in line for line in result), f"String mangled: {result}"


class TestSplitQuoteAwareness:
    """_INLINE_COMPOUND_SPLIT must not corrupt string literals containing control keywords."""

    def test_split_does_not_break_string_literal(self) -> None:
        """A string literal containing a keyword pair must arrive as one intact line."""
        for s in ("'PUMP DO WHILE RUN'", "'PRESS THEN IF READY'", "'ELSE IF x'"):
            r = translate_control_flow(f"#msg := {s};")
            assert r == [f"self.msg = {s}"], r

    def test_split_does_not_break_string_in_if_body(self) -> None:
        """String literal with control keywords inside an IF body must survive intact."""
        scl = "IF #flag THEN\n#msg := 'PUMP DO WHILE RUN';\nEND_IF;"
        result = translate_control_flow(scl)
        assert any("self.msg = 'PUMP DO WHILE RUN'" in line for line in result), result

    def test_split_applied_outside_string(self) -> None:
        """A real keyword pair outside quotes must still be split (regression guard)."""
        scl = "IF #a THEN IF #b THEN #out := 1;\nEND_IF;\nEND_IF;"
        result = translate_control_flow(scl)
        if_count = sum(1 for line in result if line.strip().startswith("if "))
        assert if_count == 2, f"Expected 2 ifs, got: {result}"


class TestSplitPinnedKeywordPairs:
    """Pin keyword pairs beyond THEN IF that were working but untested."""

    def test_then_case_split(self) -> None:
        """THEN CASE glued on one line must produce correct IF + CASE output.

        SCL CASE labels must appear alone on their own line (label_match
        requires ``:\\s*$``), so the body lives on the next line.
        """
        scl = "IF #flag THEN CASE #x OF\n" "1:\n" "#out := 1;\n" "END_CASE;\n" "END_IF;"
        result = translate_control_flow(scl)
        assert any("if self.flag" in line for line in result), result
        assert any("self.out = 1" in line for line in result), result
        assert not any("END_CASE" in line for line in result), result

    def test_do_while_nested_split(self) -> None:
        """DO WHILE glued on one line — outer WHILE body must contain inner while."""
        scl = (
            "WHILE #a > 0 DO WHILE #b > 0 DO\n"
            "#b := #b - 1;\n"
            "END_WHILE;\n"
            "#a := #a - 1;\n"
            "END_WHILE;"
        )
        result = translate_control_flow(scl)
        while_count = sum(1 for line in result if line.strip().startswith("while "))
        assert while_count == 2, f"Expected 2 while loops, got: {result}"
        assert any("self.b = self.b - 1" in line for line in result), result
        assert any("self.a = self.a - 1" in line for line in result), result


class TestPowerOperatorNotMangled:
    """Secondary bug (not reproducible; guarded): ``**`` must stay ``**``."""

    def test_power_operator_spaced(self) -> None:
        result = translate_control_flow("#y := #x ** 2;")
        assert "self.y = self.x ** 2" in result[0]
        assert "* *" not in result[0]

    def test_power_operator_unspaced(self) -> None:
        result = translate_control_flow("#y := #x**2;")
        assert "* *" not in result[0]
        assert "**" in result[0]

    def test_power_operator_in_condition(self) -> None:
        result = translate_control_flow("IF #x ** 2 > 4 THEN\n#y := 1;\nEND_IF;")
        combined = "\n".join(result)
        assert "* *" not in combined
        assert "**" in combined
