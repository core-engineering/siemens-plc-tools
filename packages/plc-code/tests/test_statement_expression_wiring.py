"""Statements now carry the tree alongside the slice.

The convention, applied as written: the existing field keeps its name and its
`list[Token]` type, and the tree is added under the same name suffixed `_expr`.
No existing field changes type, so no current consumer breaks — which is the
only reason this task can be small.
"""

from plc_code.parser.expressions import BinaryOp, VariableRef
from plc_code.parser.lexer import TokenType, tokenize
from plc_code.parser.statement_parser import parse_statements
from plc_code.parser.statements import Assignment, Call, If


def _parse(source: str):
    return parse_statements([t for t in tokenize(source) if t.type is not TokenType.EOF])


class TestAssignment:
    def test_the_token_slice_is_unchanged(self) -> None:
        statement = _parse("#b := #a + 1;").statements[0]
        assert isinstance(statement, Assignment)
        assert [t.value for t in statement.value] == ["#", "a", "+", "1"]

    def test_the_tree_is_available_alongside(self) -> None:
        statement = _parse("#b := #a + 1;").statements[0]
        assert isinstance(statement, Assignment)
        assert isinstance(statement.value_expr, BinaryOp)
        assert statement.value_expr.operator == "+"

    def test_the_target_has_a_tree_too(self) -> None:
        statement = _parse("#b := 1;").statements[0]
        assert isinstance(statement, Assignment)
        assert isinstance(statement.target_expr, VariableRef)


class TestCall:
    def test_an_argument_value_has_a_tree(self) -> None:
        statement = _parse("#block(CLK := (#state = #RUNNING));").statements[0]
        assert isinstance(statement, Call)
        assert isinstance(statement.arguments[0].value_expr, BinaryOp)


class TestIf:
    def test_a_condition_has_a_tree(self) -> None:
        statement = _parse("IF #a > 1 THEN #b := 1; END_IF;").statements[0]
        assert isinstance(statement, If)
        assert isinstance(statement.branches[0].condition_expr, BinaryOp)


class TestUnparseable:
    def test_a_bad_expression_leaves_none_and_keeps_the_slice(self) -> None:
        result = _parse("#b := @;")
        statement = result.statements[0]
        assert isinstance(statement, Assignment)
        assert statement.value_expr is None
        assert statement.value != []
