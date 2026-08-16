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


def _assignments(statements) -> list[Assignment]:
    """Every Assignment reachable from a statement list, including inside a Case."""
    found: list[Assignment] = []
    for statement in statements:
        if isinstance(statement, Assignment):
            found.append(statement)
        elif isinstance(statement, Case):
            for branch in statement.branches:
                found.extend(_assignments(branch.body))
            found.extend(_assignments(statement.default))
    return found


def _targets(assignment: Assignment) -> list[str]:
    return [t.value for t in assignment.target]


class TestMalformedCase:
    """A CASE branch that fails to open with a label must not lose tokens.

    `_parse_case_labels` originally scanned speculatively into a buffer and
    discarded that buffer on failure, silently dropping whatever it had
    scanned with no statement and no recorded error. These reproduce the
    reviewer's finding directly and guard against it recurring.
    """

    def test_unlabelled_branch_does_not_swallow_statements(self) -> None:
        """The reviewer's exact case: a branch opening with a bare statement."""
        result = _parse("CASE #a OF #x := 1; END_CASE; #c := 2;")
        assignments = _assignments(result.statements)
        # #x := 1 must not vanish: either it shows up as a statement
        # (nested in the Case or spilled out of it), or an error was
        # recorded for the span that failed to open as a label.
        x_present = any(_targets(a) == ["#", "x"] for a in assignments)
        assert x_present or result.errors
        # #c := 2, after END_CASE, must still parse regardless.
        assert any(_targets(a) == ["#", "c"] for a in assignments)

    def test_second_branch_without_label_keeps_first_branch_intact(self) -> None:
        result = _parse("CASE #a OF 1: #b := 1; 2 #c := 2; END_CASE;")
        node = result.statements[0]
        assert isinstance(node, Case)
        assert [t.value for t in node.branches[0].values[0]] == ["1"]
        first_body = node.branches[0].body
        assert isinstance(first_body[0], Assignment)
        assert _targets(first_body[0]) == ["#", "b"]

    def test_labelless_body_followed_by_else_still_recognises_default(self) -> None:
        result = _parse("CASE #a OF #x := 1; ELSE #b := 9; END_CASE;")
        node = result.statements[0]
        assert isinstance(node, Case)
        assert node.default
        assert any(_targets(a) == ["#", "b"] for a in _assignments(node.default))
