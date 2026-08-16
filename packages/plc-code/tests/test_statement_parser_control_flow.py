"""Control flow, including the two CASE layouts the text path got wrong.

Both were fixed in the text translator (332bfeb) after they mistranslated
production code; the parser must handle them from the start:
  - `ELSE` in a CASE carries no colon;
  - a label may carry its first statement on the same line.
"""

from plc_code.parser.lexer import TokenType, tokenize
from plc_code.parser.statement_parser import parse_statements
from plc_code.parser.statements import Assignment, Case, For, If, While


def _parse(source: str):
    return parse_statements([t for t in tokenize(source) if t.type is not TokenType.EOF])


class TestIf:
    def test_simple_if(self) -> None:
        result = _parse("IF #a > 1 THEN #b := 2; END_IF;")
        assert result.errors == []
        node = result.statements[0]
        assert isinstance(node, If)
        assert len(node.branches) == 1
        assert isinstance(node.branches[0].body[0], Assignment)

    def test_elsif_is_another_branch(self) -> None:
        node = _parse("IF #a THEN #b := 1; ELSIF #c THEN #b := 2; END_IF;").statements[0]
        assert isinstance(node, If)
        assert len(node.branches) == 2

    def test_else_body(self) -> None:
        node = _parse("IF #a THEN #b := 1; ELSE #b := 2; END_IF;").statements[0]
        assert isinstance(node, If)
        assert len(node.else_body) == 1

    def test_nested_if(self) -> None:
        result = _parse("IF #a THEN IF #b THEN #c := 1; END_IF; END_IF;")
        assert result.errors == []
        outer = result.statements[0]
        assert isinstance(outer, If)
        assert isinstance(outer.branches[0].body[0], If)


class TestCase:
    def test_label_on_its_own_line(self) -> None:
        result = _parse("CASE #a OF\n 1:\n #b := 10;\n ELSE\n #b := 99;\n END_CASE;")
        assert result.errors == []
        node = result.statements[0]
        assert isinstance(node, Case)
        assert len(node.branches) == 1
        assert len(node.default) == 1

    def test_label_on_the_statement_line(self) -> None:
        """Used to drop the whole CASE in the text path."""
        result = _parse("CASE #a OF 1: #b := 10; 2: #b := 20; ELSE #b := 99; END_CASE;")
        assert result.errors == []
        node = result.statements[0]
        assert isinstance(node, Case)
        assert len(node.branches) == 2

    def test_bare_else_has_no_colon(self) -> None:
        node = _parse("CASE #a OF 1: #b := 1; ELSE #b := 9; END_CASE;").statements[0]
        assert isinstance(node, Case)
        assert node.default

    def test_multi_value_label(self) -> None:
        node = _parse("CASE #a OF 1, 2: #b := 1; END_CASE;").statements[0]
        assert isinstance(node, Case)
        assert len(node.branches[0].values) == 2

    def test_quoted_symbolic_label(self) -> None:
        node = _parse('CASE #a OF "MODE_ONE": #b := 1; END_CASE;').statements[0]
        assert isinstance(node, Case)
        assert len(node.branches) == 1

    def test_no_default(self) -> None:
        node = _parse("CASE #a OF 1: #b := 1; END_CASE;").statements[0]
        assert isinstance(node, Case)
        assert node.default == []


class TestLoops:
    def test_for_without_step(self) -> None:
        node = _parse("FOR #i := 1 TO 9 DO #b := #i; END_FOR;").statements[0]
        assert isinstance(node, For)
        assert node.step == []
        assert len(node.body) == 1

    def test_for_with_step(self) -> None:
        node = _parse("FOR #i := 1 TO 9 BY 2 DO #b := #i; END_FOR;").statements[0]
        assert isinstance(node, For)
        assert node.step

    def test_while(self) -> None:
        node = _parse("WHILE #a < 5 DO #a := #a + 1; END_WHILE;").statements[0]
        assert isinstance(node, While)
        assert len(node.body) == 1
