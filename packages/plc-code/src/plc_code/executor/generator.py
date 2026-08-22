"""Python generation from the statement AST.

The executor used to rewrite SCL as text: a now-deleted ``ControlFlowTranslator``
split a region's flattened content on newlines and matched control-flow
keywords with regular expressions, so anything it did not recognise was copied
verbatim into the generated Python while ``transpile_block`` reported success.
This module reads the statement tree instead, and a construct it cannot
generate raises rather than emitting nothing.

`Assignment` is rendered natively (Task 6): `generate_statements` calls
`plc_code.executor.renderer.render` directly on `target_expr`/`value_expr`
rather than rebuilding SCL text and handing it to a translator (see
`_generate_assignment`). Three shapes still fall back to the text dispatcher
-- a slice that failed to parse, the named-call-with-outputs shape `render`
cannot express (`#ret := "Block"(x := #a, out => #b)`), and any node `render`
itself refuses (raises `UnsupportedExpression` for).

`If`, `For`, `While` and `Case` are rendered natively too (Task 7): a
condition (`Branch.condition_expr`, `While.condition_expr`), a `For` bound
(`start_expr`/`end_expr`/`step_expr`), and a `Case` selector
(`selector_expr`) all go through `render` via `_render_expression_or_fallback`,
falling back to the text dispatcher on the same two conditions as
`_generate_assignment`'s fallback (no tree, or `render` raises). A `Case`
label is a *different* mapping from every other position: `_render_case_label`
maps a label whose tree is a non-local, non-absolute `VariableRef` with a
matching `string_constants` entry to that entry's bare integer -- the ordinary
`self.NAME` substitution `render`'s own `_render_variable_ref` would apply to
that identical tree shape everywhere else must NOT apply here (see
`_render_case_label`'s own docstring). A `For` loop's own variable name has no
`*_expr` field on the statement AST and stays on the text path unconditionally
-- there is no tree for it to render from. `Call`, `Return` and `Exit` still
rebuild the SCL string and hand it to `ExpressionTranslator` /
`StatementTranslator`, the same translators the deleted text path used --
replacing those is a later task in the same plan, along with the body of a
still-native `If`/`For`/`While`/`Case`, which recurses through
`generate_statements` itself (via `_generate_body`) and so already renders any
nested `Assignment`, `If`, `For`, `While` or `Case` it contains natively too.

`_generate_statements_via_strings` is the pre-Task-6 generator, kept alive
under a private name as the differential's "old" side (see
`tests/test_generator_native_differential.py`) until a later task deletes it.
For everything still routed through it -- `Call`/`Return`/`Exit`, an
`Assignment` that falls back, and a header slice that falls back --
`StatementTranslator.translate_simple_statement` (for `Call`/`Return`/`Exit`)
or `StatementTranslator.translate_if_condition` / `.expr_translator.translate`
(for a fallen-back header slice) remain the dispatch surface, unchanged from
before Task 6.
"""

from __future__ import annotations

from plc_code.executor.codegen import StatementTranslator
from plc_code.executor.renderer import UnsupportedExpression, render
from plc_code.parser.expressions import Expression, FunctionCall, VariableRef
from plc_code.parser.lexer import Token
from plc_code.parser.statements import Assignment, Call, Case, Exit, For, If, Return, Statement, While

INDENT = "    "

#: How many `Assignment` statements `_generate_assignment` has rendered natively (from
#: the tree) versus routed to `_generate_assignment_via_dispatcher`, since the last
#: :func:`reset_assignment_render_counters` call. Process-global, mutable, and not
#: thread-safe by design -- this exists purely so a differential run can answer "how
#: much of what it just measured was actually exercising the native path?" (see
#: :func:`assignment_render_counts`), a question "586 agree" alone cannot answer: an
#: `Assignment` that falls back compares the dispatcher against itself, which can only
#: ever agree, so a differential dominated by fallbacks would look reassuring for the
#: wrong reason. Never read directly outside this module; use the accessor functions.
_native_assignment_renders = 0
_fallback_assignment_renders = 0


def reset_assignment_render_counters() -> None:
    """Reset both `Assignment`-rendering counters to zero.

    Call this immediately before the measurement whose native/fallback split you want
    to attribute -- typically right before one `generate_statements` call over one
    unit -- so a later :func:`assignment_render_counts` read reflects only that
    measurement and not whatever ran before it in the same process.
    """
    global _native_assignment_renders, _fallback_assignment_renders
    _native_assignment_renders = 0
    _fallback_assignment_renders = 0


def assignment_render_counts() -> tuple[int, int]:
    """The `Assignment`-rendering counts accumulated since the last reset.

    Returns
    -------
    tuple[int, int]
        ``(native, fallback)`` -- how many `Assignment` statements
        :func:`_generate_assignment` has rendered from the tree versus routed to
        :func:`_generate_assignment_via_dispatcher`, since the last
        :func:`reset_assignment_render_counters` call (or process start, if never
        reset).
    """
    return _native_assignment_renders, _fallback_assignment_renders


#: The control-flow counterpart to `_native_assignment_renders`/`_fallback_assignment_renders`
#: above -- same rationale, same process-global/not-thread-safe caveat, same "never read
#: directly outside this module" rule. Incremented once per header-level expression slice
#: :func:`_render_expression_or_fallback` or :func:`_render_case_label` is asked to render:
#: an `If`/`While` condition, one `For` bound (`start`/`end`/`step`, each counted
#: separately), a `Case` selector (once per `Case`, not once per arm -- it is computed once
#: and reused, matching the pre-Task-7 cost), or one `Case` label. See
#: :func:`reset_control_flow_render_counters` / :func:`control_flow_render_counts`.
_native_control_flow_renders = 0
_fallback_control_flow_renders = 0


def reset_control_flow_render_counters() -> None:
    """Reset both control-flow-header counters to zero.

    Call this immediately before the measurement whose native/fallback split you want to
    attribute, mirroring :func:`reset_assignment_render_counters` for `If`/`For`/`While`/
    `Case` headers instead of `Assignment`.
    """
    global _native_control_flow_renders, _fallback_control_flow_renders
    _native_control_flow_renders = 0
    _fallback_control_flow_renders = 0


def control_flow_render_counts() -> tuple[int, int]:
    """The control-flow-header render counts accumulated since the last reset.

    Returns
    -------
    tuple[int, int]
        ``(native, fallback)`` -- how many header-level expression slices (an `If`/`While`
        condition, a `For` bound, a `Case` selector or label) rendered from the tree versus
        fell back to the text dispatcher, since the last
        :func:`reset_control_flow_render_counters` call (or process start, if never reset).
    """
    return _native_control_flow_renders, _fallback_control_flow_renders


class UnsupportedStatement(Exception):
    """A statement kind the generator has no branch for.

    Raised rather than skipped. A generator that silently emits nothing for a
    node it does not know is the failure this module exists to remove.
    """


def scl_text(tokens: list[Token]) -> str:
    """The SCL text of a token slice, spelled as ``Region.content`` spells it.

    Parameters
    ----------
    tokens : list[Token]
        A slice carried by a statement node, such as ``Assignment.value``.

    Returns
    -------
    str
        The token values joined with single spaces. `Region.content` is built
        the same way, so this reproduces the substring the text path worked
        from — `#a` reads as `# a`, and that lossiness is deliberate: the
        translators expect it.
    """
    return " ".join(token.value for token in tokens)


def _map_string_constants(text: str, string_constants: dict[str, int] | None) -> str:
    """Replace quoted string-constant literals in ``text`` with ``self.NAME``.

    Mirrors the substitution ``transpiler.py`` used to perform globally, with
    regex repairs afterwards, before this generator existed: each key (e.g.
    ``'"NAME"'``) is replaced by ``" self.NAME "`` wherever it occurs in
    ``text``. Reconstructed text is already single-space-separated per token
    (see :func:`scl_text`), so — unlike the old blind text rewrite — this
    substitution never glues an adjacent keyword to the replacement and needs
    no spacing repair afterwards.

    A CASE label is not routed through this helper: a label position maps a
    matching literal to its bare integer value instead, which the caller
    handles directly.

    Parameters
    ----------
    text : str
        Reconstructed SCL source text, as :func:`scl_text` renders it.
    string_constants : dict[str, int] | None
        Mapping from quoted literal (with its quotes) to the integer value
        assigned to it, or ``None``/empty when the block declares none.

    Returns
    -------
    str
        ``text``, with every mapped literal replaced.
    """
    if not string_constants:
        return text
    for literal in string_constants:
        name = literal.strip('"')
        text = text.replace(literal, f" self.{name} ")
    return text


def _generate_body_via_strings(
    statements: list[Statement],
    indent: int,
    translator: StatementTranslator,
    string_constants: dict[str, int] | None,
) -> list[str]:
    """Generate a nested body's lines via :func:`_generate_statements_via_strings`.

    ``_generate_statements_via_strings``'s own copy of the "pad an empty body with
    ``pass``" helper -- see :func:`_generate_body` for the shared rationale. Kept as
    a separate function, recursing into :func:`_generate_statements_via_strings`
    rather than into :func:`generate_statements`, so that once ``generate_statements``
    renders ``Assignment`` natively, a nested body inside an ``If``/``For``/``While``/
    ``Case`` on *this* (old) side still recurses entirely through the old,
    text-rewriting path -- never silently picking up native rendering partway through
    a call that is supposed to be the differential's unchanged "old" side.

    Parameters
    ----------
    statements : list[Statement]
        The nested body to generate.
    indent : int
        Depth in four-space units for the body's own lines (one deeper than
        the header this body follows).
    translator : StatementTranslator
        Shared translator instance, forwarded unchanged.
    string_constants : dict[str, int] | None
        Forwarded unchanged; see :func:`_generate_statements_via_strings`.

    Returns
    -------
    list[str]
        Python lines for the body. Never empty: ``["pass"]`` (at ``indent``)
        stands in for a body that generated no lines of its own.
    """
    lines = _generate_statements_via_strings(statements, indent, translator, string_constants)
    if not lines:
        lines.append(INDENT * indent + "pass")
    return lines


def _generate_body(
    statements: list[Statement],
    indent: int,
    translator: StatementTranslator,
    string_constants: dict[str, int] | None,
) -> list[str]:
    """Generate a nested body's lines via :func:`generate_statements`, padding when empty.

    The caller always emits a header line (``if``/``elif``/``else``/``for``/
    ``while``/a ``CASE`` arm) unconditionally, and Python requires at least
    one statement to follow it. A body that parses to zero statements — a
    comment-only branch is the common real-world case, since comment tokens
    never reach the statement parser — would otherwise leave that header
    dangling with nothing indented under it, which is not valid Python.

    Recurses into :func:`generate_statements` (the tree-driven generator), not
    :func:`_generate_statements_via_strings` -- see :func:`_generate_body_via_strings`
    for the sibling that keeps the old path's recursion self-contained.

    Parameters
    ----------
    statements : list[Statement]
        The nested body to generate.
    indent : int
        Depth in four-space units for the body's own lines (one deeper than
        the header this body follows).
    translator : StatementTranslator
        Shared translator instance, forwarded unchanged.
    string_constants : dict[str, int] | None
        Forwarded unchanged; see :func:`generate_statements`.

    Returns
    -------
    list[str]
        Python lines for the body. Never empty: ``["pass"]`` (at ``indent``)
        stands in for a body that generated no lines of its own.
    """
    lines = generate_statements(statements, indent, translator, string_constants)
    if not lines:
        lines.append(INDENT * indent + "pass")
    return lines


def _generate_statements_via_strings(
    statements: list[Statement],
    indent: int = 0,
    translator: StatementTranslator | None = None,
    string_constants: dict[str, int] | None = None,
) -> list[str]:
    """Generate Python lines for a list of statements, rebuilding SCL text per statement.

    This is the pre-Task-6 body of ``generate_statements``, kept alive under a
    private name rather than deleted outright: it is the "old" side of
    ``test_generator_native_differential.py`` (Task 6's unit-level differential
    over the corpus, comparing this function line-for-line against the tree-driven
    ``generate_statements``), and it is what Task 9 deletes once every statement
    kind has a native renderer of its own. Nothing here changed behaviourally when
    it was renamed from ``generate_statements`` to this name.

    Parameters
    ----------
    statements : list[Statement]
        The tree, as ``parse_statements`` returns it.
    indent : int
        Depth in four-space units. The caller splices the result into a class
        body, so the lines come back already indented.
    translator : StatementTranslator | None
        The translator to render expressions and simple statements with.
        Defaults to a fresh one; passed explicitly so a caller may share state
        across a whole block.
    string_constants : dict[str, int] | None
        Mapping from a quoted string literal (e.g. ``'"USER_FREEWHEEL"'``) to
        the integer value assigned to it, as collected by
        ``SCLTranspiler._collect_string_constants``. A literal that matches a
        CASE label is rendered as that bare integer; matching elsewhere it is
        rendered as ``self.NAME``. ``None`` (the default) renders every string
        literal as itself.

    Returns
    -------
    list[str]
        Python lines, in source order.

    Raises
    ------
    UnsupportedStatement
        For a statement kind with no branch here.
    """
    translator = translator if translator is not None else StatementTranslator()
    prefix = INDENT * indent
    lines: list[str] = []

    for statement in statements:
        if isinstance(statement, Assignment):
            target = scl_text(statement.target)
            value = scl_text(statement.value)
            text = _map_string_constants(f"{target} := {value} ;", string_constants)
            lines.extend(prefix + line for line in translator.translate_simple_statement(text))
            continue

        if isinstance(statement, If):
            for position, branch in enumerate(statement.branches):
                keyword = "if" if position == 0 else "elif"
                condition_text = _map_string_constants(scl_text(branch.condition), string_constants)
                condition = translator.translate_if_condition(condition_text)
                lines.append(f"{prefix}{keyword} {condition}:")
                lines.extend(
                    _generate_body_via_strings(branch.body, indent + 1, translator, string_constants)
                )
            if statement.else_body:
                lines.append(f"{prefix}else:")
                lines.extend(
                    _generate_body_via_strings(statement.else_body, indent + 1, translator, string_constants)
                )
            continue

        if isinstance(statement, For):
            variable_text = _map_string_constants(scl_text(statement.variable), string_constants)
            start_text = _map_string_constants(scl_text(statement.start), string_constants)
            end_text = _map_string_constants(scl_text(statement.end), string_constants)
            variable = translator.expr_translator.translate(variable_text)
            start = translator.expr_translator.translate(start_text)
            end = translator.expr_translator.translate(end_text)
            bounds = f"{start}, {end} + 1"
            if statement.step:
                step_text = _map_string_constants(scl_text(statement.step), string_constants)
                bounds += f", {translator.expr_translator.translate(step_text)}"
            lines.append(f"{prefix}for {variable} in range({bounds}):")
            lines.extend(_generate_body_via_strings(statement.body, indent + 1, translator, string_constants))
            continue

        if isinstance(statement, While):
            condition_text = _map_string_constants(scl_text(statement.condition), string_constants)
            condition = translator.translate_if_condition(condition_text)
            lines.append(f"{prefix}while {condition}:")
            lines.extend(_generate_body_via_strings(statement.body, indent + 1, translator, string_constants))
            continue

        if isinstance(statement, Case):
            selector_text = _map_string_constants(scl_text(statement.selector), string_constants)
            selector = translator.expr_translator.translate(selector_text)
            for position, arm in enumerate(statement.branches):
                keyword = "if" if position == 0 else "elif"
                values = []
                for v in arm.values:
                    label_text = scl_text(v)
                    if string_constants and label_text in string_constants:
                        values.append(str(string_constants[label_text]))
                    else:
                        values.append(
                            translator.expr_translator.translate(
                                _map_string_constants(label_text, string_constants)
                            )
                        )
                if len(values) == 1:
                    test = f"{selector} == {values[0]}"
                else:
                    test = f"{selector} in ({', '.join(values)})"
                lines.append(f"{prefix}{keyword} {test}:")
                lines.extend(_generate_body_via_strings(arm.body, indent + 1, translator, string_constants))
            if statement.default:
                lines.append(f"{prefix}else:")
                lines.extend(
                    _generate_body_via_strings(statement.default, indent + 1, translator, string_constants)
                )
            continue

        if isinstance(statement, Call):
            arguments = []
            for argument in statement.arguments:
                value = scl_text(argument.value)
                if not argument.name:
                    arguments.append(value)
                elif argument.is_output:
                    arguments.append(f"{argument.name} => {value}")
                else:
                    arguments.append(f"{argument.name} := {value}")
            call = _map_string_constants(
                f"{scl_text(statement.callee)} ( {' , '.join(arguments)} ) ;", string_constants
            )
            lines.extend(prefix + line for line in translator.translate_simple_statement(call))
            continue

        if isinstance(statement, Return):
            lines.extend(prefix + line for line in translator.translate_simple_statement("RETURN ;"))
            continue

        if isinstance(statement, Exit):
            lines.extend(prefix + line for line in translator.translate_simple_statement("EXIT ;"))
            continue

        raise UnsupportedStatement(f"{type(statement).__name__} at line {statement.line}")

    return lines


def _is_named_call_with_output_binding(expression: Expression | None) -> bool:
    """Whether ``expression`` is a quoted-block call that binds at least one ``=>`` output.

    ``render``'s ``_render_named_call`` silently drops an ``is_output=True`` argument
    when building the call's parameter dict -- the expression path can only return
    *one* value, so it has nowhere to route a second, out-of-band write-back. The
    text path does not have this gap: ``StatementTranslator._translate_named_call_assignment``
    emits the call, the output-assignment lines, and the return-value assignment as
    separate statements. So an ``Assignment`` whose right-hand side has this exact
    shape cannot be rendered from the tree alone and must keep routing through the
    dispatcher -- see :func:`_generate_assignment`.

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


def _generate_assignment_via_dispatcher(
    statement: Assignment,
    prefix: str,
    translator: StatementTranslator,
    string_constants: dict[str, int] | None,
) -> list[str]:
    """One ``Assignment``'s lines via the text dispatcher -- the fallback native rendering cannot take.

    Reuses exactly the shape ``_generate_statements_via_strings`` builds: rebuild the
    SCL text from the token slices, map string constants over it, and hand it to
    ``StatementTranslator.translate_simple_statement``. Called for a shape
    :func:`_generate_assignment` has determined cannot be rendered from the tree
    alone -- either because a slice failed to parse (``target_expr``/``value_expr`` is
    ``None``), because the value is the named-call-with-outputs shape (see
    :func:`_is_named_call_with_output_binding`), or because :func:`render` itself
    raised :class:`~plc_code.executor.renderer.UnsupportedExpression` for a node it
    has no visitor for.

    Parameters
    ----------
    statement : Assignment
        The assignment to generate.
    prefix : str
        Indentation to prepend to every emitted line.
    translator : StatementTranslator
        Shared translator instance, forwarded unchanged.
    string_constants : dict[str, int] | None
        Forwarded unchanged; see :func:`generate_statements`.

    Returns
    -------
    list[str]
        The dispatcher's Python lines, each already prefixed with ``prefix``.
    """
    target = scl_text(statement.target)
    value = scl_text(statement.value)
    text = _map_string_constants(f"{target} := {value} ;", string_constants)
    return [prefix + line for line in translator.translate_simple_statement(text)]


def _generate_assignment(
    statement: Assignment,
    prefix: str,
    translator: StatementTranslator,
    string_constants: dict[str, int] | None,
) -> list[str]:
    """One ``Assignment``'s Python line(s): rendered natively from the tree, or via the dispatcher.

    Native rendering (``f"{render(target)} = {render(value)}"``) is attempted unless
    one of three conditions holds, in which case the whole statement is routed through
    :func:`_generate_assignment_via_dispatcher` instead -- the same text-rewriting path
    :func:`_generate_statements_via_strings` uses for every ``Assignment``:

    1. ``statement.target_expr`` or ``statement.value_expr`` is ``None`` (the slice
       failed to parse as an expression) -- there is no tree to render.
    2. The value is a named-call-with-outputs (see
       :func:`_is_named_call_with_output_binding`) -- :func:`render` would silently
       drop the ``=>`` bindings.
    3. :func:`render` raises :class:`~plc_code.executor.renderer.UnsupportedExpression`
       for either side -- a node the renderer has no visitor for (or refuses to
       render, e.g. a bare builtin call binding an output). This is the general form
       of case 2: whenever the tree alone cannot be rendered, fall back, rather than
       enumerating every such shape by hand.

    A compound assignment (``#a += 1``) needs none of this: the statement parser
    desugars it into an ordinary ``:=`` ``Assignment`` before it ever reaches the
    generator (see ``statement_parser.py``'s own comment on the desugaring), with
    ``value_expr`` already the fully parsed ``BinaryOp`` for ``#a + 1`` -- probed
    directly and confirmed, it renders natively with no special case.

    Every call increments exactly one of the module-level counters (see
    :func:`reset_assignment_render_counters` / :func:`assignment_render_counts`):
    ``_native_assignment_renders`` when this returns the native line, otherwise
    ``_fallback_assignment_renders``. A caller comparing this function's output
    against the dispatcher's for the same input can only ever agree on a fallback
    (both sides call the same dispatcher), so the split those counters expose is what
    tells such a comparison how much of what it measured actually exercised the new
    path.

    Parameters
    ----------
    statement : Assignment
        The assignment to generate.
    prefix : str
        Indentation to prepend to the emitted line.
    translator : StatementTranslator
        Shared translator instance, forwarded to the dispatcher fallback.
    string_constants : dict[str, int] | None
        Forwarded to :func:`render` (native path) or the dispatcher fallback
        unchanged; see :func:`generate_statements`.

    Returns
    -------
    list[str]
        One line (native) or the dispatcher's lines (fallback), each already
        prefixed with ``prefix``.
    """
    global _native_assignment_renders, _fallback_assignment_renders
    if statement.target_expr is None or statement.value_expr is None:
        _fallback_assignment_renders += 1
        return _generate_assignment_via_dispatcher(statement, prefix, translator, string_constants)
    if _is_named_call_with_output_binding(statement.value_expr):
        _fallback_assignment_renders += 1
        return _generate_assignment_via_dispatcher(statement, prefix, translator, string_constants)
    try:
        target_text = render(statement.target_expr, string_constants)
        value_text = render(statement.value_expr, string_constants)
    except UnsupportedExpression:
        _fallback_assignment_renders += 1
        return _generate_assignment_via_dispatcher(statement, prefix, translator, string_constants)
    _native_assignment_renders += 1
    return [f"{prefix}{target_text} = {value_text}"]


def _render_expression_or_fallback(
    tokens: list[Token],
    expr: Expression | None,
    string_constants: dict[str, int] | None,
    translator: StatementTranslator,
) -> str:
    """One control-flow header expression: an `If`/`While` condition, a `For` bound, or a `Case` selector.

    Native rendering (`render(expr, string_constants)`) is attempted whenever `expr` is not
    `None`; a `None` tree (the slice failed to parse) or `render` raising
    `UnsupportedExpression` both fall back to the text dispatcher -- exactly the same two
    conditions :func:`_generate_assignment` falls back for, minus the named-call-with-outputs
    special case, which does not arise in a condition/bound/selector position (that shape is
    only reachable as an `Assignment`'s right-hand side).

    The fallback path reproduces the pre-Task-7 text exactly: `translate_if_condition` and
    `translator.expr_translator.translate` are both, read directly, nothing more than
    `self.expr_translator.translate(text)` -- so one fallback shape serves `If`/`While`
    conditions, `For` bounds, and `Case` selectors alike; nothing here re-derives what
    `StatementTranslator.translate_if_condition` already is.

    Every call increments exactly one of :data:`_native_control_flow_renders` /
    :data:`_fallback_control_flow_renders` (see :func:`reset_control_flow_render_counters` /
    :func:`control_flow_render_counts`).

    Parameters
    ----------
    tokens : list[Token]
        The slice's raw token run (e.g. `Branch.condition`, `For.start`), used only by the
        fallback path.
    expr : Expression | None
        The slice's parsed tree, or `None` when it failed to parse.
    string_constants : dict[str, int] | None
        Forwarded to :func:`render` (native path) or applied via :func:`_map_string_constants`
        to the fallback text; see :func:`generate_statements`.
    translator : StatementTranslator
        Shared translator instance, used by the fallback path only.

    Returns
    -------
    str
        The rendered Python expression text.
    """
    global _native_control_flow_renders, _fallback_control_flow_renders
    if expr is not None:
        try:
            text = render(expr, string_constants)
        except UnsupportedExpression:
            pass
        else:
            _native_control_flow_renders += 1
            return text
    _fallback_control_flow_renders += 1
    text = _map_string_constants(scl_text(tokens), string_constants)
    return translator.expr_translator.translate(text)


def _render_case_label(
    tokens: list[Token],
    expr: Expression | None,
    string_constants: dict[str, int] | None,
    translator: StatementTranslator,
) -> str:
    """One `Case` label: a mapped symbolic constant renders as its bare integer, everything else natively.

    A label is a different mapping from an ordinary expression position -- see the task
    brief this function implements. A label whose tree is a non-local, non-absolute
    `VariableRef` (`"MODE_ONE"`, never `#name` or `%name`) with quoted spelling
    (`f'"{name}"'`) present in `string_constants` emits that mapping's bare integer, the
    same value a matching `Assignment` right-hand side would resolve to at runtime. This is
    deliberately NOT the same substitution :func:`render`'s own `_render_variable_ref`
    performs for that identical tree shape everywhere else (`self.NAME`): applying that
    substitution here would turn `if self.s == 1:` into `if self.s == self.MODE_ONE:`,
    which `test_case_labels.py::TestSymbolicLabels` (an executable CASE, not a text
    comparison) would catch immediately, since `self.MODE_ONE` is never assigned in the
    generated class.

    Every other label -- a plain literal (`1`), a range that failed to parse (`expr is
    None`), or any tree :func:`render` raises `UnsupportedExpression` for -- goes through
    :func:`render` if it has a tree, else the text-dispatcher fallback below, which
    reproduces the pre-Task-7 per-label logic exactly: a literal match in
    `string_constants` (by raw token text, not by tree shape -- this is the fallback path's
    own pre-existing lookup, unrelated to the native ruling above) emits the bare integer;
    otherwise the token text is translated as an ordinary expression.

    Every call increments exactly one of :data:`_native_control_flow_renders` /
    :data:`_fallback_control_flow_renders`, same as :func:`_render_expression_or_fallback`.

    Parameters
    ----------
    tokens : list[Token]
        The label's raw token slice (`CaseBranch.values[i]`), used by the fallback path.
    expr : Expression | None
        The label's parsed tree (`CaseBranch.values_expr[i]`), or `None`.
    string_constants : dict[str, int] | None
        Forwarded to :func:`render` and consulted directly for the symbolic-label ruling
        and the fallback path's own literal-text lookup.
    translator : StatementTranslator
        Shared translator instance, used by the fallback path only.

    Returns
    -------
    str
        The rendered Python text for this one label.
    """
    global _native_control_flow_renders, _fallback_control_flow_renders
    if expr is not None:
        if isinstance(expr, VariableRef) and not expr.is_local and not expr.is_absolute:
            quoted = f'"{expr.name}"'
            if string_constants and quoted in string_constants:
                _native_control_flow_renders += 1
                return str(string_constants[quoted])
        try:
            text = render(expr, string_constants)
        except UnsupportedExpression:
            pass
        else:
            _native_control_flow_renders += 1
            return text
    _fallback_control_flow_renders += 1
    label_text = scl_text(tokens)
    if string_constants and label_text in string_constants:
        return str(string_constants[label_text])
    return translator.expr_translator.translate(_map_string_constants(label_text, string_constants))


def generate_statements(
    statements: list[Statement],
    indent: int = 0,
    translator: StatementTranslator | None = None,
    string_constants: dict[str, int] | None = None,
) -> list[str]:
    """Generate Python lines for a list of statements.

    ``Assignment`` renders natively from ``target_expr``/``value_expr`` via
    :func:`render` -- see :func:`_generate_assignment` for the three cases that still
    fall back to the text dispatcher. ``If``/``For``/``While``/``Case`` headers render
    natively too -- a condition, a bound, a selector via
    :func:`_render_expression_or_fallback`, a ``Case`` label via
    :func:`_render_case_label` -- falling back to the text dispatcher on the same terms
    (no tree, or :func:`render` raises). ``Call``, ``Return`` and ``Exit`` are unchanged
    from :func:`_generate_statements_via_strings`: they still rebuild SCL text and hand
    it to ``StatementTranslator``. Replacing those is a later task in the same plan.

    Parameters
    ----------
    statements : list[Statement]
        The tree, as ``parse_statements`` returns it.
    indent : int
        Depth in four-space units. The caller splices the result into a class
        body, so the lines come back already indented.
    translator : StatementTranslator | None
        The translator to render expressions and simple statements with.
        Defaults to a fresh one; passed explicitly so a caller may share state
        across a whole block.
    string_constants : dict[str, int] | None
        Mapping from a quoted string literal (e.g. ``'"USER_FREEWHEEL"'``) to
        the integer value assigned to it, as collected by
        ``SCLTranspiler._collect_string_constants``. A literal that matches a
        CASE label is rendered as that bare integer; matching elsewhere it is
        rendered as ``self.NAME`` -- for ``Assignment`` this happens inside
        :func:`render` itself (see its own ``string_constants`` parameter) rather
        than through :func:`_map_string_constants`. ``None`` (the default) renders
        every string literal as itself.

    Returns
    -------
    list[str]
        Python lines, in source order.

    Raises
    ------
    UnsupportedStatement
        For a statement kind with no branch here.
    """
    translator = translator if translator is not None else StatementTranslator()
    prefix = INDENT * indent
    lines: list[str] = []

    for statement in statements:
        if isinstance(statement, Assignment):
            lines.extend(_generate_assignment(statement, prefix, translator, string_constants))
            continue

        if isinstance(statement, If):
            for position, branch in enumerate(statement.branches):
                keyword = "if" if position == 0 else "elif"
                condition = _render_expression_or_fallback(
                    branch.condition, branch.condition_expr, string_constants, translator
                )
                lines.append(f"{prefix}{keyword} {condition}:")
                lines.extend(_generate_body(branch.body, indent + 1, translator, string_constants))
            if statement.else_body:
                lines.append(f"{prefix}else:")
                lines.extend(_generate_body(statement.else_body, indent + 1, translator, string_constants))
            continue

        if isinstance(statement, For):
            variable_text = _map_string_constants(scl_text(statement.variable), string_constants)
            variable = translator.expr_translator.translate(variable_text)
            start = _render_expression_or_fallback(
                statement.start, statement.start_expr, string_constants, translator
            )
            end = _render_expression_or_fallback(
                statement.end, statement.end_expr, string_constants, translator
            )
            bounds = f"{start}, {end} + 1"
            if statement.step:
                step = _render_expression_or_fallback(
                    statement.step, statement.step_expr, string_constants, translator
                )
                bounds += f", {step}"
            lines.append(f"{prefix}for {variable} in range({bounds}):")
            lines.extend(_generate_body(statement.body, indent + 1, translator, string_constants))
            continue

        if isinstance(statement, While):
            condition = _render_expression_or_fallback(
                statement.condition, statement.condition_expr, string_constants, translator
            )
            lines.append(f"{prefix}while {condition}:")
            lines.extend(_generate_body(statement.body, indent + 1, translator, string_constants))
            continue

        if isinstance(statement, Case):
            selector = _render_expression_or_fallback(
                statement.selector, statement.selector_expr, string_constants, translator
            )
            for position, arm in enumerate(statement.branches):
                keyword = "if" if position == 0 else "elif"
                values = []
                for value_index, v in enumerate(arm.values):
                    value_expr = arm.values_expr[value_index] if value_index < len(arm.values_expr) else None
                    values.append(_render_case_label(v, value_expr, string_constants, translator))
                if len(values) == 1:
                    test = f"{selector} == {values[0]}"
                else:
                    test = f"{selector} in ({', '.join(values)})"
                lines.append(f"{prefix}{keyword} {test}:")
                lines.extend(_generate_body(arm.body, indent + 1, translator, string_constants))
            if statement.default:
                lines.append(f"{prefix}else:")
                lines.extend(_generate_body(statement.default, indent + 1, translator, string_constants))
            continue

        if isinstance(statement, Call):
            arguments = []
            for argument in statement.arguments:
                value = scl_text(argument.value)
                if not argument.name:
                    arguments.append(value)
                elif argument.is_output:
                    arguments.append(f"{argument.name} => {value}")
                else:
                    arguments.append(f"{argument.name} := {value}")
            call = _map_string_constants(
                f"{scl_text(statement.callee)} ( {' , '.join(arguments)} ) ;", string_constants
            )
            lines.extend(prefix + line for line in translator.translate_simple_statement(call))
            continue

        if isinstance(statement, Return):
            lines.extend(prefix + line for line in translator.translate_simple_statement("RETURN ;"))
            continue

        if isinstance(statement, Exit):
            lines.extend(prefix + line for line in translator.translate_simple_statement("EXIT ;"))
            continue

        raise UnsupportedStatement(f"{type(statement).__name__} at line {statement.line}")

    return lines
