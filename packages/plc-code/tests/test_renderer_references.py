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


def test_a_size_prefixed_hex_literal_strips_the_size_and_recurses() -> None:
    """`B#16#FF` -- a size prefix (`_SIZE_PREFIXES`) wrapping a chained hex literal.

    The node is exactly what the expression parser produces for `B#16#FF` (probed
    directly, not guessed): `TypedLiteral(prefix="B", value="16#FF")`. `_render_typed_literal`
    strips the size prefix (Python has no distinct byte-literal syntax) and recurses
    into the rest, which is itself a `TypedLiteral(prefix="16", value="FF")` --
    `_render_typed_literal` again, not `_render_literal`.
    """
    node = TypedLiteral(line=1, column=1, prefix="B", value="16#FF")
    assert render(node) == "0xff"


def test_a_size_prefixed_bare_value_strips_the_size_and_renders_the_literal() -> None:
    """`REAL#1000.0` -- a size prefix wrapping a bare (non-chained) value.

    Probed directly: `TypedLiteral(prefix="REAL", value="1000.0")`. The value has no
    further `#`, so `_render_typed_literal` strips the size prefix and renders what is
    left through `_render_literal` -- `"1000.0"` is already a valid Python float
    literal.
    """
    node = TypedLiteral(line=1, column=1, prefix="REAL", value="1000.0")
    assert render(node) == "1000.0"


def test_a_prefix_with_its_own_value_syntax_raises() -> None:
    """`DATE#...` is not a size prefix -- it carries its own value syntax, unlike
    `B#`/`REAL#`/etc, so there is no Python literal to strip down to.

    Probed directly: `TypedLiteral(prefix="DATE", value="2024-01-01")`.
    """
    node = TypedLiteral(line=1, column=1, prefix="DATE", value="2024-01-01")
    with pytest.raises(UnsupportedExpression):
        render(node)


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


def test_a_quoted_global_alone_is_a_tag_table_lookup() -> None:
    """`"Db"` on its own is a PLC tag or a global DB passed whole; the runtime's tag
    table serves both. It used to render as the Python string literal `"Db"` --
    always true in a condition, silently."""
    assert render(VariableRef(line=1, column=1, name="Db", is_local=False)) == 'self._runtime.tags["Db"]'


def test_eno_is_the_one_bare_global() -> None:
    """The old text translator's only unquoted, non-local identifier."""
    assert render(VariableRef(line=1, column=1, name="ENO", is_local=False)) == "ENO"


def test_an_absolute_address_is_unchanged() -> None:
    assert render(VariableRef(line=1, column=1, name="I0", is_absolute=True, is_local=False)) == "%I0"


def test_a_local_member_is_just_a_member() -> None:
    """`.#name`: the `#` marks the member as a block variable and is not part of the
    name. The old text translator rendered `self.a.self.b` (a `NameError` at run
    time); the first native renderer reproduced it bug for bug."""
    node = Member(
        line=1,
        column=1,
        base=VariableRef(line=1, column=1, name="a", is_local=True),
        name="b",
        is_local=True,
    )
    assert render(node) == "self.a.b"


def test_an_absolute_member_is_refused_with_its_line() -> None:
    """`.%DBX0` reads a bit of the base; the harness has no slice semantics, so the
    renderer refuses (a located TRANSPILE diagnostic) rather than emit `self.a.%DBX0`."""
    node = Member(
        line=7,
        column=1,
        base=VariableRef(line=7, column=1, name="a", is_local=True),
        name="DBX0",
        is_absolute=True,
    )
    with pytest.raises(UnsupportedExpression, match="slice") as excinfo:
        render(node)
    assert excinfo.value.line == 7


def test_a_quoted_member_is_a_path() -> None:
    """`"Db"."armStatus.isActive"`: TIA exports a nested struct member as one quoted
    path; it renders as the attribute chain it names."""
    node = Member(
        line=1,
        column=1,
        base=VariableRef(line=1, column=1, name="Db", is_local=False),
        name="armStatus.isActive[0]",
        is_quoted=True,
    )
    assert render(node) == 'self._runtime.global_dbs["Db"].armStatus.isActive[0]'


def test_a_name_that_is_not_an_identifier_is_made_one() -> None:
    """`#"1X02-01"` (a terminal strip's naming): the attribute is `_1X02_01`."""
    assert render(VariableRef(line=1, column=1, name="1X02-01", is_local=True)) == "self._1X02_01"


def test_an_indexed_global_goes_through_the_tag_table() -> None:
    """`"Arr"[#i]`: the bare quoted base resolves through the tag table, which hands
    back a global DB by that name when one is loaded."""
    node = Index(
        line=1,
        column=1,
        base=VariableRef(line=1, column=1, name="Db", is_local=False),
        indices=[VariableRef(line=1, column=1, name="i", is_local=True)],
    )
    assert render(node) == 'self._runtime.tags["Db"][self.i]'
