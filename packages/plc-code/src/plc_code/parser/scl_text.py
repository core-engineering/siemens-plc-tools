"""The SCL spelling of an expression tree.

The inverse of :func:`plc_code.parser.expression_parser.parse_expression`, as far
as spelling goes: the tree carries a :class:`Grouping` node for every pair of
parentheses the source had, so this printer writes what the tree holds and never
re-derives precedence. Spacing is canonical -- one space around a binary operator,
none inside brackets -- so two spellings of one expression print the same.

Used where a human reads an expression back out of an analysis: the dependency
tracers' ``expression`` fields, diagnostics.
"""

from __future__ import annotations

from plc_code.parser.expressions import (
    BinaryOp,
    CallArgument,
    Expression,
    FunctionCall,
    Grouping,
    Index,
    Literal,
    Member,
    TypedLiteral,
    UnaryOp,
    VariableRef,
)


def expression_text(node: Expression) -> str:
    """``node`` spelled as SCL."""
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, TypedLiteral):
        return f"{node.prefix}#{node.value}"
    if isinstance(node, VariableRef):
        if node.is_local:
            # A block variable whose name is not an identifier is written quoted.
            return f"#{node.name}" if node.name.isidentifier() else f'#"{node.name}"'

        if node.is_absolute:
            return f"%{node.name}"
        return f'"{node.name}"'
    if isinstance(node, Member):
        name = f'"{node.name}"' if node.is_quoted else node.name
        if node.is_absolute:
            name = f"%{name}"
        elif node.is_local:
            name = f"#{name}"
        return f"{expression_text(node.base)}.{name}"
    if isinstance(node, Index):
        return f"{expression_text(node.base)}[{', '.join(expression_text(i) for i in node.indices)}]"
    if isinstance(node, UnaryOp):
        operator = node.operator
        # `NOT x` needs the space; so does `- 1`, since `-1` lexes as one literal.
        spacer = " " if operator.isalpha() or isinstance(node.operand, Literal) else ""
        return f"{operator}{spacer}{expression_text(node.operand)}"
    if isinstance(node, BinaryOp):
        return f"{expression_text(node.left)} {node.operator} {expression_text(node.right)}"
    if isinstance(node, Grouping):
        return f"({expression_text(node.inner)})"
    if isinstance(node, FunctionCall):
        name = f'"{node.name}"' if node.is_quoted else node.name
        return f"{name}({', '.join(argument_text(a) for a in node.arguments)})"
    raise TypeError(f"not an expression node: {type(node).__name__}")


def argument_text(argument: CallArgument) -> str:
    """One call argument as written: ``value``, ``name := value`` or ``name => value``."""
    value = expression_text(argument.value)
    if not argument.name:
        return value
    name = f'"{argument.name}"' if argument.is_quoted_name else argument.name
    return f"{name} {'=>' if argument.is_output else ':='} {value}"
