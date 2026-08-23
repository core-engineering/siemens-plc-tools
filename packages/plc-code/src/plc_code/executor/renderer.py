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
``Index``, ``Grouping``, ``UnaryOp``, ``BinaryOp`` and ``FunctionCall`` -- every
expression node ``plc_code.parser.expressions`` defines.

``FunctionCall`` comes in two unrelated shapes. A bare builtin (``is_quoted=False``,
e.g. ``ABS(#x)``) maps through :data:`_BUILTIN_MAP`, the same table
the old text translator's ``_translate_builtins`` pass used, with ``LOWER_BOUND``/``UPPER_BOUND``
singled out the same way its ``_translate_array_bounds`` pass singled
them out -- see :func:`_render_builtin_call`. A quoted block call (``is_quoted=True``,
e.g. ``"Scaling"(input := #x)``) renders through
``ExpressionTranslator._build_named_call`` itself rather than a structural copy of
it -- see :func:`_render_named_call`, which passes each argument's already-rendered
value to it directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from plc_code.executor.arguments import PositionalBindingError, SignatureResolver, positional_parameter_names
from plc_code.executor.codegen import BUILTIN_MAP, OPERATOR_MAP, ExpressionTranslator
from plc_code.executor.types import parse_time_literal
from plc_code.parser.expressions import (
    BinaryOp,
    Expression,
    FunctionCall,
    Grouping,
    Index,
    Literal,
    Member,
    TypedLiteral,
    UnaryOp,
    VariableRef,
)

#: A live instance whose only use here is calling ``_build_named_call`` for a quoted
#: block call -- see :func:`_render_named_call`. ``translate``/``_build_named_call``
#: depend only on their arguments, not on any state accumulated across calls, so one
#: shared instance is safe to reuse for that rather than constructing one per call.
_TRANSLATOR = ExpressionTranslator()

#: ``codegen.OPERATOR_MAP``, imported directly now that it is a module-level constant
#: rather than a dataclass field -- so this module's operator table cannot drift from
#: the regex translator's.
_OPERATOR_MAP = OPERATOR_MAP

#: ``codegen.BUILTIN_MAP``, imported the same way as :data:`_OPERATOR_MAP` and for the
#: same reason -- so this module's builtin table cannot drift from the regex
#: translator's.
_BUILTIN_MAP = BUILTIN_MAP

#: The two builtins the old text translator's ``_translate_array_bounds`` pass rewrote through
#: its own regex instead of the generic ``_translate_builtins`` substitution -- see
#: :func:`_is_array_bound_call`.
_ARRAY_BOUND_BUILTINS = frozenset({"LOWER_BOUND", "UPPER_BOUND"})

#: Binary operators the old text translator left exactly as written -- their SCL
#: spelling is already valid Python -- because they carried no entry in
#: ``OPERATOR_MAP``. ``&`` belongs here, not mapped to ``and``: see the module
#: docstring and :func:`_render_binary_op`.
_PASSTHROUGH_BINARY_OPERATORS = frozenset({"&", "+", "-", "*", "/", "<", ">", "<=", ">=", "**"})

#: Duration-literal prefixes, matched case-insensitively: ``T#``, ``TIME#``, ``LT#``,
#: ``LTIME#``. The old text translator's ``_translate_time_literals`` pass collapsed all four to
#: ``T#`` before calling ``parse_time_literal`` -- the runtime stores every duration as
#: a float number of seconds regardless of which keyword wrote it -- so this does the
#: same rather than branching on which one matched.
_DURATION_PREFIXES = frozenset({"T", "TIME", "LT", "LTIME"})

#: Elementary SCL type names that only ever wrap a *size*, never a value syntax of
#: their own -- unlike ``DATE#``, ``CHAR#``, ``S5T#``, .... Python has no distinct
#: byte/word/dword/sized-numeric literal syntax, so a chained or bare literal under
#: one of these (``B#16#FF``, ``REAL#1000.0``) renders as whatever is underneath the
#: prefix, stripped -- see :func:`_render_typed_literal`.
_SIZE_PREFIXES = frozenset(
    {
        "B",
        "BYTE",
        "W",
        "WORD",
        "DW",
        "DWORD",
        "LW",
        "LWORD",
        "BOOL",
        "SINT",
        "INT",
        "DINT",
        "LINT",
        "USINT",
        "UINT",
        "UDINT",
        "ULINT",
        "REAL",
        "LREAL",
    }
)

#: The one identifier SCL reads bare and unquoted despite carrying
#: ``VariableRef.is_local=False``: a function block's own ``ENO`` output. See
#: ``plc_code.parser.expression_parser._IMPLICIT_VARIABLES``, which is the only member
#: of that set. Nothing in the tree marks *why* a non-local ``VariableRef`` was
#: unquoted rather than a quoted global -- ``ENO`` is the only real-world case, so it is
#: matched by name.
_IMPLICIT_BARE_NAME = "ENO"


class UnsupportedExpression(Exception):
    """Raised by :func:`render` for a node it has no visitor for, or one it has a
    visitor for but refuses to render because the result would run without error and
    still be wrong -- see :func:`_render_builtin_call`'s output-binding check.

    Attributes
    ----------
    node : object
        The value :func:`render` was asked to render and either did not recognize or
        recognized and refused.
    line : int | None
        ``node``'s own source line, or ``None`` when ``node`` carries none -- see the
        :attr:`line` property.
    """

    def __init__(self, node: object, message: str | None = None) -> None:
        super().__init__(message if message is not None else f"no renderer for {type(node).__name__}")
        self.node = node

    @property
    def line(self) -> int | None:
        """The source line ``self.node`` carries, or ``None`` when it has none.

        Every ``Expression`` subtype :func:`render` can raise this for carries a
        ``line`` field; read via ``getattr`` rather than a type-narrowed access
        because ``node`` is typed as ``object`` (this exception's own contract does
        not require an ``Expression`` specifically). Consulted by
        ``SCLTranspiler.transpile``'s top-level exception handler so a raised
        ``UnsupportedExpression`` still produces a located
        ``TranspileProblem.source_line``, not ``None``.
        """
        line = getattr(self.node, "line", None)
        return line if isinstance(line, int) else None


@dataclass(frozen=True)
class _Context:
    """What every visitor needs besides the node: carried by the recursion, built once.

    Attributes
    ----------
    string_constants : dict[str, int] | None
        See :func:`render`.
    signature_resolver : SignatureResolver | None
        See :func:`render`.
    """

    string_constants: dict[str, int] | None
    signature_resolver: SignatureResolver | None


def render(
    expression: Expression,
    string_constants: dict[str, int] | None = None,
    signature_resolver: SignatureResolver | None = None,
) -> str:
    """Render one expression node as Python source.

    Dispatches on ``expression``'s runtime type. There is no fallback branch: a node
    this function does not recognize raises rather than emitting text that merely
    looks plausible.

    Parameters
    ----------
    expression : Expression
        A node from :mod:`plc_code.parser.expressions`.
    string_constants : dict[str, int] | None, optional
        Mapping from a quoted string-constant literal (e.g. ``'"USER_FREEWHEEL"'``,
        quotes included) to the integer value assigned to it, as collected by
        ``SCLTranspiler._collect_string_constants``. A non-local, non-absolute
        :class:`~plc_code.parser.expressions.VariableRef` whose quoted spelling is a
        key of this table renders as ``self.NAME`` instead of the quoted literal it
        would otherwise render as -- see :func:`_render_variable_ref`. A CASE label
        is not affected by this parameter; that substitution (a matching literal
        becomes its bare integer) is a different mapping, applied by the generator
        directly, not by this function. ``None`` (the default) renders every
        non-local global as a quoted literal, unconditionally.
    signature_resolver : SignatureResolver | None, optional
        Resolves a quoted block name to its declared input parameter names in order,
        so a positional argument in a call to that block can be bound to the right
        one. ``None`` means no project context: a call with positional arguments
        then raises rather than dropping them, which is what the old text path did
        silently. A call with only named arguments never consults it.

    Returns
    -------
    str
        The equivalent Python expression text.

    Raises
    ------
    UnsupportedExpression
        ``expression`` is not one of the node types this function currently renders.
    """
    return _render(expression, _Context(string_constants, signature_resolver))


def _render(expression: Expression, ctx: _Context) -> str:
    """Dispatch on the node type with the context already built."""
    if isinstance(expression, Literal):
        return _render_literal(expression)
    if isinstance(expression, TypedLiteral):
        return _render_typed_literal(expression)
    if isinstance(expression, VariableRef):
        return _render_variable_ref(expression, ctx)
    if isinstance(expression, Member):
        return _render_member(expression, ctx)
    if isinstance(expression, Index):
        return _render_index(expression, ctx)
    if isinstance(expression, Grouping):
        return f"({_render(expression.inner, ctx)})"
    if isinstance(expression, UnaryOp):
        return _render_unary_op(expression, ctx)
    if isinstance(expression, BinaryOp):
        return _render_binary_op(expression, ctx)
    if isinstance(expression, FunctionCall):
        return _render_function_call(expression, ctx)
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
    """``16#FF`` as a lowercase Python hex literal; a duration as seconds; a chain resolved.

    Structural equivalent of the old text translator's ``_translate_hex_literals`` pass and
    ``_translate_time_literals`` for the ``16``/duration prefixes, plus a case those
    have no equivalent for: a *chained* literal like ``B#16#FF`` (byte, hexadecimal,
    ``FF``) or a bare-value one like ``REAL#1000.0``. The text path throws the type
    information away before it can help -- probed directly, ``translate("B#16#FF")``
    returns ``'bself.0xff'`` (the ``B`` glued onto the value as if it were an
    identifier) and ``translate("#a := B#16#FF")`` returns ``'self.a == bself.0xff'``
    (the assignment has become a comparison too) -- so there is nothing correct to be
    equivalent to there. The tree still has ``TypedLiteral(prefix="B", value="16#FF")``
    intact, which is enough: a size prefix in :data:`_SIZE_PREFIXES` carries no value
    of its own -- Python has no distinct byte/word/dword literal syntax -- so it is
    stripped and the rest of ``node.value`` is rendered instead, recursively when that
    rest is itself chained (``value`` still contains a ``#``) and through
    :func:`_render_literal` when it is not (``REAL#1000.0``'s ``"1000.0"`` is already
    a valid Python float literal). A prefix that carries its own value syntax instead
    of a mere size -- ``DATE#``, ``CHAR#``, ``S5T#``, ... -- is not in
    :data:`_SIZE_PREFIXES` and still raises: there is no equivalent Python literal to
    strip down to, and guessing one is not this function's job.

    Parameters
    ----------
    node : TypedLiteral
        The typed literal to render.

    Returns
    -------
    str
        A Python hex literal, a ``float`` repr in seconds, or (for a stripped size
        prefix) whatever :func:`_render_typed_literal` or :func:`_render_literal`
        returns for the value underneath it.

    Raises
    ------
    UnsupportedExpression
        ``node.prefix`` is neither a hex marker, a duration marker, nor a size
        prefix in :data:`_SIZE_PREFIXES`.
    """
    prefix = node.prefix.upper()
    if prefix == "16":
        return hex(int(node.value, 16))
    if prefix in _DURATION_PREFIXES:
        return repr(parse_time_literal(f"T#{node.value}"))
    if prefix in _SIZE_PREFIXES:
        inner_prefix, separator, inner_value = node.value.partition("#")
        if separator:
            return _render_typed_literal(TypedLiteral(node.line, node.column, inner_prefix, inner_value))
        return _render_literal(Literal(node.line, node.column, node.value))
    raise UnsupportedExpression(node)


def _render_variable_ref(node: VariableRef, ctx: _Context) -> str:
    """``#name`` as an instance attribute; ``%name`` and a quoted global as-is.

    Parameters
    ----------
    node : VariableRef
        The variable reference to render.
    ctx : _Context
        See :func:`render`. When ``node`` is a non-local, non-absolute, non-``ENO``
        global and its quoted spelling (``f'"{node.name}"'``) is a key of this
        table, it renders as ``self.{name}`` instead of the quoted literal.

    Returns
    -------
    str
        ``self.{name}`` for a local (``#name``) or a mapped string constant;
        ``%{name}`` unchanged for an absolute address (``%name``); the bare name
        for ``ENO``; ``"{name}"`` (quoted) for any other global, matching what the
        old text translator left untouched when a quoted name was not immediately
        followed by ``.member`` (its ``GLOBAL_DB_PATTERN`` regex required the dot; ``Member``
        handles that case, not this function).
    """
    if node.is_local:
        return f"self.{node.name}"
    if node.is_absolute:
        return f"%{node.name}"
    if node.name.upper() == _IMPLICIT_BARE_NAME:
        return node.name
    quoted = f'"{node.name}"'
    if ctx.string_constants and quoted in ctx.string_constants:
        return f"self.{node.name}"
    return quoted


def _is_global_db_ref(node: Expression, string_constants: dict[str, int] | None = None) -> bool:
    """Whether ``node`` is the bare quoted global a ``Member`` base substitutes for.

    Parameters
    ----------
    node : Expression
        A ``Member``'s ``base``.
    string_constants : dict[str, int] | None, optional
        See :func:`render`. A ``VariableRef`` whose quoted spelling is a key of
        this table is a mapped string constant, not a global DB, and returns
        False here -- the substitution in :func:`_render_variable_ref` takes
        priority.

    Returns
    -------
    bool
        True for a ``VariableRef`` that is neither local (``#name``) nor absolute
        (``%name``) nor the bare ``ENO`` nor a mapped string constant -- i.e. one
        that renders quoted, as a bare quoted global followed by ``.member`` requires.
    """
    if not (
        isinstance(node, VariableRef)
        and not node.is_local
        and not node.is_absolute
        and node.name.upper() != _IMPLICIT_BARE_NAME
    ):
        return False
    if string_constants and f'"{node.name}"' in string_constants:
        return False
    return True


def _render_member(node: Member, ctx: _Context) -> str:
    """``base.name``, substituting the runtime lookup for a bare global base.

    Structural equivalent of the old text translator's ``_translate_global_db`` pass: when the
    base is a bare quoted global (see :func:`_is_global_db_ref`), it renders through
    ``self._runtime.global_dbs[...]`` instead of through :func:`_render_variable_ref`,
    exactly as the old text translator's ``GLOBAL_DB_PATTERN`` regex substituted there. Any
    other base -- local, absolute, a mapped string constant, or itself a
    ``Member``/``Index``/``Grouping`` -- renders through :func:`render` normally.

    Parameters
    ----------
    node : Member
        The member access to render.
    ctx : _Context
        See :func:`render`. Forwarded to :func:`_is_global_db_ref` and to the
        base's own render.

    Returns
    -------
    str
        ``{base}.{name}`` for a plain member; ``{base}.self.{name}`` when the member
        was written ``.#name``; ``{base}.%{name}`` when written ``.%name``;
        ``{base}."{name}"`` when written ``."name"``.
    """
    if _is_global_db_ref(node.base, ctx.string_constants):
        assert isinstance(node.base, VariableRef)  # narrowed by _is_global_db_ref
        base_text = f'self._runtime.global_dbs["{node.base.name}"]'
    else:
        base_text = _render(node.base, ctx)

    if node.is_local:
        return f"{base_text}.self.{node.name}"
    if node.is_absolute:
        return f"{base_text}.%{node.name}"
    if node.is_quoted:
        return f'{base_text}."{node.name}"'
    return f"{base_text}.{node.name}"


def _render_index(node: Index, ctx: _Context) -> str:
    """``base[i]`` for one subscript; ``base[i, j]`` chained as ``base[i][j]``.

    Structural equivalent of the old text translator's ``_translate_multi_index`` pass: the base
    renders through :func:`render` unchanged (a quoted global base is not substituted
    here -- only ``Member`` does that, matching the old text translator's ``GLOBAL_DB_PATTERN``
    regex's requirement of
    a literal ``.`` after the quoted name), and every subscript becomes its own
    bracket pair, in source order.

    Parameters
    ----------
    node : Index
        The indexing operation to render.
    ctx : _Context
        See :func:`render`. Forwarded to every recursive render of the base and
        each subscript.

    Returns
    -------
    str
        The base followed by one ``[...]`` per entry in ``node.indices``.
    """
    base_text = _render(node.base, ctx)
    return base_text + "".join(f"[{_render(index, ctx)}]" for index in node.indices)


def _render_unary_op(node: UnaryOp, ctx: _Context) -> str:
    """``NOT x`` as ``not x``; ``-x`` unchanged, both with a space after the operator.

    Structural equivalent of the old text translator's ``_translate_operators`` pass: ``NOT``
    is looked up in :data:`_OPERATOR_MAP` (``"not"``); ``-`` has no entry there
    because its SCL and Python spellings are identical, so it renders as-is. Either
    way the old text translator's regex passes always left a space between the
    operator and its operand, so this does too.

    Parameters
    ----------
    node : UnaryOp
        The unary operator to render.
    ctx : _Context
        See :func:`render`. Forwarded to the operand's render.

    Returns
    -------
    str
        ``"not"`` or ``"-"``, a space, then the rendered operand.

    Raises
    ------
    UnsupportedExpression
        ``node.operator`` is neither ``NOT`` nor ``-``.
    """
    if node.operator in _OPERATOR_MAP:
        py_operator = _OPERATOR_MAP[node.operator]
    elif node.operator == "-":
        py_operator = "-"
    else:
        raise UnsupportedExpression(node)
    return f"{py_operator} {_render(node.operand, ctx)}"


def _render_binary_op(node: BinaryOp, ctx: _Context) -> str:
    """One binary operator between its rendered operands.

    Structural equivalent of the old text translator's ``_translate_operators`` pass: looks
    ``node.operator`` up in :data:`_OPERATOR_MAP` first (``AND``, ``OR``, ``<>``,
    ``MOD``, ``DIV``), then falls back to the standalone-``=`` rule the old text
    translator applied with its own regex rather than through ``OPERATOR_MAP``
    (``=`` becomes ``==``), then to :data:`_PASSTHROUGH_BINARY_OPERATORS` for
    everything the old text translator left exactly as written -- including
    ``&``, which stays ``&`` rather than becoming ``and``: see the module
    docstring.

    Parameters
    ----------
    node : BinaryOp
        The binary operator to render.
    ctx : _Context
        See :func:`render`. Forwarded to both operands' render.

    Returns
    -------
    str
        The left operand, the Python spelling of the operator, and the right
        operand, each separated by a single space.

    Raises
    ------
    UnsupportedExpression
        ``node.operator`` has no entry in :data:`_OPERATOR_MAP`, is not ``=``, and
        is not one of :data:`_PASSTHROUGH_BINARY_OPERATORS`.
    """
    if node.operator == "=":
        py_operator = "=="
    elif node.operator in _OPERATOR_MAP:
        py_operator = _OPERATOR_MAP[node.operator]
    elif node.operator in _PASSTHROUGH_BINARY_OPERATORS:
        py_operator = node.operator
    else:
        raise UnsupportedExpression(node)
    return f"{_render(node.left, ctx)} {py_operator} {_render(node.right, ctx)}"


def _render_function_call(node: FunctionCall, ctx: _Context) -> str:
    """Dispatch a call node to its builtin or quoted-block renderer.

    Parameters
    ----------
    node : FunctionCall
        The call to render.
    ctx : _Context
        See :func:`render`. Forwarded to whichever renderer handles the call.

    Returns
    -------
    str
        The rendered call, from :func:`_render_named_call` when ``node.is_quoted``,
        from :func:`_render_builtin_call` otherwise.
    """
    if node.is_quoted:
        return _render_named_call(node, ctx)
    return _render_builtin_call(node, ctx)


def _is_array_bound_call(node: FunctionCall) -> bool:
    """Whether ``node`` matches the exact shape ``_translate_array_bounds`` rewrites.

    That pass's regex requires exactly two arguments, bound by the bare (unquoted)
    names ``ARR`` and ``DIM`` in that order -- a positional call, a different
    argument count, a quoted parameter name, or ``DIM`` before ``ARR`` all fail to
    match it and fall through to :func:`_render_builtin_call`'s generic path instead,
    which leaves ``LOWER_BOUND``/``UPPER_BOUND`` spelled bare -- see its docstring.

    Parameters
    ----------
    node : FunctionCall
        A call whose ``name.upper()`` is ``LOWER_BOUND`` or ``UPPER_BOUND``.

    Returns
    -------
    bool
        True when ``node.arguments`` is exactly ``[ARR := ..., DIM := ...]`` with
        neither name quoted nor either argument output-bound.
    """
    if len(node.arguments) != 2:
        return False
    arr_arg, dim_arg = node.arguments
    return (
        not arr_arg.is_output
        and not arr_arg.is_quoted_name
        and arr_arg.name.upper() == "ARR"
        and not dim_arg.is_output
        and not dim_arg.is_quoted_name
        and dim_arg.name.upper() == "DIM"
    )


def _render_builtin_call(node: FunctionCall, ctx: _Context) -> str:
    """A bare (unquoted) call: a mapped builtin, the ``ARR``/``DIM`` bound pair, or neither.

    Structural equivalent of the old text translator's ``_translate_builtins`` pass together
    with ``_translate_array_bounds``, which runs first and claims ``LOWER_BOUND``/
    ``UPPER_BOUND`` before the generic substitution ever sees them (see that
    method's own skip of both names). An unmapped name -- ``node.name`` not a key
    of :data:`_BUILTIN_MAP` -- keeps its bare spelling, exactly as the old text
    translator left a call it had no table entry for untouched.

    Unlike :func:`_render_named_call`, which filters ``is_output`` arguments out of
    the dict it builds, this function has no destination to route an output binding
    to -- a bare call is rendered as a plain positional Python call, and Python has
    no way to bind a parameter by name into a builtin's positional argument list, let
    alone write a result back into one. Silently rendering the bound variable as if
    it were an input, as an earlier version of this function did, is worse than
    raising: the old text-based translator already produced invalid Python here
    (``:=``/``=>`` become ``==`` under ``OPERATOR_MAP``, a ``SyntaxError``), so
    treating the output as an input would trade a loud failure for one that runs
    silently and never writes the result back. So this raises instead, before
    rendering anything, for any call -- mapped or not, array-bound shape or not --
    that carries an ``=>`` argument. A ``:=`` (input) binding is unaffected: its name
    is still discarded and its value still rendered positionally, exactly as before --
    only the direction that has nowhere to go is refused.

    Parameters
    ----------
    node : FunctionCall
        The call to render; ``node.is_quoted`` is False.
    ctx : _Context
        See :func:`render`. Forwarded to every argument's render.

    Returns
    -------
    str
        ``(lambda ...)(arr, dim)`` for the array-bound shape; ``py_func(args, ...)``
        otherwise, with each argument rendered through :func:`render` and joined by
        ``", "``.

    Raises
    ------
    UnsupportedExpression
        Any argument of ``node`` carries an output binding (``is_output=True``,
        written ``=>`` in SCL) -- a bare call has no destination to route it to, so
        rendering it positionally would silently drop the write-back.
    """
    for argument in node.arguments:
        if argument.is_output:
            raise UnsupportedExpression(
                node,
                f"bare builtin call {node.name!r} binds {argument.name!r} with '=>' "
                "(an output); a positional call has nowhere to write the result back "
                "to, so rendering it as an input would run without error and silently "
                "drop the write",
            )
    upper_name = node.name.upper()
    if upper_name in _ARRAY_BOUND_BUILTINS and _is_array_bound_call(node):
        py_func = _BUILTIN_MAP[upper_name]
        arr_text = _render(node.arguments[0].value, ctx)
        dim_text = _render(node.arguments[1].value, ctx)
        return f"({py_func})({arr_text}, {dim_text})"
    py_func = _BUILTIN_MAP.get(upper_name, node.name)
    args_text = ", ".join(_render(argument.value, ctx) for argument in node.arguments)
    return f"{py_func}({args_text})"


def _render_named_call(node: FunctionCall, ctx: _Context) -> str:
    """A quoted block call, rendered by calling ``ExpressionTranslator._build_named_call``.

    ``_build_named_call`` is now a pure formatter: it takes each argument as an
    already-rendered ``(name, value)`` pair and does no parsing or translation of its
    own -- see its own docstring. So this function renders every bound argument's
    value through :func:`render` directly and hands the ``(name, value)`` pairs to
    ``_build_named_call`` as data, with no placeholder-and-substitute step in between.
    (An earlier version of this function had to route the value through a
    ``__ARGVAL<n>__`` placeholder instead, because the version of ``_build_named_call``
    it called back then still re-translated its argument text internally -- calling
    ``translate`` a second time on already-rendered Python corrupted it, e.g.
    ``self.translate("math.sqrt(self.x)")`` doubled to
    ``"math.math.sqrt(self.x)"``. That risk no longer exists: a pure formatter never
    looks at its arguments as anything but opaque text to embed.) The result is
    ``_build_named_call``'s own argument-selection rule (an argument written
    ``name => value`` is dropped; one with no name is bound to the callee's next
    declared input first, see the module ``arguments``) and its own wrapping text, not a re-derived
    copy of either.

    A parameter name written quoted (``"x" := #a``) is passed through quoted, because
    that is what reproduces ``_build_named_call``'s own (pre-existing, unrelated to
    this task) mishandling of that shape -- calling the real method is what makes that
    reproduction structural rather than a duplicated guess at its bug.

    Parameters
    ----------
    node : FunctionCall
        The call to render; ``node.is_quoted`` is True.
    ctx : _Context
        See :func:`render`. Forwarded to every bound argument's render.

    Returns
    -------
    str
        ``_build_named_call``'s own output.
    """
    # A positional argument is bound to the callee's next declared input, read from
    # the project through the resolver. Without one it raises: the old text path
    # dropped such arguments and called the block with no inputs, silently.
    positional = [argument for argument in node.arguments if not argument.name]
    try:
        positional_names = positional_parameter_names(
            node.name,
            positional_count=len(positional),
            already_named={argument.name for argument in node.arguments if argument.name},
            resolver=ctx.signature_resolver,
        )
    except PositionalBindingError as error:
        raise UnsupportedExpression(node, str(error)) from error
    names_for_positional = iter(positional_names)

    bound_arguments: list[tuple[str, str]] = []
    for argument in node.arguments:
        if argument.is_output:
            continue
        if argument.name:
            name_text = f'"{argument.name}"' if argument.is_quoted_name else argument.name
        else:
            name_text = next(names_for_positional)
        value_text = _render(argument.value, ctx)
        bound_arguments.append((name_text, value_text))
    return _TRANSLATOR._build_named_call(node.name, bound_arguments)  # noqa: SLF001
