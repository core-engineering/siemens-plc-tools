"""Expression AST for SCL.

Sized on measurement, not on the language reference: across 16,069 expression
slices in five production projects (as counted by the conformance walker;
see ``parser/conformance.py``), access (`#`, `.`, `[]`) dominates, followed
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
        The name of the member, without any leading `#`.
    is_local : bool
        True when the member was written `.#name`. The corpus uses that form 234
        times, and it is different source from `.name` — a consumer that cannot
        tell them apart cannot render either one back. Follows
        `VariableRef.is_local`, where `#` already means local.
    is_absolute : bool
        True when the member was written `.%name` — SCL's direct access to a bit,
        byte or word of the base: `.%X0`, `.%B1`, `.%DBX0`. The corpus writes 77
        of them. The `%` is not part of the name, but dropping it would make the
        access indistinguishable from an ordinary member.
    is_quoted : bool
        True when the member was written `."name"`. TIA Portal quotes a name that
        collides with a keyword — the corpus writes `."type"` 80 times — so this
        is the second spelling of the same thing `#function` and `.type` are the
        first of. Follows `FunctionCall.is_quoted`.
    """

    line: int
    column: int
    base: Expression
    name: str
    is_local: bool = False
    is_absolute: bool = False
    is_quoted: bool = False


@dataclass(frozen=True)
class Index:
    """An indexing operation: `base[i]`, `base[i, j]`.

    SCL arrays may have several dimensions, and the corpus indexes two of them
    at once — `#matrixResult[#tempCounterRows, #tempCounterColumns]`. The
    subscripts are therefore a list, one-dimensional access being a list of one,
    so a consumer walks one shape rather than two.

    Attributes
    ----------
    line, column : int
        Position of the `[` in the source.
    base : Expression
        The expression being indexed.
    indices : list[Expression]
        One subscript per dimension, in source order. Never empty: `base[]` is
        not read.
    """

    line: int
    column: int
    base: Expression
    indices: list[Expression]


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
class CallArgument:
    """One argument of a call, with the parameter name when it was written.

    SCL binds arguments by name more often than by position — `#fl :=
    "PolyEval"(p := #p, n := #n, x := #ll)` — and the direction of the binding
    is part of the source: `:=` passes a value in, `=>` names a destination the
    call writes to. Both are kept, because a translator that collapses them to
    the same thing drops the writes.

    Every argument is wrapped, positional ones included, so that a consumer
    walks one list of one type in source order rather than a union.

    Attributes
    ----------
    value : Expression
        The argument's expression. Its own ``line``/``column`` locate the
        argument in the source, so this node carries no position of its own.
    name : str
        The parameter name, without quotes, or an empty string for a positional
        argument.
    is_output : bool
        True when the binding was written `name => value`.
    is_quoted_name : bool
        True when the parameter name was written `"name" := value`. TIA Portal
        quotes it and leaves its neighbour bare in the same call — `"Atan2"("x"
        := #A, y := #B)` — so both spellings are real and the difference is
        source a consumer has to be able to render back.
    """

    value: Expression
    name: str = ""
    is_output: bool = False
    is_quoted_name: bool = False


@dataclass(frozen=True)
class FunctionCall:
    """A function call in an expression: `ABS(#x)`, `INT_TO_REAL(#n)`.

    Attributes
    ----------
    line, column : int
        Position of the function name.
    name : str
        The name, without the surrounding quotes when there were any.
    arguments : list[CallArgument]
        The arguments, in source order, each wrapped so that a named binding
        keeps its parameter name and direction.
    is_quoted : bool
        True when the callee was written `"Name"(...)` rather than bare. The
        corpus calls user blocks that way 235 times, and a generator has to tell
        such a call from a builtin like `ABS`. Named for what was written rather
        than for what it means, because the semantics are not established here.
    """

    line: int
    column: int
    name: str
    arguments: list[CallArgument] = field(default_factory=list)
    is_quoted: bool = False


Expression = Literal | TypedLiteral | VariableRef | Member | Index | UnaryOp | BinaryOp | FunctionCall
