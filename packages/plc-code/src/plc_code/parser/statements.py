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
    both to a comparison, which is how output bindings came to be dropped in
    production code — this field preserves that distinction.

    Attributes
    ----------
    name : str
        Parameter name (e.g., "IN", "Q", "PT").
    value : list[Token]
        Unparsed expression slice for the argument value, as it appears in the
        source. Phase 1 does not parse expressions; this slice carries the raw
        tokens and their original line/column positions.
    is_output : bool, optional
        Whether this binding uses ``=>`` (output, True) or ``:=`` (input, False).
        Default is False.
    """

    name: str
    value: list[Token]
    is_output: bool = False


@dataclass(frozen=True)
class Assignment:
    """An assignment statement: ``target := value;``

    Attributes
    ----------
    line : int
        Source line number where this statement begins.
    target : list[Token]
        Unparsed expression slice for the assignment target (left-hand side),
        as it appears in the source. Phase 1 does not parse expressions; this
        slice carries the raw tokens and their original line/column positions.
    value : list[Token]
        Unparsed expression slice for the right-hand side, as it appears in
        the source. Phase 1 does not parse expressions; this slice carries the
        raw tokens and their original line/column positions.
    """

    line: int
    target: list[Token]
    value: list[Token]


@dataclass(frozen=True)
class Call:
    """A function or block call: ``callee(arg := ..., out => ...);``

    Attributes
    ----------
    line : int
        Source line number where this statement begins.
    callee : list[Token]
        Unparsed name of the called function or block, as it appears in the
        source. Phase 1 does not parse expressions; this slice carries the raw
        tokens and their original line/column positions.
    arguments : list[Argument], optional
        Bindings passed to the callee. Each argument records its parameter name,
        value (as an unparsed token slice), and binding direction (input `:=` or
        output `=>`). Default is an empty list.
    """

    line: int
    callee: list[Token]
    arguments: list[Argument] = field(default_factory=list)


@dataclass(frozen=True)
class Branch:
    """One conditional arm of an IF statement (IF or ELSIF).

    Attributes
    ----------
    condition : list[Token]
        Unparsed boolean expression slice for the branch condition, as it
        appears in the source. Phase 1 does not parse expressions; this slice
        carries the raw tokens and their original line/column positions.
    body : list[Statement]
        Statements that execute when the condition is true.
    """

    condition: list[Token]
    body: list[Statement]


@dataclass(frozen=True)
class If:
    """An IF statement: ``IF ... THEN ... ELSIF ... ELSE ... END_IF;``

    ELSIF is not a separate node type; each ELSIF clause is another entry in
    ``branches``. This eliminates redundant node types and simplifies traversal.

    Attributes
    ----------
    line : int
        Source line number where this statement begins.
    branches : list[Branch]
        All conditional arms, in order. The first branch is the IF condition;
        subsequent branches are ELSIF conditions. Each branch carries its
        condition (as an unparsed token slice) and body statements.
    else_body : list[Statement], optional
        Statements that execute if no branch condition is true. Default is an
        empty list.
    """

    line: int
    branches: list[Branch]
    else_body: list[Statement] = field(default_factory=list)


@dataclass(frozen=True)
class CaseBranch:
    """One labelled arm of a CASE statement.

    Attributes
    ----------
    values : list[list[Token]]
        One unparsed token slice per label value. Each inner list is a single
        case label (e.g., ``1``, ``"a"``, or a range ``1..10``). Multiple
        values are supported when one arm handles multiple cases. Phase 1 does
        not parse expressions; each slice carries the raw tokens and their
        original line/column positions.
    body : list[Statement]
        Statements that execute when the case selector matches one of the
        values.
    """

    values: list[list[Token]]
    body: list[Statement]


@dataclass(frozen=True)
class Case:
    """A CASE statement: ``CASE selector OF ... ELSE ... END_CASE;``

    Attributes
    ----------
    line : int
        Source line number where this statement begins.
    selector : list[Token]
        Unparsed expression slice for the case selector, as it appears in the
        source. Phase 1 does not parse expressions; this slice carries the raw
        tokens and their original line/column positions.
    branches : list[CaseBranch]
        All labelled arms in order. Each branch carries one or more label
        values and the statements to execute if the selector matches.
    default : list[Statement], optional
        Statements that execute if no branch label matches (the ELSE arm).
        Default is an empty list.
    """

    line: int
    selector: list[Token]
    branches: list[CaseBranch]
    default: list[Statement] = field(default_factory=list)


@dataclass(frozen=True)
class For:
    """A FOR loop: ``FOR variable := start TO end BY step DO ... END_FOR;``

    The BY clause (step increment) is optional in SCL. When absent, the step
    field is empty, allowing the parser to preserve the distinction between
    implicit (default 1) and explicit step values.

    Attributes
    ----------
    line : int
        Source line number where this statement begins.
    variable : list[Token]
        Unparsed loop variable name, as it appears in the source. Phase 1 does
        not parse expressions; this slice carries the raw tokens and their
        original line/column positions.
    start : list[Token]
        Unparsed initial value expression slice, as it appears in the source.
        Phase 1 does not parse expressions; this slice carries the raw tokens
        and their original line/column positions.
    end : list[Token]
        Unparsed upper bound expression slice, as it appears in the source.
        Phase 1 does not parse expressions; this slice carries the raw tokens
        and their original line/column positions.
    step : list[Token], optional
        Unparsed step/increment expression slice, if the BY clause is present.
        Empty when the loop has no BY clause. Phase 1 does not parse
        expressions; when non-empty, this slice carries the raw tokens and
        their original line/column positions. Default is an empty list.
    body : list[Statement], optional
        Statements executed in each loop iteration. Default is an empty list.
    """

    line: int
    variable: list[Token]
    start: list[Token]
    end: list[Token]
    step: list[Token] = field(default_factory=list)
    body: list[Statement] = field(default_factory=list)


@dataclass(frozen=True)
class While:
    """A WHILE loop: ``WHILE condition DO ... END_WHILE;``

    Attributes
    ----------
    line : int
        Source line number where this statement begins.
    condition : list[Token]
        Unparsed boolean expression slice for the loop condition, as it
        appears in the source. Phase 1 does not parse expressions; this slice
        carries the raw tokens and their original line/column positions.
    body : list[Statement], optional
        Statements executed in each loop iteration. Default is an empty list.
    """

    line: int
    condition: list[Token]
    body: list[Statement] = field(default_factory=list)


@dataclass(frozen=True)
class Return:
    """A RETURN statement: ``RETURN;``

    Attributes
    ----------
    line : int
        Source line number where this statement begins.
    """

    line: int


@dataclass(frozen=True)
class Exit:
    """An EXIT statement: ``EXIT;`` — the SCL loop break.

    Attributes
    ----------
    line : int
        Source line number where this statement begins.
    """

    line: int


Statement = Assignment | Call | If | Case | For | While | Return | Exit
