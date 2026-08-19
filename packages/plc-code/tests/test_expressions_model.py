"""Expression AST nodes.

Frozen like those in `statements.py`: a tree a consumer can mutate is no longer
a reading of the source.
"""

import dataclasses

import pytest

from plc_code.parser.expressions import (
    BinaryOp,
    FunctionCall,
    Index,
    Literal,
    Member,
    TypedLiteral,
    UnaryOp,
    VariableRef,
)


class TestNodesAreFrozen:
    def test_a_literal_cannot_be_mutated(self) -> None:
        """The type is the contract; the message is a CPython detail.

        Asserting on the message text would tie this test to a wording that
        changes between Python versions — 3.12 says "cannot assign to field
        'value'" and says nothing about being frozen.
        """
        node = Literal(line=1, column=1, value="42")
        with pytest.raises(dataclasses.FrozenInstanceError):
            node.value = "43"  # type: ignore[misc]


class TestNodesCarryPosition:
    def test_every_node_has_a_line_and_column(self) -> None:
        nodes = [
            Literal(line=3, column=7, value="1"),
            TypedLiteral(line=3, column=7, prefix="T", value="5s"),
            VariableRef(line=3, column=7, name="a", is_local=True),
            Member(line=3, column=7, base=VariableRef(line=3, column=7, name="a", is_local=True), name="b"),
            Index(
                line=3,
                column=7,
                base=VariableRef(line=3, column=7, name="a", is_local=True),
                index=Literal(line=3, column=9, value="0"),
            ),
            UnaryOp(line=3, column=7, operator="NOT", operand=Literal(line=3, column=11, value="TRUE")),
            BinaryOp(
                line=3,
                column=7,
                operator="+",
                left=Literal(line=3, column=7, value="1"),
                right=Literal(line=3, column=11, value="2"),
            ),
            FunctionCall(line=3, column=7, name="ABS", arguments=[Literal(line=3, column=11, value="1")]),
        ]
        for node in nodes:
            assert node.line == 3
            assert node.column == 7
