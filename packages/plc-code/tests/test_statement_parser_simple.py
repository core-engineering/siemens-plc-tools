"""Simple statements: assignment, call, RETURN, EXIT, and error recovery.

Recovery is the point, not a nicety. Without it one unreadable construct masks
everything after it and the report degrades from "this construct, here" to
"this block fails".
"""

from plc_code.parser.lexer import TokenType, tokenize
from plc_code.parser.statement_parser import parse_statements
from plc_code.parser.statements import Assignment, Call, Exit, Return


def _parse(source: str):
    return parse_statements([t for t in tokenize(source) if t.type is not TokenType.EOF])


class TestAssignment:
    def test_simple_assignment(self) -> None:
        result = _parse("#b := 10;")
        assert result.errors == []
        assert len(result.statements) == 1
        assert isinstance(result.statements[0], Assignment)

    def test_target_and_value_are_token_slices(self) -> None:
        statement = _parse("#b := #a + 1;").statements[0]
        assert isinstance(statement, Assignment)
        assert [t.value for t in statement.target] == ["#", "b"]
        assert [t.value for t in statement.value] == ["#", "a", "+", "1"]

    def test_two_assignments_on_one_line(self) -> None:
        result = _parse("#a := 1; #b := 2;")
        assert result.errors == []
        assert len(result.statements) == 2

    def test_assignment_spanning_several_lines(self) -> None:
        """Line breaks are irrelevant to a token parser."""
        result = _parse("#b :=\n    #a\n    + 1;")
        assert result.errors == []
        assert len(result.statements) == 1


class TestCall:
    def test_input_binding(self) -> None:
        statement = _parse("#timer(IN := #start);").statements[0]
        assert isinstance(statement, Call)
        assert statement.arguments[0].name == "IN"
        assert statement.arguments[0].is_output is False

    def test_output_binding_is_distinguished(self) -> None:
        statement = _parse("#timer(Q => #done);").statements[0]
        assert isinstance(statement, Call)
        assert statement.arguments[0].is_output is True

    def test_mixed_bindings(self) -> None:
        statement = _parse("#timer(IN := #start, PT := T#5s, Q => #done);").statements[0]
        assert isinstance(statement, Call)
        assert [a.is_output for a in statement.arguments] == [False, False, True]

    def test_quoted_callee(self) -> None:
        statement = _parse('"ForwardKinematic"(x := #a);').statements[0]
        assert isinstance(statement, Call)
        # The lexer's STRING token value includes the surrounding quotes
        # (`_scan_string` slices from the opening quote), so the callee name
        # is a substring of the token value, not an exact match to it.
        assert any("ForwardKinematic" in t.value for t in statement.callee)


class TestTerminators:
    def test_return(self) -> None:
        assert isinstance(_parse("RETURN;").statements[0], Return)

    def test_exit(self) -> None:
        assert isinstance(_parse("EXIT;").statements[0], Exit)


class TestErrorRecovery:
    def test_unsupported_construct_is_an_error_not_a_guess(self) -> None:
        result = _parse("GOTO done;")
        assert result.errors
        assert "GOTO" in result.errors[0].token_value.upper()

    def test_recovery_continues_past_the_error(self) -> None:
        """The statement after a bad one must still be parsed."""
        result = _parse("GOTO done; #b := 10;")
        assert result.errors
        assert any(isinstance(s, Assignment) for s in result.statements)

    def test_error_carries_a_source_position(self) -> None:
        error = _parse("#a := 1;\nGOTO done;").errors[0]
        assert error.line == 2
        assert error.column > 0

    def test_repeat_is_reported_not_supported(self) -> None:
        result = _parse("REPEAT #b := 1; UNTIL #b > 5 END_REPEAT;")
        assert result.errors
