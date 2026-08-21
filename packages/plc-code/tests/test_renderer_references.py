"""Unit tests for `render` over literals and references (Task 3).

Every expected value for the four probed rows was taken by running
`ExpressionTranslator().translate(...)` directly (see the task report), not copied
from a table -- three of the assumptions that motivated probing turned out wrong,
`16#FF` renders lowercase (`0xff`) being one of them.
"""

from __future__ import annotations

import pytest

from plc_code.executor.renderer import UnsupportedExpression, render
from plc_code.parser.expressions import Grouping, Index, Literal, Member, TypedLiteral, VariableRef


def test_a_local_variable_becomes_an_attribute() -> None:
    assert render(VariableRef(line=1, column=1, name="a", is_local=True)) == "self.a"


def test_a_boolean_literal_becomes_a_python_boolean() -> None:
    assert render(Literal(line=1, column=1, value="TRUE")) == "True"
    assert render(Literal(line=1, column=1, value="false")) == "False"


def test_a_hex_literal_is_lowercase() -> None:
    assert render(TypedLiteral(line=1, column=1, prefix="16", value="FF")) == "0xff"


def test_a_duration_literal_becomes_seconds() -> None:
    assert render(TypedLiteral(line=1, column=1, prefix="T", value="5s")) == "5.0"


def test_a_global_db_member_goes_through_the_runtime() -> None:
    node = Member(
        line=1,
        column=1,
        base=VariableRef(line=1, column=1, name="DB", is_local=False),
        name="member",
    )
    assert render(node) == 'self._runtime.global_dbs["DB"].member'


def test_a_two_dimensional_index_chains() -> None:
    node = Index(
        line=1,
        column=1,
        base=VariableRef(line=1, column=1, name="arr", is_local=True),
        indices=[
            VariableRef(line=1, column=1, name="i", is_local=True),
            VariableRef(line=1, column=1, name="j", is_local=True),
        ],
    )
    assert render(node) == "self.arr[self.i][self.j]"


def test_grouping_keeps_its_parentheses() -> None:
    node = Grouping(line=1, column=1, inner=VariableRef(line=1, column=2, name="a", is_local=True))
    assert render(node) == "(self.a)"


def test_a_node_with_no_visitor_raises() -> None:
    with pytest.raises(UnsupportedExpression):
        render(object())  # type: ignore[arg-type]


def test_a_quoted_global_alone_keeps_its_quotes() -> None:
    """Structural: `GLOBAL_DB_PATTERN` requires a `.` right after the quoted name --
    a bare global reference is left untouched by the current translator."""
    assert render(VariableRef(line=1, column=1, name="Db", is_local=False)) == '"Db"'


def test_eno_is_the_one_bare_global() -> None:
    """The current translator's only unquoted, non-local identifier."""
    assert render(VariableRef(line=1, column=1, name="ENO", is_local=False)) == "ENO"


def test_an_absolute_address_is_unchanged() -> None:
    assert render(VariableRef(line=1, column=1, name="I0", is_absolute=True, is_local=False)) == "%I0"


def test_a_local_member_carries_its_own_hash() -> None:
    """`.#name` -- the current translator's `INSTANCE_VAR_PATTERN` still matches the
    `#name` inside a member chain, so the member itself also becomes `self.name`."""
    node = Member(
        line=1,
        column=1,
        base=VariableRef(line=1, column=1, name="a", is_local=True),
        name="b",
        is_local=True,
    )
    assert render(node) == "self.a.self.b"


def test_an_absolute_member_keeps_its_percent() -> None:
    node = Member(
        line=1,
        column=1,
        base=VariableRef(line=1, column=1, name="a", is_local=True),
        name="DBX0",
        is_absolute=True,
    )
    assert render(node) == "self.a.%DBX0"


def test_a_quoted_member_keeps_its_quotes() -> None:
    node = Member(
        line=1,
        column=1,
        base=VariableRef(line=1, column=1, name="Db", is_local=False),
        name="type",
        is_quoted=True,
    )
    assert render(node) == 'self._runtime.global_dbs["Db"]."type"'


def test_an_index_base_keeps_a_global_quoted_rather_than_a_runtime_lookup() -> None:
    """Only `Member` substitutes the runtime lookup; `Index` does not -- matching
    `GLOBAL_DB_PATTERN`, which needs a literal `.` after the quoted name."""
    node = Index(
        line=1,
        column=1,
        base=VariableRef(line=1, column=1, name="Db", is_local=False),
        indices=[VariableRef(line=1, column=1, name="i", is_local=True)],
    )
    assert render(node) == '"Db"[self.i]'
