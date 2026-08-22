"""Python generation from the statement AST.

The executor used to rewrite SCL as text: a now-deleted ``ControlFlowTranslator``
split a region's flattened content on newlines and matched control-flow
keywords with regular expressions, so anything it did not recognise was copied
verbatim into the generated Python while ``transpile_block`` reported success.
This module reads the statement tree instead, and a construct it cannot
generate raises rather than emitting nothing.

`Assignment` is now rendered natively: `generate_statements` calls
`plc_code.executor.renderer.render` directly on `target_expr`/`value_expr`
rather than rebuilding SCL text and handing it to a translator (see
`_generate_assignment`). Three shapes still fall back to the text dispatcher
-- a slice that failed to parse, the named-call-with-outputs shape `render`
cannot express (`#ret := "Block"(x := #a, out => #b)`), and any node `render`
itself refuses (raises `UnsupportedExpression` for). Every other statement kind
(`If`, `For`, `While`, `Case`, `Call`, `Return`, `Exit`) still rebuilds the SCL
string and hands it to `ExpressionTranslator` / `StatementTranslator`, the same
translators the deleted text path used -- replacing those is a later task in
the same plan.

`_generate_statements_via_strings` is the pre-this-task generator, kept alive
under a private name as the differential's "old" side (see
`tests/test_generator_native_differential.py`) until a later task deletes it.
For everything still routed through it -- every non-`Assignment` statement,
and an `Assignment` that falls back -- `StatementTranslator.translate_simple_statement`
remains the statement-level dispatcher: RETURN/EXIT, the quoted-name block
call, compound assignment, the named-call-with-outputs special case, the
`#name(...)` FB call and the bare-expression fallback are dispatched there, in
that order.
"""

from __future__ import annotations

from plc_code.executor.codegen import StatementTranslator
from plc_code.executor.renderer import UnsupportedExpression, render
from plc_code.parser.expressions import Expression, FunctionCall
from plc_code.parser.lexer import Token
from plc_code.parser.statements import Assignment, Call, Case, Exit, For, If, Return, Statement, While

INDENT = "    "


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
    if statement.target_expr is None or statement.value_expr is None:
        return _generate_assignment_via_dispatcher(statement, prefix, translator, string_constants)
    if _is_named_call_with_output_binding(statement.value_expr):
        return _generate_assignment_via_dispatcher(statement, prefix, translator, string_constants)
    try:
        target_text = render(statement.target_expr, string_constants)
        value_text = render(statement.value_expr, string_constants)
    except UnsupportedExpression:
        return _generate_assignment_via_dispatcher(statement, prefix, translator, string_constants)
    return [f"{prefix}{target_text} = {value_text}"]


def generate_statements(
    statements: list[Statement],
    indent: int = 0,
    translator: StatementTranslator | None = None,
    string_constants: dict[str, int] | None = None,
) -> list[str]:
    """Generate Python lines for a list of statements.

    ``Assignment`` renders natively from ``target_expr``/``value_expr`` via
    :func:`render` -- see :func:`_generate_assignment` for the three cases that still
    fall back to the text dispatcher. Every other statement kind (``If``, ``For``,
    ``While``, ``Case``, ``Call``, ``Return``, ``Exit``) is unchanged from
    :func:`_generate_statements_via_strings`: it still rebuilds SCL text and hands it
    to ``StatementTranslator``. Replacing those is a later task in the same plan.

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
                condition_text = _map_string_constants(scl_text(branch.condition), string_constants)
                condition = translator.translate_if_condition(condition_text)
                lines.append(f"{prefix}{keyword} {condition}:")
                lines.extend(_generate_body(branch.body, indent + 1, translator, string_constants))
            if statement.else_body:
                lines.append(f"{prefix}else:")
                lines.extend(_generate_body(statement.else_body, indent + 1, translator, string_constants))
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
            lines.extend(_generate_body(statement.body, indent + 1, translator, string_constants))
            continue

        if isinstance(statement, While):
            condition_text = _map_string_constants(scl_text(statement.condition), string_constants)
            condition = translator.translate_if_condition(condition_text)
            lines.append(f"{prefix}while {condition}:")
            lines.extend(_generate_body(statement.body, indent + 1, translator, string_constants))
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
