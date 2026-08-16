"""Statement AST for SCL.

Sized on measurement, not on the language reference: across 11 950 body lines
in five production PLC projects, assignments are 59% of statements, followed by
IF/ELSIF/ELSE, calls, FOR, RETURN, CASE, EXIT and WHILE. REPEAT/UNTIL, GOTO and
CONTINUE do not occur at all and have no node here — the parser reports them as
errors, which is the honest answer for a construct the toolchain cannot
translate.

Expressions are not parsed in this phase. Every field that holds one holds the
``list[Token]`` slice it occupies, so the shape of a statement is resolved
without committing to an expression grammar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from plc_code.parser.lexer import Token


@dataclass(frozen=True)
class ParseError:
    """A construct the parser could not read, with where and what was expected.

    Attributes
    ----------
    line, column : int
        Position of the offending token in the original source.
    token_value : str
        The token the parser stopped on.
    expected : str
        What would have been valid there, in plain words.
    """

    line: int
    column: int
    token_value: str
    expected: str

    @property
    def message(self) -> str:
        """One-line description, naming the token and the expectation."""
        return (
            f"line {self.line}, column {self.column}: unexpected "
            f"{self.token_value!r}, expected {self.expected}"
        )


@dataclass(frozen=True)
class Argument:
    """One binding in a call.

    ``is_output`` separates ``=>`` from ``:=``. The text translator collapses
    both to a comparison, which is how output bindings came to be dropped.
    """

    name: str
    value: list[Token]
    is_output: bool = False


@dataclass(frozen=True)
class Assignment:
    """``target := value;``"""

    line: int
    target: list[Token]
    value: list[Token]


@dataclass(frozen=True)
class Call:
    """``callee(arg := ..., out => ...);``"""

    line: int
    callee: list[Token]
    arguments: list[Argument] = field(default_factory=list)


@dataclass(frozen=True)
class Branch:
    """One ``IF``/``ELSIF`` arm."""

    condition: list[Token]
    body: list[Statement]


@dataclass(frozen=True)
class If:
    """``IF ... THEN ... ELSIF ... ELSE ... END_IF;``

    ``ELSIF`` needs no node of its own: it is another entry in ``branches``.
    """

    line: int
    branches: list[Branch]
    else_body: list[Statement] = field(default_factory=list)


@dataclass(frozen=True)
class CaseBranch:
    """One labelled arm. ``values`` holds one token slice per label value."""

    values: list[list[Token]]
    body: list[Statement]


@dataclass(frozen=True)
class Case:
    """``CASE selector OF ... ELSE ... END_CASE;``"""

    line: int
    selector: list[Token]
    branches: list[CaseBranch]
    default: list[Statement] = field(default_factory=list)


@dataclass(frozen=True)
class For:
    """``FOR variable := start TO end BY step DO ... END_FOR;``

    ``step`` is empty when the loop has no ``BY`` clause.
    """

    line: int
    variable: list[Token]
    start: list[Token]
    end: list[Token]
    step: list[Token] = field(default_factory=list)
    body: list[Statement] = field(default_factory=list)


@dataclass(frozen=True)
class While:
    """``WHILE condition DO ... END_WHILE;``"""

    line: int
    condition: list[Token]
    body: list[Statement] = field(default_factory=list)


@dataclass(frozen=True)
class Return:
    """``RETURN;``"""

    line: int


@dataclass(frozen=True)
class Exit:
    """``EXIT;`` — the SCL loop break."""

    line: int


Statement = Assignment | Call | If | Case | For | While | Return | Exit
