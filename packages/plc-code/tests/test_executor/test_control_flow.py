"""Tests for control flow translation."""

from plc_code.executor.control_flow import (
    ControlFlowTranslator,
    translate_control_flow,
)


class TestIfTranslation:
    """Tests for IF statement translation."""

    def test_simple_if(self) -> None:
        """Test simple IF statement."""
        scl = """
        IF #flag THEN
            #output := TRUE;
        END_IF;
        """
        result = translate_control_flow(scl)

        assert len(result) >= 2
        assert "if self.flag:" in result[0]
        assert "self.output = True" in result[1]

    def test_if_else(self) -> None:
        """Test IF/ELSE statement."""
        scl = """
        IF #condition THEN
            #a := 1;
        ELSE
            #a := 2;
        END_IF;
        """
        result = translate_control_flow(scl)

        assert any("if self.condition:" in line for line in result)
        assert any("else:" in line for line in result)
        assert any("self.a = 1" in line for line in result)
        assert any("self.a = 2" in line for line in result)

    def test_if_elsif_else(self) -> None:
        """Test IF/ELSIF/ELSE statement."""
        scl = """
        IF #x = 1 THEN
            #result := 10;
        ELSIF #x = 2 THEN
            #result := 20;
        ELSE
            #result := 0;
        END_IF;
        """
        result = translate_control_flow(scl)

        assert any("if self.x == 1:" in line for line in result)
        assert any("elif self.x == 2:" in line for line in result)
        assert any("else:" in line for line in result)

    def test_if_elsif_else_three_branches(self) -> None:
        """Test IF/ELSIF/ELSE where each keyword has its body inline (on the same line).

        This is the format produced by the TIA Portal parser for Sign.s7dcl:
          IF #x < 0.0 THEN #Sign := -1.0 ;
          ELSIF #x > 0.0 THEN #Sign := 1.0 ;
          ELSE #Sign := 0.0 ;
          END_IF ;

        Regression: commit 58f6883 added inline-body capture after THEN for IF but
        not for ELSIF, and the ELSE check used ``upper == "ELSE"`` which failed to
        match ``ELSE #Sign := 0.0 ;``.  This caused the ELSIF body to be swallowed
        and ``ELSE`` to appear as a literal identifier in the generated Python.
        """
        # Inline format — body on same line as controlling keyword
        scl = (
            "IF # x < 0.0 THEN # Sign := -1.0 ;\n"
            "ELSIF # x > 0.0 THEN # Sign := 1.0 ;\n"
            "ELSE # Sign := 0.0 ;\n"
            "END_IF ;\n"
        )
        result = translate_control_flow(scl)

        # Branch headers
        assert any("if self.x < 0.0:" in line for line in result), f"Missing if branch in {result}"
        assert any("elif self.x > 0.0:" in line for line in result), f"Missing elif branch in {result}"
        assert any("else:" in line for line in result), f"Missing else: in {result}"

        # Bodies must be correctly assigned — no body-stealing, no raw 'ELSE' identifier
        assert any("self.Sign = -1.0" in line for line in result), f"IF body missing in {result}"
        assert any("self.Sign = 1.0" in line for line in result), f"ELSIF body missing in {result}"
        assert any("self.Sign = 0.0" in line for line in result), f"ELSE body missing in {result}"

        # The literal keyword 'ELSE' must not appear as a Python expression
        assert not any(line.strip().startswith("ELSE ") for line in result), (
            f"Raw ELSE keyword found in generated Python: {result}"
        )

        # elif branch body must be indented under elif, not elsewhere
        result_combined = "\n".join(result)
        elif_idx = next(i for i, l in enumerate(result) if "elif" in l)
        # The line immediately after elif must contain the ELSIF body
        assert "self.Sign = 1.0" in result[elif_idx + 1], (
            f"ELSIF body not directly under elif: {result}"
        )

    def test_if_with_and_or(self) -> None:
        """Test IF with AND/OR operators."""
        scl = """
        IF #a AND #b THEN
            #c := TRUE;
        END_IF;
        """
        result = translate_control_flow(scl)

        assert any("and" in line.lower() for line in result)

    def test_if_with_not(self) -> None:
        """Test IF with NOT operator."""
        scl = """
        IF NOT(#flag) THEN
            #output := FALSE;
        END_IF;
        """
        result = translate_control_flow(scl)

        assert any("not" in line.lower() for line in result)

    def test_nested_if(self) -> None:
        """Test nested IF statements."""
        scl = """
        IF #outer THEN
            IF #inner THEN
                #x := 1;
            END_IF;
        END_IF;
        """
        result = translate_control_flow(scl)

        # Should have two if statements
        if_count = sum(1 for line in result if line.strip().startswith("if "))
        assert if_count == 2


class TestCaseTranslation:
    """Tests for CASE statement translation."""

    def test_simple_case(self) -> None:
        """Test simple CASE statement."""
        scl = """
        CASE #state OF
            #STATE_A:
                #output := 1;
            #STATE_B:
                #output := 2;
        END_CASE;
        """
        result = translate_control_flow(scl)

        assert any("if self.state ==" in line for line in result)
        assert any("elif self.state ==" in line for line in result)

    def test_case_with_numbers(self) -> None:
        """Test CASE with numeric values."""
        scl = """
        CASE #value OF
            0:
                #result := 'zero';
            1:
                #result := 'one';
            2:
                #result := 'two';
        END_CASE;
        """
        result = translate_control_flow(scl)

        assert any("== 0" in line for line in result)
        assert any("== 1" in line for line in result)
        assert any("== 2" in line for line in result)

    def test_case_with_nested_if(self) -> None:
        """Test CASE with nested IF."""
        scl = """
        CASE #activeState OF
            #NO_ALARM:
                IF #trigger THEN
                    #activeState := #ALARM;
                END_IF;
            #ALARM:
                IF NOT(#trigger) THEN
                    #activeState := #NO_ALARM;
                END_IF;
        END_CASE;
        """
        result = translate_control_flow(scl)

        # Should have case branches and nested ifs
        if_count = sum(1 for line in result if "if " in line.lower())
        assert if_count >= 2


class TestWhileTranslation:
    """Tests for WHILE statement translation."""

    def test_simple_while(self) -> None:
        """Test simple WHILE statement."""
        scl = """
        WHILE (#i < 10) DO
            #i += 1;
        END_WHILE;
        """
        result = translate_control_flow(scl)

        assert any("while" in line for line in result)
        assert any("self.i < 10" in line for line in result)

    def test_while_with_condition(self) -> None:
        """Test WHILE with complex condition."""
        scl = """
        WHILE (#index < #upperBound - 1) DO
            #index += 2;
        END_WHILE;
        """
        result = translate_control_flow(scl)

        assert any("while" in line for line in result)
        assert any("self.upperBound" in line for line in result)

    def test_while_with_nested_if(self) -> None:
        """Test WHILE with nested IF."""
        scl = """
        WHILE (#running) DO
            IF #shouldStop THEN
                #running := FALSE;
            END_IF;
        END_WHILE;
        """
        result = translate_control_flow(scl)

        assert any("while" in line for line in result)
        assert any("if " in line for line in result)


class TestForTranslation:
    """Tests for FOR statement translation."""

    def test_simple_for(self) -> None:
        """Test simple FOR statement."""
        scl = """
        FOR #i := 1 TO 10 DO
            #sum += #i;
        END_FOR;
        """
        result = translate_control_flow(scl)

        assert any("for self.i in range" in line for line in result)
        assert any("1, 10 + 1" in line or "1, 11" in line for line in result)

    def test_for_with_step(self) -> None:
        """Test FOR with BY step."""
        scl = """
        FOR #i := 0 TO 20 BY 2 DO
            #arr[#i] := 0;
        END_FOR;
        """
        result = translate_control_flow(scl)

        assert any("for self.i in range" in line for line in result)
        assert any("2)" in line for line in result)  # step value

    def test_for_with_expression_bounds(self) -> None:
        """Test FOR with expression bounds."""
        scl = """
        FOR #idx := #start TO #end DO
            #data[#idx] := 0;
        END_FOR;
        """
        result = translate_control_flow(scl)

        assert any("self.start" in line for line in result)
        assert any("self.end" in line for line in result)


class TestCompoundAssignment:
    """Tests for compound assignment operators."""

    def test_plus_equals(self) -> None:
        """Test += operator."""
        scl = "#counter += 1;"
        result = translate_control_flow(scl)

        assert len(result) == 1
        assert "self.counter += 1" in result[0]

    def test_minus_equals(self) -> None:
        """Test -= operator."""
        scl = "#value -= 5;"
        result = translate_control_flow(scl)

        assert len(result) == 1
        assert "self.value -= 5" in result[0]

    def test_multiply_equals(self) -> None:
        """Test *= operator."""
        scl = "#scale *= 2;"
        result = translate_control_flow(scl)

        assert len(result) == 1
        assert "self.scale *= 2" in result[0]


class TestComplexScenarios:
    """Tests for complex code scenarios."""

    def test_simple_alarm_pattern(self) -> None:
        """Test ValveControl-like state machine."""
        scl = """
        CASE #activeState OF
            #NO_ALARM:
                IF #alarmTrigger THEN
                    #activeState := #ALARM;
                END_IF;
            #ALARM:
                IF NOT(#alarmTrigger) THEN
                    #activeState := #NO_ALARM;
                END_IF;
        END_CASE;
        #alarmState := #activeState;
        """
        result = translate_control_flow(scl)

        # Should translate successfully
        assert len(result) > 0

        # Should have CASE branches
        if_count = sum(1 for line in result if line.strip().startswith("if "))
        elif_count = sum(1 for line in result if line.strip().startswith("elif "))
        assert if_count >= 2 or (if_count >= 1 and elif_count >= 1)

        # Should have final assignment
        assert any("self.alarmState = self.activeState" in line for line in result)

    def test_swap_bytes_pattern(self) -> None:
        """Test SwapBytesInWord-like loop."""
        scl = """
        WHILE (#tempSwapIndex < #tempUpperIndex - 1) DO
            IF #tempSwapIndex > #start_position AND #tempSwapIndex < #stop_position THEN
                #value := 0;
            END_IF;
            #tempSwapIndex += 2;
        END_WHILE;
        """
        result = translate_control_flow(scl)

        assert any("while" in line for line in result)
        assert any("if " in line for line in result)
        assert any("+= 2" in line for line in result)


class TestControlFlowTranslatorClass:
    """Tests for ControlFlowTranslator class."""

    def test_translator_instance(self) -> None:
        """Test creating translator instance."""
        translator = ControlFlowTranslator()
        assert translator is not None

    def test_translate_block_method(self) -> None:
        """Test translate_block method."""
        translator = ControlFlowTranslator()
        result = translator.translate_block("#x := 1;")

        assert len(result) == 1
        assert "self.x = 1" in result[0]

    def test_preprocess_skips_comments(self) -> None:
        """Test that preprocessing skips comments."""
        scl = """
        // This is a comment
        #x := 1;
        // Another comment
        #y := 2;
        """
        result = translate_control_flow(scl)

        # Should only have the two assignments
        assert len(result) == 2

    def test_preprocess_skips_regions(self) -> None:
        """Test that preprocessing skips REGION markers."""
        scl = """
        REGION Test
            #x := 1;
        END_REGION
        """
        result = translate_control_flow(scl)

        # Should only have the assignment
        assert len(result) == 1
        assert "self.x = 1" in result[0]

    def test_preprocess_skips_pragmas(self) -> None:
        """Test that preprocessing skips pragma lines."""
        scl = """
        { S7_Language := "SCL" }
        #x := 1;
        """
        result = translate_control_flow(scl)

        assert len(result) == 1
        assert "self.x = 1" in result[0]

    def test_assignment_of_function_call_result(self) -> None:
        """Test that `#var := FUNC(#arg);` produces assignment, not comparison.

        SCL: #ca := COS(#alpha);
        Must transpile to: self.ca = math.cos(self.alpha)
        NOT:              self.ca == math.cos(self.alpha)

        Regression test for the bug where the FB-call dispatch pattern
        (#name(...)) matched before the assignment (:=) check, routing
        function-call assignments through translate_fb_call() which
        emitted == instead of =.
        """
        scl = "#ca := COS(#alpha);"
        result = translate_control_flow(scl)

        assert len(result) == 1
        # Must be an assignment (single =), not a comparison (==)
        assert "self.ca = math.cos(self.alpha)" in result[0]
        assert "self.ca == math.cos(self.alpha)" not in result[0]


class TestMultiLineAssignments:
    """Tests for TIA Portal multi-line assignment continuation.

    TIA Portal sometimes splits a single SCL assignment across two source lines,
    with the LHS and ':=' on one line and the RHS on the next line:

        #matrixResult[#i, #k] :=
        #matrixResult[#i, #k] * #matrixResult[#k, #k];

    This must produce a single valid Python assignment, not two statements.
    """

    def test_continuation_line_joined(self) -> None:
        """LHS-only := line followed by RHS line must produce one assignment."""
        scl = "# a := \n# b * # c ;"
        result = translate_control_flow(scl)
        # Must produce exactly ONE Python statement
        assert len(result) == 1
        assert "self.a = self.b * self.c" in result[0]

    def test_continuation_line_inside_for_loop(self) -> None:
        """Multi-line assignment inside FOR loop must work correctly."""
        scl = (
            "FOR # i := 0 TO 2 DO \n"
            "# arr [ # i ] := \n"
            "# arr [ # i ] * 2.0 ; \n"
            "END_FOR ;"
        )
        result = translate_control_flow(scl)
        # Result must be a for loop with a body assignment (not empty body)
        combined = "\n".join(result)
        assert "for self.i in range(" in combined
        assert "self.arr" in combined
        # Must not contain a dangling assignment with no RHS
        for line in result:
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#") and not stripped.startswith("//"):
                # Ensure no line ends with bare "=" or "= "
                assert not stripped.endswith("= "), f"Dangling assignment: {stripped!r}"


class TestIdentifierSafeKeywordSpacing:
    """Regression tests for commit 2e30253: TO/DO/OF/BY spacing must not split identifiers.

    The lookbehind was tightened from ``(?<=[^\\s])`` to ``(?<=[^\\sA-Za-z])`` so
    that keywords are only spaced when glued to a non-letter (digit, ')', ']') —
    the real FOR-range / CASE selector case — and never when they form the tail of
    an alphabetic identifier such as ``triggerGoto``, ``autoBy``, ``infoOf``, or
    ``calDo``.
    """

    # ------------------------------------------------------------------
    # Identifiers that END in a keyword letter-sequence must be preserved
    # ------------------------------------------------------------------

    def test_identifier_ending_in_to_is_not_split(self) -> None:
        """'triggerGoto' must not become 'triggerGo TO'.

        The old regex ``(?<=[^\\s])TO\\b`` fired on the 'o' before 'TO', turning
        the tail of the identifier into a keyword.  The fixed regex requires the
        preceding character to be a non-letter, so alphabetic tails are safe.
        """
        scl = "#triggerGoto := TRUE;"
        result = translate_control_flow(scl)

        combined = " ".join(result)
        assert "triggerGoto" in combined, (
            f"Identifier 'triggerGoto' was mangled: {result}"
        )
        assert "triggerGo" not in combined.replace("triggerGoto", ""), (
            f"'TO' was spuriously inserted into 'triggerGoto': {result}"
        )

    def test_identifier_ending_in_by_is_not_split(self) -> None:
        """'autoBy' must not become 'auto BY'."""
        scl = "#autoBy := 1;"
        result = translate_control_flow(scl)

        combined = " ".join(result)
        assert "autoBy" in combined, f"Identifier 'autoBy' was mangled: {result}"

    def test_identifier_ending_in_of_is_not_split(self) -> None:
        """'infoOf' must not become 'info OF'."""
        scl = "#infoOf := 42;"
        result = translate_control_flow(scl)

        combined = " ".join(result)
        assert "infoOf" in combined, f"Identifier 'infoOf' was mangled: {result}"

    def test_identifier_ending_in_do_is_not_split(self) -> None:
        """'calDo' must not become 'cal DO'."""
        scl = "#calDo := FALSE;"
        result = translate_control_flow(scl)

        combined = " ".join(result)
        assert "calDo" in combined, f"Identifier 'calDo' was mangled: {result}"

    def test_multiple_suffix_identifiers_in_one_block(self) -> None:
        """All four suffix variants survive in one block, verifying no cross-contamination."""
        scl = """
        #triggerGoto := TRUE;
        #autoBy := 1;
        #infoOf := 42;
        #calDo := FALSE;
        """
        result = translate_control_flow(scl)
        combined = " ".join(result)

        assert "triggerGoto" in combined, f"'triggerGoto' mangled: {result}"
        assert "autoBy" in combined, f"'autoBy' mangled: {result}"
        assert "infoOf" in combined, f"'infoOf' mangled: {result}"
        assert "calDo" in combined, f"'calDo' mangled: {result}"

    # ------------------------------------------------------------------
    # Genuinely-glued keywords (non-letter before keyword) MUST be spaced
    # ------------------------------------------------------------------

    def test_glued_to_in_for_range_is_spaced(self) -> None:
        """A digit-glued ``0TO #n`` range must still get a space.

        The ``\b`` boundary only fires when ``TO`` is followed by a non-word
        character (space, ``#``).  The digit ``0`` before ``TO`` is non-letter, so
        ``(?<=[^\\sA-Za-z])TO\\b`` fires on ``0TO #n`` and inserts the space,
        yielding a parseable FOR range.
        """
        # '0TO #n': digit before TO, word boundary fires because '#' follows.
        scl = "FOR #i := 0TO #n DO\n    #x := #i;\nEND_FOR;"
        result = translate_control_flow(scl)

        combined = " ".join(result)
        # The FOR loop must have been parsed (range produced)
        assert "for self.i in range(" in combined, (
            f"FOR loop not translated (glued 0TO not spaced): {result}"
        )
        # The loop body assignment must be present
        assert "self.x = self.i" in combined, (
            f"FOR loop body missing: {result}"
        )

    def test_glued_to_after_bracket_is_spaced(self) -> None:
        """A ``]TO`` form (array-element upper bound) must get a space.

        ``]`` is a non-letter, so ``(?<=[^\\sA-Za-z])TO\\b`` fires on ``arr[0]TO``
        and inserts the required space between the bound expression and the keyword.
        """
        scl = "FOR #i := #arr[0]TO 5 DO\n    #x := #i;\nEND_FOR;"
        result = translate_control_flow(scl)

        combined = " ".join(result)
        assert "for self.i in range(" in combined, (
            f"FOR loop not translated (glued ]TO not spaced): {result}"
        )
        assert "self.arr[0]" in combined, (
            f"Lower bound missing: {result}"
        )
        assert "self.x = self.i" in combined, (
            f"FOR loop body missing: {result}"
        )
