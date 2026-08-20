"""Expression AST for SCL.

Sized on measurement, not on the language reference: across 16,201 expression
slices in five production projects, access (`#`, `.`, `[]`) dominates, followed
by arithmetic, then boolean. `XOR` does not occur once and has no node here —
the parser reports it as an error, which is the honest answer for a construct
the toolchain cannot translate.

Nodes are frozen: a tree a consumer can mutate is no longer a reading of the
source.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Literal:
    """A literal: number, string, `TRUE`/`FALSE`.

    Attributes
    ----------
    line, column : int
        Position of the first token in the source.
    value : str
        The text of the literal, as written.
    """

    line: int
    column: int
    value: str


@dataclass(frozen=True)
class TypedLiteral:
    """A literal prefixed by its type: `T#5s`, `16#FF`, `DINT#5`.

    The lexer does not recognize these; it produces the same token sequence as
    a variable access preceded by a number or identifier. Without this node,
    `16#FF` reads as "16 followed by the variable `#FF`", silently.

    Attributes
    ----------
    line, column : int
        Position of the prefix in the source.
    prefix : str
        What precedes the `#`: `"T"`, `"16"`, `"DINT"`.
    value : str
        What follows the `#`, concatenated as-is: `"5s"`, `"FF"`.
    """

    line: int
    column: int
    prefix: str
    value: str


@dataclass(frozen=True)
class VariableRef:
    """A variable: `#local` or `"DbName"`.

    Attributes
    ----------
    line, column : int
        Position in the source.
    name : str
        The name, without the `#` or quotes.
    is_local : bool
        True for `#name` (block variable), False for `"name"` (data block or
        global block). The distinction determines whether code generation
        chooses an instance attribute or a global lookup.
    """

    line: int
    column: int
    name: str
    is_local: bool


@dataclass(frozen=True)
class Member:
    """A member access: `base.name`.

    Attributes
    ----------
    line, column : int
        Position of the `.` in the source.
    base : Expression
        The expression being accessed.
    name : str
        The name of the member.
    """

    line: int
    column: int
    base: Expression
    name: str


@dataclass(frozen=True)
class Index:
    """An indexing operation: `base[index]`.

    Attributes
    ----------
    line, column : int
        Position of the `[` in the source.
    base : Expression
        The expression being indexed.
    index : Expression
        The index, itself an expression.
    """

    line: int
    column: int
    base: Expression
    index: Expression


@dataclass(frozen=True)
class UnaryOp:
    """A unary operator: `NOT x`, `-x`.

    Attributes
    ----------
    line, column : int
        Position of the operator.
    operator : str
        `"NOT"` (uppercase) or `"-"`.
    operand : Expression
        The operand.
    """

    line: int
    column: int
    operator: str
    operand: Expression


@dataclass(frozen=True)
class BinaryOp:
    """A binary operator.

    Attributes
    ----------
    line, column : int
        Position of the operator.
    operator : str
        The SCL form: `"+"`, `"*"`, `">="`, `"<>"`, `"**"`, `"AND"`, `"OR"`,
        `"MOD"`. Words are uppercase.
    left, right : Expression
        The operands.
    """

    line: int
    column: int
    operator: str
    left: Expression
    right: Expression


@dataclass(frozen=True)
class FunctionCall:
    """A function call in an expression: `ABS(#x)`, `INT_TO_REAL(#n)`.

    Attributes
    ----------
    line, column : int
        Position of the function name.
    name : str
        The name, as written.
    arguments : list[Expression]
        The arguments, in source order.
    """

    line: int
    column: int
    name: str
    arguments: list[Expression] = field(default_factory=list)


Expression = Literal | TypedLiteral | VariableRef | Member | Index | UnaryOp | BinaryOp | FunctionCall
