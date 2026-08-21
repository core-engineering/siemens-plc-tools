"""Render Python source directly from the SCL expression tree.

The executor used to rewrite SCL expressions as text through twelve ordered regex
passes with placeholder protection, and every silent corruption that produced was
fixed by adding another pass: ``16#8201`` read as an instance variable until hex
literals got their own pass, a string literal rewritten as code until literals were
protected behind placeholders, and so on. This renders from the tree instead of the
text, so there is no ordering between passes to get wrong and no text a later pass
can still mangle. A node this module has no visitor for raises
:class:`UnsupportedExpression` rather than emitting something plausible.

This module covers ``Literal``, ``TypedLiteral``, ``VariableRef``, ``Member``,
``Index`` and ``Grouping`` -- the access and literal shapes
``plc_code.parser.expressions`` documents as dominating the corpus.  ``UnaryOp``,
``BinaryOp`` and ``FunctionCall`` are later tasks in the same plan (operators, then
calls); :func:`render` raises :class:`UnsupportedExpression` for those today.
"""

from __future__ import annotations

from plc_code.executor.types import parse_time_literal
from plc_code.parser.expressions import (
    Expression,
    Grouping,
    Index,
    Literal,
    Member,
    TypedLiteral,
    VariableRef,
)

#: Duration-literal prefixes, matched case-insensitively: ``T#``, ``TIME#``, ``LT#``,
#: ``LTIME#``. ``ExpressionTranslator._translate_time_literals`` collapses all four to
#: ``T#`` before calling ``parse_time_literal`` -- the runtime stores every duration as
#: a float number of seconds regardless of which keyword wrote it -- so this does the
#: same rather than branching on which one matched.
_DURATION_PREFIXES = frozenset({"T", "TIME", "LT", "LTIME"})

#: The one identifier SCL reads bare and unquoted despite carrying
#: ``VariableRef.is_local=False``: a function block's own ``ENO`` output. See
#: ``plc_code.parser.expression_parser._IMPLICIT_VARIABLES``, which is the only member
#: of that set. Nothing in the tree marks *why* a non-local ``VariableRef`` was
#: unquoted rather than a quoted global -- ``ENO`` is the only real-world case, so it is
#: matched by name.
_IMPLICIT_BARE_NAME = "ENO"


class UnsupportedExpression(Exception):
    """Raised by :func:`render` for an expression node with no visitor.

    Attributes
    ----------
    node : object
        The value :func:`render` was asked to render and did not recognize.
    """

    def __init__(self, node: object) -> None:
        super().__init__(f"no renderer for {type(node).__name__}")
        self.node = node


def render(expression: Expression) -> str:
    """Render one expression node as Python source.

    Dispatches on ``expression``'s runtime type. There is no fallback branch: a node
    this function does not recognize raises rather than emitting text that merely
    looks plausible.

    Parameters
    ----------
    expression : Expression
        A node from :mod:`plc_code.parser.expressions`.

    Returns
    -------
    str
        The equivalent Python expression text.

    Raises
    ------
    UnsupportedExpression
        ``expression`` is not one of the node types this function currently renders.
    """
    if isinstance(expression, Literal):
        return _render_literal(expression)
    if isinstance(expression, TypedLiteral):
        return _render_typed_literal(expression)
    if isinstance(expression, VariableRef):
        return _render_variable_ref(expression)
    if isinstance(expression, Member):
        return _render_member(expression)
    if isinstance(expression, Index):
        return _render_index(expression)
    if isinstance(expression, Grouping):
        return f"({render(expression.inner)})"
    raise UnsupportedExpression(expression)


def _render_literal(node: Literal) -> str:
    """A number exactly as written, or a boolean spelled the Python way.

    Parameters
    ----------
    node : Literal
        The literal to render.

    Returns
    -------
    str
        ``"True"``/``"False"`` for a boolean spelling (any case); ``node.value``
        unchanged otherwise -- SCL numeric literals (``1.5``, ``-1``, ...) are already
        valid Python.
    """
    upper = node.value.upper()
    if upper == "TRUE":
        return "True"
    if upper == "FALSE":
        return "False"
    return node.value


def _render_typed_literal(node: TypedLiteral) -> str:
    """``16#FF`` as a lowercase Python hex literal; a duration as seconds.

    Structural equivalents of ``ExpressionTranslator._translate_hex_literals`` and
    ``_translate_time_literals`` -- the only two prefixes the current translator
    gives real meaning to. Every other prefix found in the corpus (``B#16#FF``,
    ``REAL#1000.0``, ...) is out of scope here: the current translator's own output
    for those is already not valid Python -- see this task's report -- so there is
    nothing correct to reproduce.

    Parameters
    ----------
    node : TypedLiteral
        The typed literal to render.

    Returns
    -------
    str
        A Python hex literal or a ``float`` repr in seconds.

    Raises
    ------
    UnsupportedExpression
        ``node.prefix`` is neither a hex marker nor a duration marker.
    """
    prefix = node.prefix.upper()
    if prefix == "16":
        return hex(int(node.value, 16))
    if prefix in _DURATION_PREFIXES:
        return repr(parse_time_literal(f"T#{node.value}"))
    raise UnsupportedExpression(node)


def _render_variable_ref(node: VariableRef) -> str:
    """``#name`` as an instance attribute; ``%name`` and a quoted global as-is.

    Parameters
    ----------
    node : VariableRef
        The variable reference to render.

    Returns
    -------
    str
        ``self.{name}`` for a local (``#name``); ``%{name}`` unchanged for an
        absolute address (``%name``); the bare name for ``ENO``; ``"{name}"``
        (quoted) for any other global, matching what the current translator leaves
        untouched when a quoted name is not immediately followed by ``.member``
        (``GLOBAL_DB_PATTERN`` requires the dot; ``Member`` handles that case, not
        this function).
    """
    if node.is_local:
        return f"self.{node.name}"
    if node.is_absolute:
        return f"%{node.name}"
    if node.name.upper() == _IMPLICIT_BARE_NAME:
        return node.name
    return f'"{node.name}"'


def _is_global_db_ref(node: Expression) -> bool:
    """Whether ``node`` is the bare quoted global a ``Member`` base substitutes for.

    Parameters
    ----------
    node : Expression
        A ``Member``'s ``base``.

    Returns
    -------
    bool
        True for a ``VariableRef`` that is neither local (``#name``) nor absolute
        (``%name``) nor the bare ``ENO`` -- i.e. one that renders quoted, as
        ``ExpressionTranslator.GLOBAL_DB_PATTERN`` requires (a literal ``"name"``
        immediately followed by ``.``).
    """
    return (
        isinstance(node, VariableRef)
        and not node.is_local
        and not node.is_absolute
        and node.name.upper() != _IMPLICIT_BARE_NAME
    )


def _render_member(node: Member) -> str:
    """``base.name``, substituting the runtime lookup for a bare global base.

    Structural equivalent of ``ExpressionTranslator._translate_global_db``: when the
    base is a bare quoted global (see :func:`_is_global_db_ref`), it renders through
    ``self._runtime.global_dbs[...]`` instead of through :func:`_render_variable_ref`,
    exactly as the current translator's ``GLOBAL_DB_PATTERN`` substitutes there. Any
    other base -- local, absolute, or itself a ``Member``/``Index``/``Grouping`` --
    renders through :func:`render` normally.

    Parameters
    ----------
    node : Member
        The member access to render.

    Returns
    -------
    str
        ``{base}.{name}`` for a plain member; ``{base}.self.{name}`` when the member
        was written ``.#name``; ``{base}.%{name}`` when written ``.%name``;
        ``{base}."{name}"`` when written ``."name"``.
    """
    if _is_global_db_ref(node.base):
        assert isinstance(node.base, VariableRef)  # narrowed by _is_global_db_ref
        base_text = f'self._runtime.global_dbs["{node.base.name}"]'
    else:
        base_text = render(node.base)

    if node.is_local:
        return f"{base_text}.self.{node.name}"
    if node.is_absolute:
        return f"{base_text}.%{node.name}"
    if node.is_quoted:
        return f'{base_text}."{node.name}"'
    return f"{base_text}.{node.name}"


def _render_index(node: Index) -> str:
    """``base[i]`` for one subscript; ``base[i, j]`` chained as ``base[i][j]``.

    Structural equivalent of ``ExpressionTranslator._translate_multi_index``: the base
    renders through :func:`render` unchanged (a quoted global base is not substituted
    here -- only ``Member`` does that, matching ``GLOBAL_DB_PATTERN``'s requirement of
    a literal ``.`` after the quoted name), and every subscript becomes its own
    bracket pair, in source order.

    Parameters
    ----------
    node : Index
        The indexing operation to render.

    Returns
    -------
    str
        The base followed by one ``[...]`` per entry in ``node.indices``.
    """
    base_text = render(node.base)
    return base_text + "".join(f"[{render(index)}]" for index in node.indices)
