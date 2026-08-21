"""Python generation from the statement AST.

The executor used to rewrite SCL as text: a now-deleted ``ControlFlowTranslator``
split a region's flattened content on newlines and matched control-flow
keywords with regular expressions, so anything it did not recognise was copied
verbatim into the generated Python while ``transpile_block`` reported success.
This module reads the statement tree instead, and a construct it cannot
generate raises rather than emitting nothing.

It does not translate expressions. For each statement it rebuilds the SCL
string and hands it to `ExpressionTranslator` / `StatementTranslator`, the same
translators the deleted text path used, so expression rendering itself is
unchanged by this switch. Replacing them is pass 2.

Every non-control-flow statement (`Assignment`, `Call`, `Return`, `Exit`) is
routed through `StatementTranslator.translate_simple_statement`, the
statement-level dispatcher: it is where RETURN/EXIT, the quoted-name block
call, compound assignment, the named-call-with-outputs special case, the
`#name(...)` FB call and the bare-expression fallback are actually dispatched,
in that order.
"""

from __future__ import annotations

from plc_code.executor.codegen import StatementTranslator
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


def _generate_body(
    statements: list[Statement],
    indent: int,
    translator: StatementTranslator,
    string_constants: dict[str, int] | None,
) -> list[str]:
    """Generate a nested body's lines, padding with ``pass`` when it is empty.

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


def generate_statements(
    statements: list[Statement],
    indent: int = 0,
    translator: StatementTranslator | None = None,
    string_constants: dict[str, int] | None = None,
) -> list[str]:
    """Generate Python lines for a list of statements.

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
