"""Tests for code generation utilities."""

from plc_code.executor.codegen import (
    translate_assignment,
    translate_expression,
    translate_fb_call,
)


class TestExpressionTranslator:
    """Tests for expression translation."""

    def test_instance_variable(self) -> None:
        """Test translating instance variables."""
        assert translate_expression("#myVar") == "self.myVar"
        assert translate_expression("#activeState") == "self.activeState"

    def test_multiple_instance_variables(self) -> None:
        """Test translating multiple instance variables."""
        result = translate_expression("#a + #b")
        assert result == "self.a + self.b"

    def test_global_db_access(self) -> None:
        """Test translating global DB access."""
        result = translate_expression('"ProcessData".status.value')
        assert 'self._runtime.global_dbs["ProcessData"]' in result
        assert ".status.value" in result

    def test_operators_and_or(self) -> None:
        """Test translating AND/OR operators."""
        assert "and" in translate_expression("#a AND #b")
        assert "or" in translate_expression("#a OR #b")

    def test_operator_not(self) -> None:
        """Test translating NOT operator."""
        result = translate_expression("NOT #flag")
        assert "not" in result
        assert "self.flag" in result

    def test_operator_assignment(self) -> None:
        """Test translating assignment operator."""
        # Note: := in expression context becomes =
        result = translate_expression("#a := 5")
        assert "=" in result
        assert ":=" not in result

    def test_operator_not_equal(self) -> None:
        """Test translating <> operator."""
        result = translate_expression("#a <> #b")
        assert "!=" in result
        assert "<>" not in result

    def test_boolean_literals(self) -> None:
        """Test translating boolean literals."""
        assert "True" in translate_expression("TRUE")
        assert "False" in translate_expression("FALSE")
        assert "True" in translate_expression("true")

    def test_builtin_int_to_real(self) -> None:
        """Test translating INT_TO_REAL."""
        result = translate_expression("INT_TO_REAL(#value)")
        assert "float(" in result

    def test_builtin_abs(self) -> None:
        """Test translating ABS."""
        result = translate_expression("ABS(#value)")
        assert "abs(" in result

    def test_complex_expression(self) -> None:
        """Test translating complex expression."""
        expr = "#a AND NOT #b OR #c"
        result = translate_expression(expr)
        assert "and" in result
        assert "not" in result
        assert "or" in result
        assert "self.a" in result
        assert "self.b" in result
        assert "self.c" in result


class TestStatementTranslator:
    """Tests for statement translation."""

    def test_simple_assignment(self) -> None:
        """Test translating simple assignment."""
        result = translate_assignment("#output := #input;")
        assert result == "self.output = self.input"

    def test_assignment_with_expression(self) -> None:
        """Test translating assignment with expression."""
        result = translate_assignment("#result := #a + #b;")
        assert "self.result" in result
        assert "self.a + self.b" in result

    def test_assignment_with_literal(self) -> None:
        """Test translating assignment with literal."""
        result = translate_assignment("#activeState := 0;")
        assert "self.activeState = 0" in result


class TestFBCallTranslation:
    """Tests for FB call translation."""

    def test_simple_fb_call(self) -> None:
        """Test translating simple FB call."""
        result = translate_fb_call("#myTimer(IN := #input, PT := #delay);")
        assert len(result) >= 1
        assert "self.myTimer(" in result[0]
        assert "IN=self.input" in result[0]
        assert "PT=self.delay" in result[0]

    def test_fb_call_with_output(self) -> None:
        """Test translating FB call with output parameter."""
        result = translate_fb_call("#timer(IN := #in, Q => #out);")
        assert len(result) >= 2
        # First line is the call
        assert "self.timer(" in result[0]
        # Second line is output assignment
        assert "self.out = self.timer.Q" in result[1]

    def test_timer_call_adds_clock(self) -> None:
        """Test that timer calls add clock parameter."""
        result = translate_fb_call("#antiBouncingTimer(IN := #input, PT := #delay);")
        assert "clock=self._runtime.clock" in result[0]


class TestBuiltinTypeConversions:
    """Tests for SCL type conversion builtins (REAL_TO_LREAL etc.)."""

    def test_real_to_lreal(self) -> None:
        """REAL_TO_LREAL(#x) must translate to float(self.x) (identity cast in Python)."""
        result = translate_expression("REAL_TO_LREAL(#dampingLambda)")
        # In Python float == LReal, so identity conversion is fine.
        # Must not raise and must produce valid Python (not the raw SCL literal).
        assert "self.dampingLambda" in result
        assert "REAL_TO_LREAL" not in result

    def test_lreal_to_real(self) -> None:
        """LREAL_TO_REAL(#x) must translate without leaving the SCL name."""
        result = translate_expression("LREAL_TO_REAL(#val)")
        assert "self.val" in result
        assert "LREAL_TO_REAL" not in result


class TestSpacedComparisonOperators:
    """Tests for spaced comparison operators produced by the TIA Portal lexer."""

    def test_spaced_less_or_equal(self) -> None:
        """ABS(x - 0) < = (y) must become abs(x - 0) <= y (not < == y)."""
        # The parser lexes <= as two tokens: '<' and '=' with a space between.
        result = translate_expression("ABS(#a - 0.0) < = (#b * ABS(#a))")
        assert "<=" in result
        assert "< ==" not in result
        assert "< =" not in result

    def test_spaced_greater_or_equal(self) -> None:
        """Similarly >= (as '> =') must become >=."""
        result = translate_expression("#a > = #b")
        assert ">=" in result
        assert "> =" not in result
