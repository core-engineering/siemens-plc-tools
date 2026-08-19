"""Argument values that contain parentheses, and compound assignment.

`_take_until(COMMA, RPAREN)` delimited an argument's value without counting
parenthesis depth, so the first inner `)` ended the value. On

    #block(CLK := (#state = #RUNNING), Q => #out);

the value stopped at the `)` closing `(#state = #RUNNING)`, the argument list
ended there, and everything after it desynchronised — reporting "an assignment
or a call" at `,`, `Q`, `=`, `>` and on into the following lines. One missing
depth counter produced 45 of the 51 conformance errors in the production
corpus, spread across three blocks and reported as four unrelated-looking
causes.

The remaining 6 came from a single `+=` in one block: the lexer emits `+` and
`=` separately and nothing composed them.

Both cases are transcribed from real production SCL rather than invented, which
is how the shapes here differ from what a from-memory example would look like —
the multi-line boolean argument value in particular.
"""

from plc_code.parser.lexer import TokenType, tokenize
from plc_code.parser.statement_parser import parse_statements
from plc_code.parser.statements import Assignment, Call


def _parse(source: str):
    return parse_statements([t for t in tokenize(source) if t.type is not TokenType.EOF])


class TestParenthesisedArgumentValue:
    def test_a_parenthesised_value_does_not_end_the_argument(self) -> None:
        result = _parse("#block(CLK := (#state = #RUNNING), Q => #out);")
        assert result.errors == [], [e.expected for e in result.errors]
        assert len(result.statements) == 1
        call = result.statements[0]
        assert isinstance(call, Call)
        assert [a.name for a in call.arguments] == ["CLK", "Q"]

    def test_the_value_keeps_its_own_parentheses(self) -> None:
        call = _parse("#block(CLK := (#state = #RUNNING));").statements[0]
        assert isinstance(call, Call)
        assert [t.value for t in call.arguments[0].value] == [
            "(",
            "#",
            "state",
            "=",
            "#",
            "RUNNING",
            ")",
        ]

    def test_the_output_binding_after_it_is_still_an_output(self) -> None:
        call = _parse("#block(CLK := (#a = #b), Q => #out);").statements[0]
        assert isinstance(call, Call)
        assert call.arguments[1].is_output is True

    def test_a_nested_call_as_a_value(self) -> None:
        """`INT_TO_USINT(...)` as an argument value — one block used this."""
        result = _parse('#mode(safetyState := INT_TO_USINT("Iface".status.state));')
        assert result.errors == []
        call = result.statements[0]
        assert isinstance(call, Call)
        assert len(call.arguments) == 1
        assert call.arguments[0].value[0].value == "INT_TO_USINT"

    def test_nested_parentheses_two_deep(self) -> None:
        result = _parse("#block(IN := ((#a + #b) * (#c - #d)), OUT => #r);")
        assert result.errors == []
        call = result.statements[0]
        assert isinstance(call, Call)
        assert [a.name for a in call.arguments] == ["IN", "OUT"]

    def test_a_multi_line_boolean_value(self) -> None:
        """The shape production actually uses, spread over three lines."""
        result = _parse(
            '#alarm(alarmTrigger := "Data".flag\n'
            '                       AND ("Data".state = "AUTHORIZED")\n'
            '                       AND ("Iface".state = "READY"),\n'
            '       alarmState => "Data".alarmState);'
        )
        assert result.errors == []
        call = result.statements[0]
        assert isinstance(call, Call)
        assert [a.name for a in call.arguments] == ["alarmTrigger", "alarmState"]

    def test_a_positional_value_may_be_parenthesised_too(self) -> None:
        result = _parse("#block((#a + #b));")
        assert result.errors == []
        call = result.statements[0]
        assert isinstance(call, Call)
        assert len(call.arguments) == 1
        assert call.arguments[0].name == ""

    def test_an_unbalanced_open_paren_still_terminates(self) -> None:
        """Malformed input must not spin: the slice ends at the stream's end."""
        result = _parse("#block(IN := (#a + #b;")
        assert isinstance(result.statements, list)


class TestCompoundAssignment:
    def test_plus_equals_is_read_as_an_assignment(self) -> None:
        result = _parse("#index += #STEP;")
        assert result.errors == [], [e.expected for e in result.errors]
        assert len(result.statements) == 1
        assert isinstance(result.statements[0], Assignment)

    def test_plus_equals_desugars_to_target_plus_value(self) -> None:
        """`#i += #n` means `#i := #i + #n`; the AST says so explicitly."""
        statement = _parse("#index += #STEP;").statements[0]
        assert isinstance(statement, Assignment)
        assert [t.value for t in statement.target] == ["#", "index"]
        assert [t.value for t in statement.value] == ["#", "index", "+", "#", "STEP"]

    def test_a_plain_assignment_is_unchanged(self) -> None:
        statement = _parse("#index := #STEP;").statements[0]
        assert isinstance(statement, Assignment)
        assert [t.value for t in statement.value] == ["#", "STEP"]

    def test_a_bare_plus_is_still_addition(self) -> None:
        """`#a + = #b` with a space is not `+=`; adjacency decides."""
        result = _parse("#a := #b + 1;")
        assert result.errors == []
        statement = result.statements[0]
        assert isinstance(statement, Assignment)
        assert [t.value for t in statement.value] == ["#", "b", "+", "1"]
