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
`_generate_assignment`). The named-call-with-outputs shape `render` cannot
express (`#ret := "Block"(x := #a, out => #b)`) renders natively too, by a
different route (`_generate_named_call_assignment`, Task 8 -- see below). Two
conditions still fall back to the text dispatcher: a slice that failed to
parse, and any node `render` itself refuses (raises `UnsupportedExpression`
for).

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
-- there is no tree for it to render from.

`Call`, `Return` and `Exit` are rendered natively too (Task 8): `Return` and
`Exit` unconditionally (`_generate_return` / `_generate_exit` -- no tree is
involved, so there is nothing to fall back for), and `Call` by reading its
shape off `statement.callee_expr` (`_generate_call`) rather than re-parsing
rebuilt SCL text with `translate_simple_statement`'s regular expressions. An
FB instance call (`#instance(...)`) is reimplemented directly from the tree
(`_generate_fb_instance_call`), since `StatementTranslator.translate_fb_call`
is deleted in the next task; a quoted-block call statement (`"Block"(...)`)
instead calls `StatementTranslator._emit_named_call` directly
(`_generate_named_call_statement`), the same runtime-producing method the
dispatcher itself calls once its own regex has matched -- see
`_named_call_placeholder` for why every argument value still goes through
`render` rather than being handed to `_emit_named_call` as already-rendered
Python text. `Call` falls back on the same terms as `Assignment`: no tree (or
not a shape a statement callee can be), or `render` raising.

The body of a still-native `If`/`For`/`While`/`Case` recurses through
`generate_statements` itself (via `_generate_body`), so already renders any
nested `Assignment`, `Call`, `Return`, `Exit`, `If`, `For`, `While` or `Case`
it contains natively too.

`_generate_statements_via_strings` is the pre-Task-6 generator, kept alive
under a private name as the differential's "old" side (see
`tests/test_generator_native_differential.py`) until a later task deletes it.
For everything still routed through it -- an `Assignment`, header slice or
`Call` that falls back -- `StatementTranslator.translate_simple_statement` (for
`Assignment`/`Call`) or `StatementTranslator.translate_if_condition` /
`.expr_translator.translate` (for a fallen-back header slice) remain the
dispatch surface, unchanged from before Task 6.
"""

from __future__ import annotations

from collections import Counter

from plc_code.executor.codegen import StatementTranslator
from plc_code.executor.renderer import UnsupportedExpression, render
from plc_code.parser.expressions import Expression, FunctionCall, Member, VariableRef
from plc_code.parser.lexer import Token, TokenType
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


#: The `Call`/`Return`/`Exit` counterpart to the two pairs above -- same rationale, same
#: process-global/not-thread-safe caveat, same "never read directly outside this module"
#: rule. One pair for all three statement kinds (not split per kind, unlike the
#: control-flow pair): incremented once per `Call`/`Return`/`Exit` statement `generate_statements`
#: renders, native on every exit but a `Call` whose shape :func:`_generate_call` cannot
#: render from the tree. See :func:`reset_call_render_counters` / :func:`call_render_counts`.
_native_call_renders = 0
_fallback_call_renders = 0

#: Fix round 1 addition: `_fallback_call_renders` alone conflates every reason a `Call`
#: falls back into one number, which cannot tell "the paren-truncation guard fired" from
#: "the callee is not a simple statement callee" from "`render` raised". Keyed by a short
#: reason string (see :func:`_record_call_fallback`'s own call sites for the exact keys
#: in use), incremented alongside `_fallback_call_renders` at the same call sites, never
#: independently. See :func:`reset_call_render_counters` / :func:`call_fallback_reasons`.
_call_fallback_reasons: Counter[str] = Counter()


def reset_call_render_counters() -> None:
    """Reset the `Call`/`Return`/`Exit`-rendering counters (and reason breakdown) to zero.

    Call this immediately before the measurement whose native/fallback split you want to
    attribute, mirroring :func:`reset_assignment_render_counters` /
    :func:`reset_control_flow_render_counters` for `Call`/`Return`/`Exit` instead.
    """
    global _native_call_renders, _fallback_call_renders, _call_fallback_reasons
    _native_call_renders = 0
    _fallback_call_renders = 0
    _call_fallback_reasons = Counter()


def call_render_counts() -> tuple[int, int]:
    """The `Call`/`Return`/`Exit`-rendering counts accumulated since the last reset.

    Returns
    -------
    tuple[int, int]
        ``(native, fallback)`` -- how many `Call`/`Return`/`Exit` statements rendered
        from the tree versus fell back to the text dispatcher, since the last
        :func:`reset_call_render_counters` call (or process start, if never reset).
    """
    return _native_call_renders, _fallback_call_renders


def call_fallback_reasons() -> Counter[str]:
    """Why each `Call` fallback happened, accumulated since the last reset.

    A copy, not the live counter -- the caller cannot mutate module state through it.
    The keys in practice (see :func:`_record_call_fallback`'s call sites):
    ``"not_a_simple_callee"`` (`callee_expr` has no tree, is not a plain `VariableRef`,
    or is an absolute address -- :func:`_generate_call` itself), ``"closing_parenthesis"``
    (an FB-call argument's raw value contains a `)`, so `translate_fb_call`'s own
    paren-truncation is not attempted -- :func:`_generate_fb_instance_call`),
    ``"missing_argument_tree"`` (a named argument's `value_expr` is ``None`` -- either
    native renderer), and ``"unsupported_expression"`` (:func:`render` raised -- either
    native renderer). Every key's total sums to :func:`call_render_counts`'s fallback
    figure.

    Returns
    -------
    Counter[str]
        Reason -> count, since the last :func:`reset_call_render_counters` call (or
        process start, if never reset).
    """
    return Counter(_call_fallback_reasons)


def _record_call_fallback(reason: str) -> None:
    """Record one `Call` fallback's reason in :data:`_call_fallback_reasons`.

    Called once at each site that decides a `Call` cannot be rendered natively --
    :func:`_generate_call` itself (no usable callee shape) and each native renderer
    (:func:`_generate_named_call_statement`, :func:`_generate_fb_instance_call`) at
    every point it returns ``None``. Only records the reason; the caller is still
    responsible for :func:`_generate_call`'s own `_fallback_call_renders` increment
    and for actually falling back to :func:`_generate_call_via_dispatcher`.

    Parameters
    ----------
    reason : str
        A short, stable key -- see :func:`call_fallback_reasons` for the set in use.
    """
    global _call_fallback_reasons
    _call_fallback_reasons[reason] += 1


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
    separate statements. So :func:`render` alone cannot express an ``Assignment``
    whose right-hand side has this exact shape -- it renders natively by a different
    route instead (Task 8): :func:`_generate_named_call_assignment` calls
    ``StatementTranslator._emit_named_call`` directly, the same runtime-producing
    method ``_translate_named_call_assignment`` itself calls, with each argument's
    value taken from :func:`render` rather than re-derived from token text -- see
    :func:`_generate_assignment`, which only falls back to the dispatcher when that
    native call itself cannot proceed (a slice with no tree, or :func:`render`
    raising).

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


#: Mirrors ``renderer._IMPLICIT_BARE_NAME`` -- the one quoted name ``ExpressionTranslator``
#: and :func:`~plc_code.executor.renderer.render` both leave completely bare (neither
#: ``self.``-prefixed nor quoted). Duplicated here (not imported) because it is a single
#: literal and :func:`_is_write_back_candidate` needs to reject it the same way
#: ``renderer._render_variable_ref`` / ``_is_global_db_ref`` do, for the same reason.
_IMPLICIT_BARE_NAME = "ENO"


def _is_write_back_candidate(value_expr: Expression, string_constants: dict[str, int] | None) -> bool:
    """Whether ``_emit_named_call`` would treat a ``:=`` argument with this value as an in-out write-back.

    ``_emit_named_call`` decides this by testing its OWN translated text for the value --
    ``value_expr.startswith("self.") and " " not in value_expr.strip()`` -- computed from
    ``self.expr_translator.translate(value.strip())`` after the *whole* call text has
    already been through :func:`_map_string_constants` once (see
    :func:`_generate_call_via_dispatcher`). Probed directly against
    ``ExpressionTranslator.translate`` (with the same ``_map_string_constants`` pass
    applied first) to find every tree shape whose translated text is space-free -- there
    are exactly three, and nothing else, not even a one-level array index (``#a[1]``,
    which keeps ``" [ 1 ]"``'s spaces):

    1. A bare local variable, ``#name`` -- the ``#\\s+`` collapse turns ``"# name"`` into
       ``"self.name"``, with nothing left to keep a space around. Probed: ``"# a"`` ->
       ``"self.a"``.
    2. A bare *global* variable, ``"Name"``, whose quoted spelling is a
       ``string_constants`` key -- :func:`_map_string_constants` replaces the whole
       literal with ``" self.Name "`` (padded, but ``.strip()`` removes the padding, not
       an internal space) before ``translate`` ever runs. Probed:
       ``_map_string_constants('"Foo"', {'"Foo"': 1})`` -> ``" self.Foo "``.
    3. A *single* level of member access directly on a *plain* global DB reference,
       ``"Name" . member`` -- ``ExpressionTranslator``'s ``GLOBAL_DB_PATTERN``
       (``r'"(\\w+)"\\s*\\.\\s*(.+)'``) rewrites the whole ``"Name" . member`` run at once
       into ``self._runtime.global_dbs["Name"].member``, with no space introduced at the
       join. This is the mirror image of case 2, not an extension of it: the pattern's
       ``"(\\w+)"`` group requires ``Name`` to consist *only* of word characters (letters,
       digits, underscore) -- a hyphen, a space or anything else in the quoted name never
       matches, so ``"My-DB" . m`` is left completely untouched by ``translate`` (fixed in
       fix round 1: probed end to end on ``"Blk"(x := "My-DB".m);`` -- old dispatcher
       emits exactly one line, no write-back; the first version of this function wrongly
       returned True here, emitting a second, spurious write-back line the corpus
       differential's own per-slice attribution laundered away as an accepted
       ``GLOBAL_DB_PATTERN``-can't-match residual, since the *value itself* does render
       identically either way -- only the *extra statement* differs, which no
       argument-value slice comparison can see). A *second* level of member access
       (``"Name" . a . b``) is also NOT covered: only the first ``.member`` is absorbed by
       the pattern, and everything after it keeps its `scl_text` spaces untouched. Probed:
       ``'"Db" . a'`` -> ``'self._runtime.global_dbs["Db"].a'`` (no space) but
       ``'"Db" . a . b'`` -> ``'self._runtime.global_dbs["Db"].a . b'`` (space survives
       after the first hop) -- so this case requires the ``Member``'s own ``base`` to be
       the plain global ``VariableRef`` itself (not another ``Member``/``Index``), with a
       non-empty, all-word-character name that is not itself a mapped string constant
       (case 2's substitution takes priority over ``GLOBAL_DB_PATTERN``, mirroring
       ``renderer._is_global_db_ref``'s own ordering).

    Every other shape -- an index, an operator, a nested call, a literal, a member chain
    two or more levels deep, a member access on a global whose *own* quoted name contains
    a non-word character (case 3's exclusion above), a *quoted* global not in
    ``string_constants`` (renders quoted, e.g. ``'"Foo"'``, never ``self.``-prefixed) --
    keeps at least one `scl_text` space or never reaches ``"self."`` at all, and so is
    never a candidate.

    These three shapes are exactly what :func:`~plc_code.executor.renderer.render` itself
    also renders space-free and ``self.``-prefixed for (its ``_render_variable_ref`` /
    ``_render_member`` / ``_is_global_db_ref``) -- this function mirrors that same
    three-way split rather than re-deriving raw text or calling ``translate`` a second
    time on :func:`render`'s own output, which would risk the double-translation
    corruption :func:`_generate_named_call_statement` / :func:`_generate_named_call_assignment`
    use :func:`render` (via the placeholder trick) to avoid in the first place.

    A related divergence the reviewer found while auditing this function, noted rather
    than fixed because it is unreachable in the corpus: if a *quoted call's own callee*
    (not an argument value) happens to share its spelling with a ``string_constants``
    key, ``_generate_call_via_dispatcher``'s ``_map_string_constants`` pass mangles the
    callee text itself before ``_translate_named_block_call``'s own
    ``^"([^"]+)"\\s*\\(`` match ever runs -- the leading quote is gone, the match fails,
    and the whole statement falls through to being treated as something else entirely,
    not a call. This module's native path has no such failure mode (the callee is read
    from ``callee_expr`` directly, never re-matched against quoted text), so the two
    sides would disagree if the same name were ever used as both a callable block name
    and a declared symbolic constant -- a shape no corpus block does.

    Also note (not a change here): ``_emit_named_call``'s own per-parameter loop
    classifies a parameter as input/output purely by testing whether the literal
    substrings ``":="``/``"=>"`` occur in its text -- a *positional* (unnamed) argument
    whose own value happens to contain one of those substrings (e.g. nested inside a
    further quoted call) can be miscategorised by that loop. This module never triggers
    it: positional arguments are never placed into ``params_str`` in the first place (see
    :func:`_generate_named_call_statement`), so the quirk is ``_emit_named_call``'s own
    and pre-existing, not something this function's callers can reach.

    Parameters
    ----------
    value_expr : Expression
        The argument's parsed value (never ``None`` -- the caller has already checked).
    string_constants : dict[str, int] | None
        The same mapping :func:`render` and :func:`_map_string_constants` use.

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


def _named_call_placeholder(index: int, use_self_prefix: bool) -> str:
    """An inert placeholder token standing in for one ``:=``/``=>`` argument's rendered value.

    Shared by every caller of ``StatementTranslator._emit_named_call`` /
    ``_build_named_call`` in this module (:func:`_generate_named_call_assignment`,
    :func:`_generate_named_call_statement`) -- both methods re-translate whatever text
    they are given for a value (``self.expr_translator.translate(value.strip())``), so
    handing them the value's already-rendered Python text (e.g. ``"math.sqrt(self.x)"``)
    directly would corrupt it exactly as :func:`~plc_code.executor.renderer._render_named_call`'s
    own docstring documents for ``_build_named_call`` (probed there: ``translate`` doubles
    ``math.sqrt(...)`` to ``math.math.sqrt(...)``) -- ``_emit_named_call`` calls the same
    ``translate`` on the same kind of text and is exposed to the same risk. A bare
    ``__ARGVAL<n>__`` token is untouched by every substitution ``translate`` performs
    (probed directly, same as the renderer's own placeholder), so the caller substitutes
    the real value back in once ``_emit_named_call`` has returned its lines.

    ``_emit_named_call`` has one behaviour ``_build_named_call`` does not: for a ``:=``
    (non-output) argument, it decides whether to also emit an in-out write-back line by
    testing the *translated* value text itself (see :func:`_is_write_back_candidate`).
    ``use_self_prefix`` carries that verdict in, computed by the caller from the tree
    rather than from this function's placeholder text -- a bare placeholder never starts
    with ``"self."``, so using one unconditionally would always suppress the write-back,
    silently dropping it whenever the real value is the common in-out shape
    (:func:`_is_write_back_candidate` True). ``translate`` leaves the prefixed form
    untouched too (probed), so ``_emit_named_call`` sees exactly the verdict the caller
    computed, before the placeholder is substituted back out.

    Parameters
    ----------
    index : int
        This argument's position, keeping every placeholder in one call unique.
    use_self_prefix : bool
        The caller's precomputed verdict -- True only for a ``:=`` (non-output) argument
        whose value is :func:`_is_write_back_candidate`.

    Returns
    -------
    str
        ``f"self.__ARGVAL{index}__"`` when ``use_self_prefix``; ``f"__ARGVAL{index}__"``
        otherwise.
    """
    return f"self.__ARGVAL{index}__" if use_self_prefix else f"__ARGVAL{index}__"


def _substitute_named_call_placeholders(lines: list[str], placeholders: dict[str, str]) -> list[str]:
    """Replace every :func:`_named_call_placeholder` token in ``lines`` with its real value.

    Parameters
    ----------
    lines : list[str]
        Python lines returned by ``StatementTranslator._emit_named_call``.
    placeholders : dict[str, str]
        Placeholder token -> the argument's real :func:`render` output.

    Returns
    -------
    list[str]
        ``lines`` with every placeholder token replaced by its mapped value. Distinct
        indices never collide (each token embeds its own ``<n>``), so plain sequential
        ``str.replace`` calls are safe regardless of order.
    """
    for token, value in placeholders.items():
        lines = [line.replace(token, value) for line in lines]
    return lines


def _generate_named_call_assignment(
    statement: Assignment,
    translator: StatementTranslator,
    string_constants: dict[str, int] | None,
) -> list[str] | None:
    """Native lines for ``#ret := "Block"(x := #a, out => #b)`` -- the Task 6 dispatcher-routed shape.

    Calls ``StatementTranslator._emit_named_call`` directly (the same runtime-producing
    method ``_translate_named_call_assignment`` itself calls), with every argument value
    and the assignment target taken from :func:`render` via the
    :func:`_named_call_placeholder` trick, then appends the return-value line exactly as
    ``_translate_named_call_assignment`` does: ``f'{target} = {result_var}["{block_name}"]'``
    -- keyed by the callee's own name, not the argument named ``"out"`` (probed and
    confirmed against ``test_generator_statements.py::test_an_assignment_from_a_named_call_with_outputs``).

    Parameters
    ----------
    statement : Assignment
        The assignment to generate; ``statement.value_expr`` must already be known to
        satisfy :func:`_is_named_call_with_output_binding` (the caller's job).
    translator : StatementTranslator
        Shared translator instance; only ``_emit_named_call`` is used.
    string_constants : dict[str, int] | None
        Forwarded to every :func:`render` call.

    Returns
    -------
    list[str] | None
        The rendered lines (unindented -- the caller prefixes them), or ``None`` when
        ``statement.target_expr`` is ``None`` or :func:`render` raises
        :class:`~plc_code.executor.renderer.UnsupportedExpression` for the target or any
        named argument -- signalling the caller to fall back to the dispatcher.
    """
    node = statement.value_expr
    assert isinstance(node, FunctionCall)
    if statement.target_expr is None:
        return None
    placeholders: dict[str, str] = {}
    bound_arguments: list[str] = []
    for index, argument in enumerate(node.arguments):
        if not argument.name:
            continue
        try:
            value_text = render(argument.value, string_constants)
        except UnsupportedExpression:
            return None
        use_self_prefix = not argument.is_output and _is_write_back_candidate(
            argument.value, string_constants
        )
        token = _named_call_placeholder(index, use_self_prefix)
        placeholders[token] = value_text
        name_text = f'"{argument.name}"' if argument.is_quoted_name else argument.name
        direction = "=>" if argument.is_output else ":="
        bound_arguments.append(f"{name_text} {direction} {token}")
    try:
        target_text = render(statement.target_expr, string_constants)
    except UnsupportedExpression:
        return None
    lines, result_var = translator._emit_named_call(node.name, ", ".join(bound_arguments))  # noqa: SLF001
    lines = list(lines)
    lines.append(f'{target_text} = {result_var}["{node.name}"]')
    return _substitute_named_call_placeholders(lines, placeholders)


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
    the value is a named-call-with-outputs (see :func:`_is_named_call_with_output_binding`),
    in which case :func:`_generate_named_call_assignment` is tried instead -- both are
    native, but reach a Python line by a different route, since :func:`render` alone
    cannot express a call statement's ``=>`` write-backs (see that function's own
    docstring). Either native attempt falls back to
    :func:`_generate_assignment_via_dispatcher` -- the same text-rewriting path
    :func:`_generate_statements_via_strings` uses for every ``Assignment`` -- on:

    1. ``statement.target_expr`` or ``statement.value_expr`` is ``None`` (the slice
       failed to parse as an expression) -- there is no tree to render.
    2. :func:`render` (or, for the named-call-with-outputs shape,
       :func:`_generate_named_call_assignment`'s own use of it) raises
       :class:`~plc_code.executor.renderer.UnsupportedExpression` for either side -- a
       node the renderer has no visitor for (or refuses to render, e.g. a bare builtin
       call binding an output). Rather than enumerating every such shape by hand, any
       node the tree alone cannot render falls back.

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
        named_call_lines = _generate_named_call_assignment(statement, translator, string_constants)
        if named_call_lines is None:
            _fallback_assignment_renders += 1
            return _generate_assignment_via_dispatcher(statement, prefix, translator, string_constants)
        _native_assignment_renders += 1
        return [prefix + line for line in named_call_lines]
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


#: An FB instance name substring that makes :func:`_generate_fb_instance_call` add a
#: trailing ``clock=self._runtime.clock`` argument -- copied verbatim from
#: ``StatementTranslator.translate_fb_call``'s own ``any(timer_type in
#: instance_name.lower() for timer_type in [...])`` check, which this function
#: reproduces rather than calls (Task 9 deletes ``translate_fb_call``; see
#: :func:`_generate_call`'s own docstring).
_TIMER_INSTANCE_MARKERS = ("timer", "ton", "tof", "tp")


def _generate_call_via_dispatcher(
    statement: Call,
    prefix: str,
    translator: StatementTranslator,
    string_constants: dict[str, int] | None,
) -> list[str]:
    """One ``Call``'s lines via the text dispatcher -- the fallback native rendering cannot take.

    Reuses exactly the shape ``_generate_statements_via_strings`` builds: rebuild the
    SCL call text from the token slices, map string constants over it, and hand it to
    ``StatementTranslator.translate_simple_statement`` -- the same three-way dispatch
    (``#instance(...)``, ``"Block"(...)``, or neither) that function performs by
    re-parsing the text with regular expressions, since :func:`_generate_call` could not
    determine (or could not render) the shape from the tree alone.

    Parameters
    ----------
    statement : Call
        The call to generate.
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
    return [prefix + line for line in translator.translate_simple_statement(call)]


def _generate_named_call_statement(
    statement: Call,
    translator: StatementTranslator,
    string_constants: dict[str, int] | None,
) -> list[str] | None:
    """Native lines for a quoted-block call statement (``"Block"(x := #a, out => #b);``).

    Calls ``StatementTranslator._emit_named_call`` directly -- the same runtime-producing
    method ``StatementTranslator._translate_named_block_call`` itself calls after its own
    regex-based paren matching -- with every argument value taken from :func:`render` via
    the :func:`_named_call_placeholder` trick. The result-dict variable
    ``_emit_named_call`` also returns is discarded, matching
    ``_translate_named_block_call``'s own ``self._emit_named_call(block_name,
    params_str)[0]`` -- a standalone call statement never reads the block's return value.

    Parameters
    ----------
    statement : Call
        The call to generate; ``statement.callee_expr`` must already be known to be a
        quoted (``is_local=False``, ``is_absolute=False``) ``VariableRef`` (the caller's
        job, in :func:`_generate_call`).
    translator : StatementTranslator
        Shared translator instance; only ``_emit_named_call`` is used.
    string_constants : dict[str, int] | None
        Forwarded to every :func:`render` call.

    Returns
    -------
    list[str] | None
        The rendered lines (unindented -- the caller prefixes them), or ``None`` when
        any named argument's ``value_expr`` is ``None`` or :func:`render` raises
        :class:`~plc_code.executor.renderer.UnsupportedExpression` -- signalling the
        caller to fall back to the dispatcher.
    """
    assert isinstance(statement.callee_expr, VariableRef)
    block_name = statement.callee_expr.name
    placeholders: dict[str, str] = {}
    bound_arguments: list[str] = []
    for index, argument in enumerate(statement.arguments):
        if not argument.name:
            continue
        if argument.value_expr is None:
            _record_call_fallback("missing_argument_tree")
            return None
        try:
            value_text = render(argument.value_expr, string_constants)
        except UnsupportedExpression:
            _record_call_fallback("unsupported_expression")
            return None
        use_self_prefix = not argument.is_output and _is_write_back_candidate(
            argument.value_expr, string_constants
        )
        token = _named_call_placeholder(index, use_self_prefix)
        placeholders[token] = value_text
        direction = "=>" if argument.is_output else ":="
        bound_arguments.append(f"{argument.name} {direction} {token}")
    lines, _result_var = translator._emit_named_call(block_name, ", ".join(bound_arguments))  # noqa: SLF001
    return _substitute_named_call_placeholders(list(lines), placeholders)


def _has_closing_parenthesis(tokens: list[Token]) -> bool:
    r"""Whether ``tokens`` contains a ``)`` character anywhere -- as its own token, or inside a string.

    ``StatementTranslator.translate_fb_call``'s own regex (``r"#(\w+)\s*\(([^)]*)\)"``)
    captures an FB call's parameter list only up to the FIRST ``)`` character found
    anywhere after the opening one -- it runs on the fully rebuilt call *text*, blind to
    token boundaries, so it truncates on a ``)`` regardless of what produced it. Two
    distinct sources both trip it, and this checks for both:

    * A grouped sub-expression or a nested function call inside any argument's value
      (``(#a == #b)``, ``ABS(#x)``) -- an ``RPAREN`` token. Probed directly against the
      corpus: an ``IN``/``PT`` pair where ``IN``'s value is a grouped comparison loses
      ``PT`` entirely and ends mid-expression.
    * A string literal argument value whose own contents include a ``)`` character --
      one ``STRING`` token, no ``RPAREN`` token at all, yet the same truncation happens
      because the regex has no concept of "inside a string". Probed (fix round 1):
      ``#tmr(IN := 'a)b', PT := #t);`` -> old dispatcher:
      ``["self.tmr(IN='a)"]`` (truncated mid-literal, ``PT`` gone); a first version of
      this predicate looked only at ``RPAREN`` and missed this case entirely, so the
      native path rendered the call whole while the dispatcher fallback -- had it been
      taken -- would not have matched. Checking each ``STRING`` token's own text (not a
      regex: a plain ``in`` substring test) closes that gap.

    :func:`_generate_fb_instance_call` does not attempt to reproduce either truncation
    from the tree -- see its own docstring -- so this flags the shape up front and lets
    :func:`_generate_call` fall back to the dispatcher instead, which reproduces the bug
    byte for byte (it calls the very same ``translate_fb_call``).

    Parameters
    ----------
    tokens : list[Token]
        One argument's raw token slice.

    Returns
    -------
    bool
        True when any token in ``tokens`` is a closing parenthesis, or is a string
        literal whose own text contains a ``)`` character.
    """
    for token in tokens:
        if token.type is TokenType.RPAREN:
            return True
        if token.type is TokenType.STRING and ")" in token.value:
            return True
    return False


def _generate_fb_instance_call(
    statement: Call,
    string_constants: dict[str, int] | None,
) -> list[str] | None:
    """Native lines for an FB instance call (``#instance(...)``), reproducing ``translate_fb_call``.

    Task 9 deletes ``StatementTranslator.translate_fb_call``, so this does not call it --
    it reimplements the same rule directly from the tree instead of re-parsing rebuilt SCL
    text with regular expressions: a positional (unnamed) argument is dropped in either
    direction (mirrors ``translate_fb_call``'s own per-param ``":=" in param`` / ``"=>" in
    param`` check, which a bare value text never satisfies), a ``:=`` argument becomes
    ``name=value`` in the call's keyword arguments, an ``=>`` argument becomes a trailing
    ``target = self.instance.name`` line, and an instance name containing ``"timer"``,
    ``"ton"``, ``"tof"`` or ``"tp"`` (case-insensitively) gets a trailing
    ``clock=self._runtime.clock`` keyword argument -- see :data:`_TIMER_INSTANCE_MARKERS`.
    Each argument's value comes from :func:`render`, not ``translate_fb_call``'s
    text-based ``ExpressionTranslator.translate`` -- a divergence between the two is an
    expression-level residual, attributed the same way every other native renderer's is.

    Unlike ``translate_fb_call``, this never re-parses the callee itself with a regex, so
    it has no equivalent of that function's own silent no-match fallback (a callee like
    ``#arr[1](...)`` or ``#a.b(...)``, which the regex ``#(\\w+)\\s*\\(`` cannot match
    either): :func:`_generate_call` never calls this function for such a callee in the
    first place, since ``callee_expr`` for either shape parses to an ``Index``/``Member``
    node, not a plain ``VariableRef`` -- see that function's own docstring. It also refuses
    -- returns ``None``, the same fallback signal as any other case here -- when any
    argument's raw value contains a closing parenthesis (see
    :func:`_has_closing_parenthesis`): reproducing ``translate_fb_call``'s own
    paren-truncation bug from the tree is not attempted, so this shape defers to the
    dispatcher instead of silently rendering something more correct than the byte-identity
    bar allows.

    Parameters
    ----------
    statement : Call
        The call to generate; ``statement.callee_expr`` must already be known to be a
        local (``is_local=True``) ``VariableRef`` (the caller's job, in
        :func:`_generate_call`).
    string_constants : dict[str, int] | None
        Forwarded to every :func:`render` call.

    Returns
    -------
    list[str] | None
        The rendered lines (unindented -- the caller prefixes them), or ``None`` when a
        named argument's ``value_expr`` is ``None``, any argument's raw value contains a
        closing parenthesis, or :func:`render` raises
        :class:`~plc_code.executor.renderer.UnsupportedExpression` -- signalling the
        caller to fall back to the dispatcher.
    """
    assert isinstance(statement.callee_expr, VariableRef)
    if any(_has_closing_parenthesis(argument.value) for argument in statement.arguments):
        _record_call_fallback("closing_parenthesis")
        return None
    instance_name = statement.callee_expr.name
    input_params: list[str] = []
    output_assignments: list[str] = []
    for argument in statement.arguments:
        if not argument.name:
            continue
        if argument.value_expr is None:
            _record_call_fallback("missing_argument_tree")
            return None
        try:
            value_text = render(argument.value_expr, string_constants)
        except UnsupportedExpression:
            _record_call_fallback("unsupported_expression")
            return None
        if argument.is_output:
            output_assignments.append(f"{value_text} = self.{instance_name}.{argument.name}")
        else:
            input_params.append(f"{argument.name}={value_text}")
    call_params = ", ".join(input_params)
    if any(marker in instance_name.lower() for marker in _TIMER_INSTANCE_MARKERS):
        call_params = (
            f"{call_params}, clock=self._runtime.clock" if call_params else "clock=self._runtime.clock"
        )
    return [f"self.{instance_name}({call_params})", *output_assignments]


def _generate_call(
    statement: Call,
    prefix: str,
    translator: StatementTranslator,
    string_constants: dict[str, int] | None,
) -> list[str]:
    """One ``Call``'s Python line(s): rendered natively from the tree, or via the dispatcher.

    ``translate_simple_statement`` tells apart three shapes by re-parsing rebuilt SCL
    text with regular expressions; this reads the same distinction straight off
    ``statement.callee_expr`` instead:

    * ``callee_expr`` is a ``VariableRef`` with ``is_local`` True (``#instance``) -- an FB
      instance call, rendered by :func:`_generate_fb_instance_call`.
    * ``callee_expr`` is a ``VariableRef`` with neither ``is_local`` nor ``is_absolute``
      (``"Block"``) -- a quoted-block call statement, rendered by
      :func:`_generate_named_call_statement`.
    * Anything else -- ``callee_expr`` is ``None`` (the slice failed to parse, or parsed
      to something no statement callee can be, e.g. a bare unquoted, unprefixed name such
      as a builtin call used as a statement), a ``VariableRef`` with ``is_absolute`` True,
      or any other node type (``Member``/``Index`` for a dotted or indexed callee, e.g.
      ``#a.b(...)`` or ``#arr[1](...)`` -- probed directly: neither parses to a
      ``VariableRef``) -- falls back to :func:`_generate_call_via_dispatcher`, the same
      text-rewriting path :func:`_generate_statements_via_strings` uses for every
      ``Call``.

    Either native renderer returning ``None`` (a named argument with no tree, or
    :func:`render` raising :class:`~plc_code.executor.renderer.UnsupportedExpression``,
    or -- FB calls only -- a closing parenthesis in an argument's raw value) also falls
    back; each such renderer records its own reason via :func:`_record_call_fallback`
    before returning, so this function only needs to record its own ("no usable callee
    shape") when it never reaches a renderer at all -- see :func:`call_fallback_reasons`
    for the full reason set.

    Every call increments exactly one of :data:`_native_call_renders` /
    :data:`_fallback_call_renders` (see :func:`reset_call_render_counters` /
    :func:`call_render_counts`), the shared counter pair for ``Call``, ``Return`` and
    ``Exit`` -- see :func:`_generate_return` / :func:`_generate_exit`.

    Parameters
    ----------
    statement : Call
        The call to generate.
    prefix : str
        Indentation to prepend to the emitted line(s).
    translator : StatementTranslator
        Shared translator instance, forwarded to the dispatcher fallback and to
        :func:`_generate_named_call_statement`.
    string_constants : dict[str, int] | None
        Forwarded to :func:`render` (native path) or the dispatcher fallback unchanged;
        see :func:`generate_statements`.

    Returns
    -------
    list[str]
        The rendered lines (native or dispatcher), each already prefixed with ``prefix``.
    """
    global _native_call_renders, _fallback_call_renders
    callee_expr = statement.callee_expr
    lines: list[str] | None = None
    if isinstance(callee_expr, VariableRef) and not callee_expr.is_absolute:
        if callee_expr.is_local:
            lines = _generate_fb_instance_call(statement, string_constants)
        else:
            lines = _generate_named_call_statement(statement, translator, string_constants)
    else:
        _record_call_fallback("not_a_simple_callee")
    if lines is None:
        _fallback_call_renders += 1
        return _generate_call_via_dispatcher(statement, prefix, translator, string_constants)
    _native_call_renders += 1
    return [prefix + line for line in lines]


def _generate_return(prefix: str) -> list[str]:
    """One ``Return`` statement's Python line -- always native, no tree involved.

    Probed directly (see :func:`generate_statements`'s own docstring):
    ``StatementTranslator().translate_simple_statement("RETURN ;") == ["return"]`` for
    every input, so there is nothing to fall back for -- every call counts as native.

    Parameters
    ----------
    prefix : str
        Indentation to prepend to the emitted line.

    Returns
    -------
    list[str]
        ``[f"{prefix}return"]``.
    """
    global _native_call_renders
    _native_call_renders += 1
    return [f"{prefix}return"]


def _generate_exit(prefix: str) -> list[str]:
    """One ``Exit`` statement's Python line -- always native, no tree involved.

    Probed directly: ``StatementTranslator().translate_simple_statement("EXIT ;") ==
    ["break"]`` for every input, so there is nothing to fall back for -- every call
    counts as native. See :func:`_generate_return`.

    Parameters
    ----------
    prefix : str
        Indentation to prepend to the emitted line.

    Returns
    -------
    list[str]
        ``[f"{prefix}break"]``.
    """
    global _native_call_renders
    _native_call_renders += 1
    return [f"{prefix}break"]


def generate_statements(
    statements: list[Statement],
    indent: int = 0,
    translator: StatementTranslator | None = None,
    string_constants: dict[str, int] | None = None,
) -> list[str]:
    """Generate Python lines for a list of statements.

    ``Assignment`` renders natively from ``target_expr``/``value_expr`` via
    :func:`render` -- see :func:`_generate_assignment` for the cases that still fall
    back to the text dispatcher. ``If``/``For``/``While``/``Case`` headers render
    natively too -- a condition, a bound, a selector via
    :func:`_render_expression_or_fallback`, a ``Case`` label via
    :func:`_render_case_label` -- falling back to the text dispatcher on the same terms
    (no tree, or :func:`render` raises). ``Call``, ``Return`` and ``Exit`` render
    natively too (see :func:`_generate_call` / :func:`_generate_return` /
    :func:`_generate_exit`); ``Return``/``Exit`` always do, and ``Call`` falls back on
    the same terms as ``Assignment``.

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
            lines.extend(_generate_call(statement, prefix, translator, string_constants))
            continue

        if isinstance(statement, Return):
            lines.extend(_generate_return(prefix))
            continue

        if isinstance(statement, Exit):
            lines.extend(_generate_exit(prefix))
            continue

        raise UnsupportedStatement(f"{type(statement).__name__} at line {statement.line}")

    return lines
