"""Python generation from the statement AST.

Generation is native from the AST for every statement kind: `Assignment` renders by
calling `plc_code.executor.renderer.render` directly on `target_expr`/`value_expr`
(`_generate_assignment`); `If`/`For`/`While`/`Case` headers render a condition, a
bound, or a selector the same way (`_render_header_expression`), with a `Case` label
mapping a matching symbolic constant to its bare integer instead of the ordinary
`self.NAME` substitution (`_render_case_label` -- see its own docstring for why that
must NOT be the same substitution `render`'s `_render_variable_ref` applies everywhere
else); `Call`, `Return` and `Exit` render by reading `Call.callee_expr`'s own shape
(`_generate_call`) rather than re-parsing rebuilt SCL text. A `For` loop's own variable
name has no `*_expr` field on the statement AST (there is no tree for it in the parsed
statement itself), so `generate_statements` parses `statement.variable`'s token slice
directly with `plc_code.parser.expression_parser.parse_expression` before rendering it
(`_render_for_variable`) -- the one place in this module that still reads from the
parser rather than purely from the tree the statement parser already built.

A construct this module cannot generate raises rather than emitting nothing or
something merely plausible: `UnsupportedStatement` for a statement kind with no branch
here, or a slice that failed to parse into an expression tree in the first place;
`plc_code.executor.renderer.UnsupportedExpression` (uncaught, propagating straight out)
for a tree node `render` has no visitor for, or refuses to render on purpose (a bare
system builtin call binding an `=>` output -- see `renderer._render_builtin_call`'s own
docstring). `SCLTranspiler.transpile`'s own top-level exception handler turns either
into `TranspileResult(success=False, ...)`.

This is the end state of a longer migration (Task 9 deletes what came before): every
statement and expression kind used to be rewritten as SCL-flavoured text and handed to
`ExpressionTranslator`/`StatementTranslator`'s twelve ordered regex passes and their own
text-dispatch logic, each fix adding another pass to patch the previous one's silent
corruption. Two corpus-wide differentials (23,305 expression slices; 594 statement units
across 647 blocks) proved the tree-driven renderer and this generator produce the same
Python the old text machinery did, with five documented, deliberate exceptions where the
old path was itself buggy -- see `CHANGELOG.md`. Only then was the text machinery, its
own tests, and the fallback path this module used to take when it was not yet fully
proven, deleted.

`Call`'s own callee shape is read directly off `statement.callee_expr`
(`_generate_call`): an FB instance call (`#instance(...)`, a local `VariableRef`), an
indexed or member-accessed FB instance call (`#arms[#i](...)`, `"db".TON(...)`, widened
onto the same branch since neither shape has a quoted-block-call read either), and a
quoted-block call statement (`"Block"(...)`, a non-local non-absolute `VariableRef`)
each render natively; anything else (an unparsed callee, or an absolute address) raises.
The FB-instance branch (`_generate_fb_instance_call`) reimplements the old
`translate_fb_call`'s own rules directly from the tree: a positional (unnamed) argument
is dropped in either direction, a `:=` argument becomes `name=value`, an `=>` argument
becomes a trailing `target = {callee}.name` line, and a callee whose own timer-marker
name contains `"timer"`/`"ton"`/`"tof"`/`"tp"` gets a trailing
`clock=self._runtime.clock` keyword argument. The quoted-block-call branch
(`_generate_named_call_statement`) and the named-call-with-outputs assignment shape
(`_generate_named_call_assignment`, for `#ret := "Block"(x := #a, out => #b)`, which
`render` alone cannot express since it can only return one value) both call
`StatementTranslator._emit_named_call` directly -- a pure formatter now (Task 9 step 2):
every argument's value is rendered through `render` first, and its in-out write-back
flag decided from the tree (`_is_write_back_candidate`), before either reaches
`_emit_named_call`, so there is no placeholder-and-substitute step and no text carving
left anywhere in this module.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from plc_code.executor.arguments import (
    PositionalBindingError,
    SignatureResolver,
    positional_parameter_names,
)
from plc_code.executor.codegen import StatementTranslator
from plc_code.executor.renderer import render
from plc_code.executor.timers import timer_class_name
from plc_code.parser.expression_parser import parse_expression
from plc_code.parser.expressions import Expression, FunctionCall, Index, Member, VariableRef
from plc_code.parser.lexer import Token
from plc_code.parser.statements import Assignment, Call, Case, Exit, For, If, Return, Statement, While

INDENT = "    "


class UnsupportedStatement(Exception):
    """A statement kind the generator has no branch for, or a slice it needed that failed to parse.

    Raised rather than skipped: a generator that silently emits nothing (or something
    merely plausible) for a construct it does not know, or for an expression-bearing
    slice that never became a tree in the first place, is the failure this module exists
    to remove. See also `plc_code.executor.renderer.UnsupportedExpression`, which this
    module lets propagate uncaught for a tree node `render` recognises but refuses (or
    has no visitor for) -- the sibling failure mode for a slice that *did* parse.

    Attributes
    ----------
    line : int | None
        The source line of the statement or slice this was raised for, when known.
        Consulted by `SCLTranspiler.transpile`'s top-level exception handler so a
        raised `UnsupportedStatement` still produces a located
        `TranspileProblem.source_line`, not `None`.
    """

    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line


class _NamedArgument(Protocol):
    """The one field :func:`_positional_names` reads from either argument shape."""

    @property
    def name(self) -> str | None: ...


@dataclass(frozen=True)
class _Context:
    """What every generator site forwards unchanged: the render-time lookups and the
    caller's own timer instances."""

    string_constants: dict[str, int] | None
    signature_resolver: SignatureResolver | None
    timer_instances: frozenset[str] = frozenset()


def _generate_body(
    statements: list[Statement],
    indent: int,
    translator: StatementTranslator,
    ctx: _Context,
) -> list[str]:
    """Generate a nested body's lines via :func:`generate_statements`, padding when empty.

    The caller always emits a header line (``if``/``elif``/``else``/``for``/
    ``while``/a ``CASE`` arm) unconditionally, and Python requires at least
    one statement to follow it. A body that parses to zero statements — a
    comment-only branch is the common real-world case, since comment tokens
    never reach the statement parser — would otherwise leave that header
    dangling with nothing indented under it, which is not valid Python.

    Parameters
    ----------
    statements : list[Statement]
        The nested body to generate.
    indent : int
        Depth in four-space units for the body's own lines (one deeper than
        the header this body follows).
    translator : StatementTranslator
        Shared translator instance, forwarded unchanged.
    ctx : _Context
        Forwarded unchanged; see :func:`generate_statements`.

    Returns
    -------
    list[str]
        Python lines for the body. Never empty: ``["pass"]`` (at ``indent``)
        stands in for a body that generated no lines of its own.
    """
    lines = _generate_statements(statements, indent, translator, ctx)
    if not lines:
        lines.append(INDENT * indent + "pass")
    return lines


def _is_named_call_with_output_binding(expression: Expression | None) -> bool:
    """Whether ``expression`` is a quoted-block call that binds at least one ``=>`` output.

    ``render``'s ``_render_named_call`` silently drops an ``is_output=True`` argument
    when building the call's parameter dict -- the expression path can only return
    *one* value, so it has nowhere to route a second, out-of-band write-back. So
    :func:`render` alone cannot express an ``Assignment`` whose right-hand side has this
    exact shape -- it renders natively by a different route instead
    (:func:`_generate_named_call_assignment`, called by :func:`_generate_assignment`),
    which calls ``StatementTranslator._emit_named_call`` directly, with each argument's
    value taken from :func:`render`.

    Probed directly (``uv run python3``, not assumed): parsing
    ``#ret := "RetWithOut"(x := #value, dbl => #doubled, trp => #tripled);`` produces
    an ``Assignment`` whose ``value_expr`` is exactly this shape -- a ``FunctionCall``
    with ``is_quoted=True`` and two ``CallArgument``s carrying ``is_output=True``.

    Parameters
    ----------
    expression : Expression | None
        An ``Assignment.value_expr`` (or ``None`` when the slice failed to parse).

    Returns
    -------
    bool
        True when ``expression`` is a ``FunctionCall`` with ``is_quoted=True`` and at
        least one argument with ``is_output=True``.
    """
    return (
        isinstance(expression, FunctionCall)
        and expression.is_quoted
        and any(argument.is_output for argument in expression.arguments)
    )


#: Mirrors ``renderer._IMPLICIT_BARE_NAME`` -- the one quoted name :func:`render` leaves
#: completely bare (neither ``self.``-prefixed nor quoted). Duplicated here (not
#: imported) because it is a single literal and :func:`_is_write_back_candidate` needs
#: to reject it the same way ``renderer._render_variable_ref`` / ``_is_global_db_ref``
#: do, for the same reason.
_IMPLICIT_BARE_NAME = "ENO"


def _is_write_back_candidate(value_expr: Expression, string_constants: dict[str, int] | None) -> bool:
    """Whether ``_emit_named_call`` should treat a ``:=`` argument with this value as an in-out write-back.

    ``_emit_named_call`` is a pure formatter (Task 9 step 2): it takes this verdict as
    data (its ``write_back`` flag) rather than inspecting the value's own rendered text,
    because the rendered text cannot always answer the question correctly on its own --
    see case 3 below. This function computes the verdict from the tree instead.

    The invariant it mirrors is the OLD text path's spelling, not :func:`render`'s.
    :func:`~plc_code.executor.renderer.render` renders almost everything space-free and
    ``self.``-prefixed -- an index (``#arr[#i]`` -> ``self.arr[self.i]``), a plain local
    member (``#a.b`` -> ``self.a.b``), a two-level global-DB chain (``"DB".a.b`` ->
    ``self._runtime.global_dbs["DB"].a.b``) all qualify by that description too, yet none
    of the three is a write-back candidate: probed directly, `render`'s own output being
    space-free is not what distinguishes them. What actually distinguished a write-back
    candidate was the OLD path's own reconstruction: `scl_text` joined every token with a
    space (``"# a . b"``), and only these three tree shapes happened to have their spaces
    fully consumed by one of the old translator's own regex substitutions --
    ``INSTANCE_VAR_PATTERN`` collapsing ``"# name"`` to ``"self.name"`` whole (case 1),
    the string-constant substitution's own whole-literal replacement (case 2), and
    ``GLOBAL_DB_PATTERN``'s single-shot match of ``'"Name" . member'`` (case 3) -- every
    other shape, including the three above, kept at least one space somewhere in the old
    reconstruction even though the *new* renderer never introduces one anywhere. There are
    exactly three such tree shapes, probed directly and confirmed, not merely reasoned
    about:

    1. A bare local variable, ``#name`` -- renders as ``self.name``.
    2. A bare *global* variable, ``"Name"``, whose quoted spelling is a
       ``string_constants`` key -- renders as ``self.Name`` (see
       :func:`~plc_code.executor.renderer._render_variable_ref`'s own
       ``string_constants`` handling).
    3. A *single* level of member access directly on a *plain* global DB reference,
       ``"Name".member`` -- renders as ``self._runtime.global_dbs["Name"].member``, via
       :func:`~plc_code.executor.renderer._is_global_db_ref`, which requires ``Name`` to
       consist only of word characters (letters, digits, underscore): a hyphen, a space
       or anything else in the quoted name means ``Name.member`` renders as a plain
       quoted-and-dotted reference instead, which is NOT a write-back candidate (fix
       round 1: a global DB name containing such a character was wrongly treated as one
       by an earlier version of this function, emitting a spurious second statement no
       argument-value-only comparison could see -- pinned by
       ``test_generator_native.py``'s three ``..._is_not_a_write_back_candidate`` tests).
       A *second* level of member access (``"Name".a.b``) is also NOT covered: only the
       first ``.member`` renders through the global-DB substitution; a chain past that
       point renders through the base's own render, which is a ``Member`` again, not a
       bare global reference.

    Every other shape -- an index, an operator, a nested call, a literal, a member chain
    two or more levels deep, a member access on a global whose *own* quoted name contains
    a non-word character (case 3's exclusion above), a *quoted* global not in
    ``string_constants`` (renders quoted, e.g. ``'"Foo"'``, never ``self.``-prefixed) --
    is never a candidate.

    Parameters
    ----------
    value_expr : Expression
        The argument's parsed value (never ``None`` -- the caller has already checked).
    string_constants : dict[str, int] | None
        The same mapping :func:`render` uses.

    Returns
    -------
    bool
        True when ``value_expr`` matches one of the three shapes above.
    """
    if isinstance(value_expr, VariableRef):
        if value_expr.is_local:
            return True
        if value_expr.is_absolute or value_expr.name.upper() == _IMPLICIT_BARE_NAME:
            return False
        return string_constants is not None and f'"{value_expr.name}"' in string_constants
    if isinstance(value_expr, Member):
        base = value_expr.base
        return (
            isinstance(base, VariableRef)
            and not base.is_local
            and not base.is_absolute
            and base.name.upper() != _IMPLICIT_BARE_NAME
            and not (string_constants and f'"{base.name}"' in string_constants)
            and base.name != ""
            and all(character.isalnum() or character == "_" for character in base.name)
        )
    return False


def _positional_names(
    block_name: str, arguments: Sequence[_NamedArgument], ctx: _Context, line: int
) -> Iterator[str]:
    """Names for the unnamed arguments of a named-block call, in order, or raise.

    Delegates to :func:`plc_code.executor.arguments.positional_parameter_names` and
    turns its :class:`PositionalBindingError` into an :class:`UnsupportedStatement`
    located at ``line``. Accepts both argument shapes (expression-AST ``Argument`` and
    statement-AST ``CallArgument``): only ``.name`` is read.
    """
    positional_count = sum(1 for argument in arguments if not argument.name)
    try:
        names = positional_parameter_names(
            block_name,
            positional_count=positional_count,
            already_named={argument.name for argument in arguments if argument.name},
            resolver=ctx.signature_resolver,
        )
    except PositionalBindingError as error:
        raise UnsupportedStatement(f"Call at line {line}: {error}", line=line) from error
    return iter(names)


def _generate_named_call_assignment(
    statement: Assignment,
    translator: StatementTranslator,
    ctx: _Context,
) -> list[str]:
    """Native lines for ``#ret := "Block"(x := #a, out => #b)``, the shape :func:`render` cannot express.

    Calls ``StatementTranslator._emit_named_call`` directly, with every argument value
    and the assignment target taken from :func:`render`, and the in-out write-back flag
    for each ``:=`` argument computed from the tree via :func:`_is_write_back_candidate`
    (``_emit_named_call`` is a pure formatter -- it takes that decision as data, it does
    not re-derive it from a value's own rendered text). Appends the return-value line
    last: ``f'{target} = {result_var}["{block_name}"]'`` -- keyed by the callee's own
    name, not the argument named ``"out"`` (probed and confirmed against
    ``test_generator_statements.py::test_an_assignment_from_a_named_call_with_outputs``).

    Parameters
    ----------
    statement : Assignment
        The assignment to generate; ``statement.value_expr`` must already be known to
        satisfy :func:`_is_named_call_with_output_binding` (the caller's job).
    translator : StatementTranslator
        Shared translator instance; only ``_emit_named_call`` is used.
    ctx : _Context
        Forwarded to every :func:`render` call.

    Returns
    -------
    list[str]
        The rendered lines (unindented -- the caller prefixes them).

    Raises
    ------
    UnsupportedStatement
        ``statement.target_expr`` is ``None`` (the slice failed to parse).
    plc_code.executor.renderer.UnsupportedExpression
        :func:`render` raised for the target or a named argument.
    """
    node = statement.value_expr
    assert isinstance(node, FunctionCall)
    if statement.target_expr is None:
        raise UnsupportedStatement(
            f"Assignment at line {statement.line} has no parsed target expression", line=statement.line
        )
    names_for_positional = _positional_names(node.name, node.arguments, ctx, statement.line)
    bound_arguments: list[tuple[str, str, bool, bool]] = []
    for argument in node.arguments:
        value_text = render(argument.value, ctx.string_constants, ctx.signature_resolver)
        if not argument.name:
            name_text = next(names_for_positional)
        else:
            name_text = f'"{argument.name}"' if argument.is_quoted_name else argument.name
        write_back = not argument.is_output and _is_write_back_candidate(argument.value, ctx.string_constants)
        bound_arguments.append((name_text, value_text, argument.is_output, write_back))
    target_text = render(statement.target_expr, ctx.string_constants, ctx.signature_resolver)
    lines, result_var = translator._emit_named_call(node.name, bound_arguments)  # noqa: SLF001
    lines = list(lines)
    lines.append(f'{target_text} = {result_var}["{node.name}"]')
    return lines


def _generate_assignment(
    statement: Assignment,
    prefix: str,
    translator: StatementTranslator,
    ctx: _Context,
) -> list[str]:
    """One ``Assignment``'s Python line(s), rendered natively from the tree.

    ``f"{render(target)} = {render(value)}"`` for the ordinary case; when the value is a
    named-call-with-outputs (see :func:`_is_named_call_with_output_binding`),
    :func:`_generate_named_call_assignment` is used instead, since :func:`render` alone
    cannot express a call statement's ``=>`` write-backs.

    A compound assignment (``#a += 1``) needs no special case here: the statement parser
    desugars it into an ordinary ``:=`` ``Assignment`` before it ever reaches the
    generator, with ``value_expr`` already the fully parsed ``BinaryOp`` for ``#a + 1``.

    Parameters
    ----------
    statement : Assignment
        The assignment to generate.
    prefix : str
        Indentation to prepend to the emitted line.
    translator : StatementTranslator
        Shared translator instance, forwarded to :func:`_generate_named_call_assignment`.
    ctx : _Context
        Forwarded to :func:`render`; see :func:`generate_statements`.

    Returns
    -------
    list[str]
        One line (the ordinary case) or :func:`_generate_named_call_assignment`'s lines,
        each already prefixed with ``prefix``.

    Raises
    ------
    UnsupportedStatement
        ``statement.target_expr`` or ``statement.value_expr`` is ``None`` (the slice
        failed to parse).
    plc_code.executor.renderer.UnsupportedExpression
        :func:`render` raised for the target or the value -- for a bare (non-quoted)
        system builtin call binding an ``=>`` output (e.g. ``#x := RD_SYS_T(OUT => #x)``,
        the one shape this ever fired on in the corpus: 6 ``GET_DIAG``, 2 ``RD_SYS_T``, 2
        ``DPRD_DAT``, 1 ``RH_CTRL``, 1 ``Serialize``, probed directly), there genuinely is
        no correct Python to produce instead --
        :func:`~plc_code.executor.renderer._render_builtin_call` raises deliberately (a
        positional call has nowhere to route an output binding). Left uncaught here:
        :class:`~plc_code.executor.transpiler.SCLTranspiler.transpile`'s own top-level
        exception handler turns it into ``TranspileResult(success=False, ...)``.
    """
    if statement.target_expr is None or statement.value_expr is None:
        raise UnsupportedStatement(
            f"Assignment at line {statement.line} has no parsed expression tree", line=statement.line
        )
    if _is_named_call_with_output_binding(statement.value_expr):
        named_call_lines = _generate_named_call_assignment(statement, translator, ctx)
        return [prefix + line for line in named_call_lines]
    target_text = render(statement.target_expr, ctx.string_constants, ctx.signature_resolver)
    value_text = render(statement.value_expr, ctx.string_constants, ctx.signature_resolver)
    return [f"{prefix}{target_text} = {value_text}"]


def _render_header_expression(expr: Expression | None, ctx: _Context, description: str, line: int) -> str:
    """One control-flow header expression: an `If`/`While` condition, a `For` bound, or a `Case` selector.

    Parameters
    ----------
    expr : Expression | None
        The slice's parsed tree, or `None` when it failed to parse.
    ctx : _Context
        Forwarded to :func:`render`; see :func:`generate_statements`.
    description : str
        What this slice is, for the `UnsupportedStatement` message -- e.g. `"If
        condition"`, `"For loop end bound"`.
    line : int
        The enclosing statement's own source line -- `expr is None` carries no line of
        its own (there is no tree), so this is what `UnsupportedStatement.line` reports
        for that case.

    Returns
    -------
    str
        The rendered Python expression text.

    Raises
    ------
    UnsupportedStatement
        `expr` is `None` (the slice failed to parse).
    plc_code.executor.renderer.UnsupportedExpression
        `render` raised.
    """
    if expr is None:
        raise UnsupportedStatement(f"{description} has no parsed expression tree", line=line)
    return render(expr, ctx.string_constants, ctx.signature_resolver)


def _render_for_variable(tokens: list[Token], ctx: _Context) -> str:
    """A `For` loop's own variable name, parsed from its raw token slice and rendered.

    Unlike every other header slice, a `For` loop's `variable` field carries no
    `*_expr` companion on the statement AST -- the statement parser never gave it one,
    so there is no tree already sitting on the statement to render from. This parses
    `tokens` directly with `plc_code.parser.expression_parser.parse_expression` (the
    same entry point the statement parser itself uses for every other slice) and
    renders the result -- the one place in this module that still reads from the
    parser rather than purely from a tree the statement parser already built.

    Parameters
    ----------
    tokens : list[Token]
        `For.variable` -- always a bare `#name` reference in valid SCL.
    ctx : _Context
        Forwarded to :func:`render`; see :func:`generate_statements`.

    Returns
    -------
    str
        The rendered Python text, ordinarily `self.{name}`.

    Raises
    ------
    UnsupportedStatement
        `tokens` did not parse into a complete expression.
    plc_code.executor.renderer.UnsupportedExpression
        `render` raised.
    """
    result = parse_expression(tokens)
    if result.expression is None:
        line = tokens[0].line if tokens else 0
        raise UnsupportedStatement(
            f"For loop variable at line {line} has no parsed expression tree", line=line
        )
    return render(result.expression, ctx.string_constants, ctx.signature_resolver)


def _render_case_label(expr: Expression | None, ctx: _Context, line: int) -> str:
    """One `Case` label: a mapped symbolic constant renders as its bare integer, everything else natively.

    A label is a different mapping from an ordinary expression position. A label whose
    tree is a non-local, non-absolute `VariableRef` (`"MODE_ONE"`, never `#name` or
    `%name`) with quoted spelling (`f'"{name}"'`) present in `ctx` emits
    that mapping's bare integer, the same value a matching `Assignment` right-hand side
    would resolve to at runtime. This is deliberately NOT the same substitution
    `render`'s own `_render_variable_ref` performs for that identical tree shape
    everywhere else (`self.NAME`): applying that substitution here would turn
    `if self.s == 1:` into `if self.s == self.MODE_ONE:`. Note that `self.MODE_ONE` is
    NOT an unassigned attribute that would fail at run time -- `transpiler.py` emits
    `MODE_ONE: int = 1` as a class attribute for every mapped string constant, so
    `self.s == self.MODE_ONE` would evaluate identically to `self.s == 1` and no
    executable test could tell the two apart. The reason for this ruling is textual
    byte-identity with the old path's own bare-integer output for a CASE label, not
    anything an executable test would catch.

    Parameters
    ----------
    expr : Expression | None
        The label's parsed tree (`CaseBranch.values_expr[i]`), or `None`.
    ctx : _Context
        Forwarded to :func:`render` and consulted directly for the symbolic-label
        ruling.
    line : int
        The enclosing `Case` statement's own source line -- `expr is None` carries no
        line of its own (there is no tree), so this is what `UnsupportedStatement.line`
        reports for that case.

    Returns
    -------
    str
        The rendered Python text for this one label.

    Raises
    ------
    UnsupportedStatement
        `expr` is `None` (the slice failed to parse).
    plc_code.executor.renderer.UnsupportedExpression
        `render` raised.
    """
    if expr is None:
        raise UnsupportedStatement("Case label has no parsed expression tree", line=line)
    if isinstance(expr, VariableRef) and not expr.is_local and not expr.is_absolute:
        quoted = f'"{expr.name}"'
        if ctx.string_constants and quoted in ctx.string_constants:
            return str(ctx.string_constants[quoted])
    return render(expr, ctx.string_constants, ctx.signature_resolver)


def _callee_is_timer(callee_expr: VariableRef | Index | Member, ctx: _Context) -> bool:
    """Whether an FB instance call needs the ``clock=self._runtime.clock`` argument.

    A timer's ``__call__`` (``TON_TIME``/``TOF_TIME``/``TP_TIME``) takes the harness
    clock explicitly; a generated FB's ``__call__(**kwargs)`` would instead store a
    stray ``clock`` attribute without complaint. So the decision is made from what
    the caller declares, not from the instance's name: a local ``VariableRef`` callee
    is a timer when its name is in ``ctx.timer_instances`` (filled by the transpiler
    from the block's own ``VAR`` sections, ``TON`` and ``TON_TIME`` alike). A
    ``Member`` callee (``"db".TON(...)``) has no declaration in reach; it counts as a
    timer only when its member name *is* an IEC timer type name, exactly -- the one
    remaining guess, kept narrow. An ``Index`` callee (``#arms[#i](...)``) is never
    one: the corpus holds no indexed timer, and a wrong ``clock=`` is a silent
    attribute on the callee.

    The old rule -- any callee name containing ``"timer"``, ``"ton"``, ``"tof"`` or
    ``"tp"`` -- missed 13 timer instances in the corpus (``TypeError`` at the call)
    and matched FB instances that merely contained ``"tp"``.
    """
    if isinstance(callee_expr, VariableRef):
        return callee_expr.name in ctx.timer_instances
    if isinstance(callee_expr, Member):
        return timer_class_name(callee_expr.name) is not None
    return False


def _generate_fb_instance_call(
    statement: Call,
    ctx: _Context,
) -> list[str]:
    """Native lines for an FB instance call: ``#instance(...)``, ``#arms[#i](...)``, or ``"db".TON(...)``.

    A positional (unnamed) argument raises (the instance's FB type is not known
    here, so there is no signature to bind it against), a ``:=`` argument
    becomes ``name=value`` in the call's keyword arguments, an ``=>`` argument becomes a
    trailing ``target = {callee}.name`` line, and a callee that is a timer instance
    gets a trailing ``clock=self._runtime.clock`` keyword argument -- see
    :func:`_callee_is_timer`. The callee
    itself renders through :func:`render` the same way any other callee shape here does
    (``self.tmr`` / ``self.arms[self.i]`` / ``self._runtime.global_dbs["db"].TON``), not
    from a hardcoded ``self.{name}`` -- an ``Index`` or ``Member`` callee renders
    correctly through the same call as a plain local one.

    Parameters
    ----------
    statement : Call
        The call to generate; ``statement.callee_expr`` must already be known to be a
        local (``is_local=True``) ``VariableRef``, an ``Index``, or a ``Member`` (the
        caller's job, in :func:`_generate_call`).
    ctx : _Context
        Forwarded to every :func:`render` call.

    Returns
    -------
    list[str]
        The rendered lines (unindented -- the caller prefixes them).

    Raises
    ------
    UnsupportedStatement
        A named argument's ``value_expr`` is ``None`` (the slice failed to parse).
    plc_code.executor.renderer.UnsupportedExpression
        :func:`render` raised for the callee or an argument.
    """
    callee_expr = statement.callee_expr
    assert isinstance(callee_expr, VariableRef | Index | Member)
    callee_text = render(callee_expr, ctx.string_constants, ctx.signature_resolver)
    input_params: list[str] = []
    output_assignments: list[str] = []
    for argument in statement.arguments:
        if not argument.name:
            raise UnsupportedStatement(
                f"Call at line {statement.line}: FB instance call passes a positional argument; "
                "the instance's type is not resolvable here, call it with named arguments",
                line=statement.line,
            )
        if argument.value_expr is None:
            raise UnsupportedStatement(
                f"Call at line {statement.line} argument {argument.name!r} has no parsed expression tree",
                line=statement.line,
            )
        value_text = render(argument.value_expr, ctx.string_constants, ctx.signature_resolver)
        if argument.is_output:
            output_assignments.append(f"{value_text} = {callee_text}.{argument.name}")
        else:
            input_params.append(f"{argument.name}={value_text}")
    call_params = ", ".join(input_params)
    if _callee_is_timer(callee_expr, ctx):
        call_params = (
            f"{call_params}, clock=self._runtime.clock" if call_params else "clock=self._runtime.clock"
        )
    return [f"{callee_text}({call_params})", *output_assignments]


def _generate_named_call_statement(
    statement: Call,
    translator: StatementTranslator,
    ctx: _Context,
) -> list[str]:
    """Native lines for a quoted-block call statement (``"Block"(x := #a, out => #b);``).

    Calls ``StatementTranslator._emit_named_call`` directly, with every argument value
    taken from :func:`render` and its in-out write-back flag from
    :func:`_is_write_back_candidate`. The result-dict variable ``_emit_named_call`` also
    returns is discarded -- a standalone call statement never reads the block's return
    value.

    Parameters
    ----------
    statement : Call
        The call to generate; ``statement.callee_expr`` must already be known to be a
        quoted (``is_local=False``, ``is_absolute=False``) ``VariableRef`` (the caller's
        job, in :func:`_generate_call`).
    translator : StatementTranslator
        Shared translator instance; only ``_emit_named_call`` is used.
    ctx : _Context
        Forwarded to every :func:`render` call.

    Returns
    -------
    list[str]
        The rendered lines (unindented -- the caller prefixes them).

    Raises
    ------
    UnsupportedStatement
        A named argument's ``value_expr`` is ``None`` (the slice failed to parse).
    plc_code.executor.renderer.UnsupportedExpression
        :func:`render` raised.
    """
    assert isinstance(statement.callee_expr, VariableRef)
    block_name = statement.callee_expr.name
    names_for_positional = _positional_names(block_name, statement.arguments, ctx, statement.line)
    bound_arguments: list[tuple[str, str, bool, bool]] = []
    for argument in statement.arguments:
        name = argument.name or next(names_for_positional)
        if argument.value_expr is None:
            raise UnsupportedStatement(
                f"Call at line {statement.line} argument {name!r} has no parsed expression tree",
                line=statement.line,
            )
        value_text = render(argument.value_expr, ctx.string_constants, ctx.signature_resolver)
        write_back = not argument.is_output and _is_write_back_candidate(
            argument.value_expr, ctx.string_constants
        )
        bound_arguments.append((name, value_text, argument.is_output, write_back))
    lines, _result_var = translator._emit_named_call(block_name, bound_arguments)  # noqa: SLF001
    return list(lines)


def _generate_call(
    statement: Call,
    prefix: str,
    translator: StatementTranslator,
    ctx: _Context,
) -> list[str]:
    """One ``Call``'s Python line(s), rendered natively from ``statement.callee_expr``'s own shape:

    * ``callee_expr`` is a ``VariableRef`` with ``is_local`` True (``#instance``), an
      ``Index`` (``#arms[#i]``), or a ``Member`` (``"db".TON``) -- an FB instance call,
      rendered by :func:`_generate_fb_instance_call`.
    * ``callee_expr`` is a ``VariableRef`` with neither ``is_local`` nor ``is_absolute``
      (``"Block"``) -- a quoted-block call statement, rendered by
      :func:`_generate_named_call_statement`.
    * Anything else -- ``callee_expr`` is ``None`` (the slice failed to parse, or parsed
      to something no statement callee can be, e.g. a bare unquoted, unprefixed name such
      as a builtin call used as a statement) or a ``VariableRef`` with ``is_absolute``
      True -- raises.

    Parameters
    ----------
    statement : Call
        The call to generate.
    prefix : str
        Indentation to prepend to the emitted line(s).
    translator : StatementTranslator
        Shared translator instance, forwarded to :func:`_generate_named_call_statement`.
    ctx : _Context
        Forwarded to :func:`render`; see :func:`generate_statements`.

    Returns
    -------
    list[str]
        The rendered lines, each already prefixed with ``prefix``.

    Raises
    ------
    UnsupportedStatement
        ``statement.callee_expr`` is not one of the shapes above, or a named argument's
        ``value_expr`` is ``None``.
    plc_code.executor.renderer.UnsupportedExpression
        :func:`render` raised for the callee or an argument.
    """
    callee_expr = statement.callee_expr
    if isinstance(callee_expr, VariableRef) and not callee_expr.is_absolute:
        if callee_expr.is_local:
            lines = _generate_fb_instance_call(statement, ctx)
        else:
            lines = _generate_named_call_statement(statement, translator, ctx)
    elif isinstance(callee_expr, Index | Member):
        lines = _generate_fb_instance_call(statement, ctx)
    else:
        raise UnsupportedStatement(
            f"Call at line {statement.line} has no supported callee shape", line=statement.line
        )
    return [prefix + line for line in lines]


def generate_statements(
    statements: list[Statement],
    indent: int = 0,
    translator: StatementTranslator | None = None,
    string_constants: dict[str, int] | None = None,
    signature_resolver: SignatureResolver | None = None,
    timer_instances: frozenset[str] = frozenset(),
) -> list[str]:
    """Generate Python lines for a list of statements, natively from the tree.

    Parameters
    ----------
    statements : list[Statement]
        The tree, as ``parse_statements`` returns it.
    indent : int
        Depth in four-space units. The caller splices the result into a class
        body, so the lines come back already indented.
    translator : StatementTranslator | None
        Shared translator instance for the quoted-block-call formatter
        (``_emit_named_call``). Defaults to a fresh one; passed explicitly so a caller
        may share state across a whole block.
    string_constants : dict[str, int] | None
        Mapping from a quoted string literal (e.g. ``'"USER_FREEWHEEL"'``) to
        the integer value assigned to it, as collected by
        ``SCLTranspiler._collect_string_constants``. A literal that matches a
        CASE label is rendered as that bare integer (see :func:`_render_case_label`);
        matching elsewhere it is rendered as ``self.NAME`` (see :func:`render`'s own
        ``string_constants`` parameter). ``None`` (the default) renders every string
        literal as itself.

    signature_resolver : SignatureResolver | None
        Resolves a called block's name to its declared input names in order, so a
        positional call argument binds to a parameter. ``None`` (the default) makes
        any positional argument to a named block raise instead of being dropped; see
        :mod:`plc_code.executor.arguments`.
    timer_instances : frozenset[str]
        Names of the block's own variables declared with an IEC timer type. An FB
        instance call whose callee is one of them gets the ``clock=`` argument a
        timer's ``__call__`` requires; see :func:`_callee_is_timer`.

    Returns
    -------
    list[str]
        Python lines, in source order.

    Raises
    ------
    UnsupportedStatement
        For a statement kind with no branch here, or an expression-bearing slice that
        failed to parse.
    plc_code.executor.renderer.UnsupportedExpression
        For a tree node :func:`render` has no visitor for, or refuses to render.
    """
    return _generate_statements(
        statements,
        indent,
        translator if translator is not None else StatementTranslator(),
        _Context(
            string_constants=string_constants,
            signature_resolver=signature_resolver,
            timer_instances=timer_instances,
        ),
    )


def _generate_statements(
    statements: list[Statement],
    indent: int,
    translator: StatementTranslator,
    ctx: _Context,
) -> list[str]:
    """The loop behind :func:`generate_statements`, with the context already built."""
    prefix = INDENT * indent
    lines: list[str] = []

    for statement in statements:
        if isinstance(statement, Assignment):
            lines.extend(_generate_assignment(statement, prefix, translator, ctx))
            continue

        if isinstance(statement, If):
            for position, branch in enumerate(statement.branches):
                keyword = "if" if position == 0 else "elif"
                condition = _render_header_expression(
                    branch.condition_expr,
                    ctx,
                    f"If branch {position} condition",
                    statement.line,
                )
                lines.append(f"{prefix}{keyword} {condition}:")
                lines.extend(_generate_body(branch.body, indent + 1, translator, ctx))
            if statement.else_body:
                lines.append(f"{prefix}else:")
                lines.extend(_generate_body(statement.else_body, indent + 1, translator, ctx))
            continue

        if isinstance(statement, For):
            variable = _render_for_variable(statement.variable, ctx)
            start = _render_header_expression(
                statement.start_expr, ctx, "For loop start bound", statement.line
            )
            end = _render_header_expression(statement.end_expr, ctx, "For loop end bound", statement.line)
            bounds = f"{start}, {end} + 1"
            if statement.step:
                step = _render_header_expression(statement.step_expr, ctx, "For loop step", statement.line)
                bounds += f", {step}"
            lines.append(f"{prefix}for {variable} in range({bounds}):")
            lines.extend(_generate_body(statement.body, indent + 1, translator, ctx))
            continue

        if isinstance(statement, While):
            condition = _render_header_expression(
                statement.condition_expr, ctx, "While condition", statement.line
            )
            lines.append(f"{prefix}while {condition}:")
            lines.extend(_generate_body(statement.body, indent + 1, translator, ctx))
            continue

        if isinstance(statement, Case):
            selector = _render_header_expression(
                statement.selector_expr, ctx, "Case selector", statement.line
            )
            for position, arm in enumerate(statement.branches):
                keyword = "if" if position == 0 else "elif"
                values = [
                    _render_case_label(value_expr, ctx, statement.line) for value_expr in arm.values_expr
                ]
                if len(values) == 1:
                    test = f"{selector} == {values[0]}"
                else:
                    test = f"{selector} in ({', '.join(values)})"
                lines.append(f"{prefix}{keyword} {test}:")
                lines.extend(_generate_body(arm.body, indent + 1, translator, ctx))
            if statement.default:
                lines.append(f"{prefix}else:")
                lines.extend(_generate_body(statement.default, indent + 1, translator, ctx))
            continue

        if isinstance(statement, Call):
            lines.extend(_generate_call(statement, prefix, translator, ctx))
            continue

        if isinstance(statement, Return):
            lines.append(f"{prefix}return")
            continue

        if isinstance(statement, Exit):
            lines.append(f"{prefix}break")
            continue

        raise UnsupportedStatement(
            f"{type(statement).__name__} at line {statement.line}", line=statement.line
        )

    return lines
