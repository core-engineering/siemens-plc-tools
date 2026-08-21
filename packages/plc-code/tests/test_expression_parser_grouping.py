"""Parentheses are source, and the tree has to keep them.

`_parse_grouping` returned its inner expression, so `(#a AND #b) OR #c` and
`#a AND #b OR #c` produced identical trees. That is fine for evaluating and
wrong for rendering: a consumer that cannot tell them apart cannot write either
one back out.
"""

from plc_code.parser.expression_parser import parse_expression
from plc_code.parser.expressions import BinaryOp, Grouping, VariableRef
from plc_code.parser.lexer import TokenType, tokenize


def _parse(source: str):
    return parse_expression([t for t in tokenize(source) if t.type is not TokenType.EOF])


def test_a_grouped_expression_keeps_its_parentheses() -> None:
    result = _parse("(#a)")
    assert result.errors == []
    node = result.expression
    assert isinstance(node, Grouping)
    assert node.inner == VariableRef(line=1, column=2, name="a", is_local=True)


def test_grouping_changes_the_tree_not_only_the_binding() -> None:
    grouped = _parse("(#a AND #b) OR #c").expression
    bare = _parse("#a AND #b OR #c").expression
    assert grouped != bare
    assert isinstance(grouped, BinaryOp)
    assert isinstance(grouped.left, Grouping)
    assert isinstance(bare.left, BinaryOp)


def test_nested_grouping_nests() -> None:
    node = _parse("((#a))").expression
    assert isinstance(node, Grouping)
    assert isinstance(node.inner, Grouping)


def test_a_grouped_call_argument_keeps_its_parentheses() -> None:
    call = _parse("ABS((#a + #b))").expression
    assert isinstance(call.arguments[0].value, Grouping)


def test_a_missing_closing_paren_is_still_an_error() -> None:
    result = _parse("(#a")
    assert result.errors != []
    assert result.expression is None
