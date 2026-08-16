"""Detect SCL constructs the transpiler does not actually support.

Why this exists
---------------
The executor translates SCL by rewriting text: there is no statement-level AST.
``ControlFlowTranslator._translate_statements`` dispatches on a handful of
leading keywords, and everything else falls through to
``_translate_simple_statement``, whose last branch hands the line to the
expression translator and emits whatever comes back. A construct the translator
has never heard of is therefore not rejected — it is copied into the generated
Python and ``transpile_block`` returns ``success=True`` with no errors and no
warnings.

That is how ``REPEAT``/``UNTIL``, ``GOTO``, ``CONTINUE`` and unmapped builtins
such as ``SEL`` or ``LIMIT`` reach a downstream project: they surface as a
``SyntaxError`` when the block is compiled, or a ``NameError`` the first time
the branch is taken — a long way from the SCL that caused them.

How it works
------------
Rather than trying to prove something about the SCL, these checks look at the
*generated Python*, where the damage is mechanically visible:

``CODE_TRANSPILE``
    Transpilation itself reported a failure. Already produced today, never
    surfaced to a user.
``CODE_SYNTAX``
    The generated module does not parse. The block cannot load at all, so this
    is an error.
``CODE_UNDEFINED_NAME``
    The generated module reads a global that neither it nor the runtime
    namespace provides. Raises ``NameError`` when that line runs, so it is a
    warning: harmless until the branch is taken.

Scope analysis uses :mod:`symtable` — CPython's own resolver — rather than a
hand-rolled AST walk, because getting comprehensions, walrus targets, ``global``
declarations and nested functions right by hand is exactly the kind of subtlety
that makes a checker noisy. Names bound at module scope (the generated code
imports ``math`` and the runtime helpers itself) are subtracted, as are builtins
and the keys of :func:`plc_code.executor.transpiler.build_runtime_globals`.

What it does not catch
----------------------
Anything that produces valid Python referencing only defined names but means the
wrong thing — a corrupted string literal, a dropped ``=>`` output. Those need
semantic knowledge of the SCL, which is the AST work this module is explicitly
not doing.
"""

from __future__ import annotations

import ast
import builtins
import symtable
from dataclasses import dataclass
from pathlib import Path

from plc_core.reporting import Severity

from plc_code.executor.models import TranspileOptions
from plc_code.executor.transpiler import build_runtime_globals, transpile_block
from plc_code.parser.models import Block

#: Transpilation reported its own failure.
CODE_TRANSPILE = "TRANSPILE"
#: The generated Python does not parse.
CODE_SYNTAX = "SYNTAX"
#: The generated Python reads a name nothing provides.
CODE_UNDEFINED_NAME = "UNDEFINED_NAME"


@dataclass(frozen=True)
class Diagnostic:
    """One problem found in a block's generated Python.

    Attributes
    ----------
    block_name : str
        Name of the SCL block the code was generated from.
    code : str
        One of :data:`CODE_TRANSPILE`, :data:`CODE_SYNTAX`,
        :data:`CODE_UNDEFINED_NAME`.
    severity : Severity
        ``ERROR`` when the block cannot load at all, ``WARNING`` when it loads
        but will fail if the offending line runs.
    message : str
        Human-readable description, naming the offending symbol where there is
        one.
    line : int | None
        1-based line in the *generated Python*, not in the SCL source.
    generated_line : str
        The generated line itself, stripped. Empty when there is no single
        line to point at.
    source_file : Path | None
        The ``.s7dcl`` the block came from, when the caller knows it.
    """

    block_name: str
    code: str
    severity: Severity
    message: str
    line: int | None = None
    generated_line: str = ""
    source_file: Path | None = None


def _module_bound_names(table: symtable.SymbolTable) -> set[str]:
    """Names the generated module binds for itself at module scope.

    Generated code emits its own ``import math`` and
    ``from plc_code.executor.runtime import _clone_value, ...``. Seen from
    inside a method those read as unassigned globals, so they must be
    subtracted using the *module* scope's view, not each nested scope's.
    """
    bound: set[str] = set()
    for symbol in table.get_symbols():
        if symbol.is_assigned() or symbol.is_imported():
            bound.add(symbol.get_name())
    return bound


def _referenced_globals(table: symtable.SymbolTable) -> set[str]:
    """Every name read as a global, across the module and all nested scopes."""
    referenced: set[str] = set()
    for symbol in table.get_symbols():
        if symbol.is_referenced() and symbol.is_global():
            referenced.add(symbol.get_name())
    for child in table.get_children():
        referenced |= _referenced_globals(child)
    return referenced


def _first_use_lines(tree: ast.AST, names: set[str]) -> dict[str, tuple[int, str]]:
    """Map each name to the line number of its first load.

    ``symtable`` knows which names are unresolved but not where they appear, so
    the location comes from a matching pass over the AST.
    """
    found: dict[str, tuple[int, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        if node.id in names and node.id not in found:
            found[node.id] = (node.lineno, "")
    return found


def _line_at(source: str, lineno: int | None) -> str:
    """Return the stripped source line, or empty when out of range."""
    if lineno is None:
        return ""
    lines = source.splitlines()
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].strip()
    return ""


def check_block(
    block: Block,
    *,
    source_file: Path | None = None,
    options: TranspileOptions | None = None,
) -> list[Diagnostic]:
    """Transpile ``block`` and report what is wrong with the generated Python.

    Parameters
    ----------
    block : Block
        Parsed SCL block.
    source_file : Path | None
        Recorded on every diagnostic so a caller can attribute findings across
        a whole project.
    options : TranspileOptions | None
        Passed straight through to :func:`transpile_block`.

    Returns
    -------
    list[Diagnostic]
        Empty when the generated Python parses and resolves. Ordered: transpile
        failures, then the syntax error, then undefined names by first use.
    """
    block_name = block.name or ""
    result = transpile_block(block, options)

    if not result.success or result.errors:
        return [
            Diagnostic(
                block_name=block_name,
                code=CODE_TRANSPILE,
                severity=Severity.ERROR,
                message=message,
                source_file=source_file,
            )
            for message in (result.errors or ["Transpilation failed"])
        ]

    code = result.python_code

    try:
        tree = ast.parse(code)
        table = symtable.symtable(code, "<generated>", "exec")
    except SyntaxError as exc:
        return [
            Diagnostic(
                block_name=block_name,
                code=CODE_SYNTAX,
                severity=Severity.ERROR,
                message=f"generated Python does not parse: {exc.msg}",
                line=exc.lineno,
                generated_line=_line_at(code, exc.lineno),
                source_file=source_file,
            )
        ]

    provided = _module_bound_names(table) | set(build_runtime_globals()) | set(dir(builtins))
    unresolved = _referenced_globals(table) - provided
    if not unresolved:
        return []

    locations = _first_use_lines(tree, unresolved)
    diagnostics = [
        Diagnostic(
            block_name=block_name,
            code=CODE_UNDEFINED_NAME,
            severity=Severity.WARNING,
            message=f"reads {name!r}, which nothing defines (NameError when this line runs)",
            line=locations.get(name, (None, ""))[0],
            generated_line=_line_at(code, locations.get(name, (None, ""))[0]),
            source_file=source_file,
        )
        for name in sorted(unresolved, key=lambda n: (locations.get(n, (10**9, ""))[0], n))
    ]
    return diagnostics
