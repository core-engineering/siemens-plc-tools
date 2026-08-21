"""Python generation from the statement AST.

The executor used to rewrite SCL as text: `ControlFlowTranslator` split a
region's flattened content on newlines and matched control-flow keywords with
regular expressions, so anything it did not recognise was copied verbatim into
the generated Python while `transpile_block` reported success. This module reads
the statement tree instead, and a construct it cannot generate raises rather
than emitting nothing.

It does not translate expressions. For each statement it rebuilds the SCL string
the text path would have handed to `ExpressionTranslator` / `StatementTranslator`
/ `ControlFlowTranslator` and calls those same methods, so the two paths agree
byte for byte by construction rather than by re-derivation. Replacing them is
pass 2.

Every non-control-flow statement (`Assignment`, `Call`, `Return`, `Exit`) is
routed through `ControlFlowTranslator._translate_simple_statement`, the text
path's own single entry point for such lines: it is where RETURN/EXIT, the
quoted-name block call, compound assignment, the named-call-with-outputs
special case, the `#name(...)` FB call and the bare-expression fallback are
actually dispatched, in that order. Calling a leading-underscore method from
here is deliberate — reusing the text path's real dispatcher, rather than
re-deriving a subset of its cases (as an earlier version of this module did
by calling `translate_fb_call` directly), is what makes the two paths agree
on constructs like a quoted-name call. A later task relocates that method;
this module should follow it when it moves.
"""

from __future__ import annotations

from plc_code.executor.codegen import StatementTranslator
from plc_code.executor.control_flow import ControlFlowTranslator
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


def generate_statements(
    statements: list[Statement],
    indent: int = 0,
    translator: StatementTranslator | None = None,
    control_flow: ControlFlowTranslator | None = None,
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
        The translator to render expressions with. Defaults to a fresh one;
        passed explicitly so a caller may share state across a whole block.
    control_flow : ControlFlowTranslator | None
        The text path's translator, used only for its
        ``_translate_simple_statement`` entry point (assignment, call, RETURN,
        EXIT). Defaults to a fresh one; passed explicitly so a caller may share
        state across a whole block, the same way ``translator`` is.

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
    control_flow = control_flow if control_flow is not None else ControlFlowTranslator()
    prefix = INDENT * indent
    lines: list[str] = []

    for statement in statements:
        if isinstance(statement, Assignment):
            text = f"{scl_text(statement.target)} := {scl_text(statement.value)} ;"
            lines.extend(prefix + line for line in control_flow._translate_simple_statement(text))
            continue

        if isinstance(statement, If):
            for position, branch in enumerate(statement.branches):
                keyword = "if" if position == 0 else "elif"
                condition = translator.translate_if_condition(scl_text(branch.condition))
                lines.append(f"{prefix}{keyword} {condition}:")
                lines.extend(generate_statements(branch.body, indent + 1, translator, control_flow))
            if statement.else_body:
                lines.append(f"{prefix}else:")
                lines.extend(generate_statements(statement.else_body, indent + 1, translator, control_flow))
            continue

        if isinstance(statement, For):
            variable = translator.expr_translator.translate(scl_text(statement.variable))
            start = translator.expr_translator.translate(scl_text(statement.start))
            end = translator.expr_translator.translate(scl_text(statement.end))
            bounds = f"{start}, {end} + 1"
            if statement.step:
                bounds += f", {translator.expr_translator.translate(scl_text(statement.step))}"
            lines.append(f"{prefix}for {variable} in range({bounds}):")
            lines.extend(generate_statements(statement.body, indent + 1, translator, control_flow))
            continue

        if isinstance(statement, While):
            condition = translator.translate_if_condition(scl_text(statement.condition))
            lines.append(f"{prefix}while {condition}:")
            lines.extend(generate_statements(statement.body, indent + 1, translator, control_flow))
            continue

        if isinstance(statement, Case):
            selector = translator.expr_translator.translate(scl_text(statement.selector))
            for position, arm in enumerate(statement.branches):
                keyword = "if" if position == 0 else "elif"
                values = [translator.expr_translator.translate(scl_text(v)) for v in arm.values]
                if len(values) == 1:
                    test = f"{selector} == {values[0]}"
                else:
                    test = f"{selector} in ({', '.join(values)})"
                lines.append(f"{prefix}{keyword} {test}:")
                lines.extend(generate_statements(arm.body, indent + 1, translator, control_flow))
            if statement.default:
                lines.append(f"{prefix}else:")
                lines.extend(generate_statements(statement.default, indent + 1, translator, control_flow))
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
            call = f"{scl_text(statement.callee)} ( {' , '.join(arguments)} ) ;"
            lines.extend(prefix + line for line in control_flow._translate_simple_statement(call))
            continue

        if isinstance(statement, Return):
            lines.extend(prefix + line for line in control_flow._translate_simple_statement("RETURN ;"))
            continue

        if isinstance(statement, Exit):
            lines.extend(prefix + line for line in control_flow._translate_simple_statement("EXIT ;"))
            continue

        raise UnsupportedStatement(f"{type(statement).__name__} at line {statement.line}")

    return lines
