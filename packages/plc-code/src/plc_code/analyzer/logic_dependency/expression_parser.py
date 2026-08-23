"""SCL expressions as :class:`LogicExpression` trees, read through the shared parser.

This module used to carry its own regex lexer and recursive-descent parser for
boolean and comparison expressions. That parser knew no arithmetic and no
indexing, and tolerated unread trailing tokens: ``#a + #b`` was read as ``#a`` and
``#b`` silently vanished from the dependency graph. It is gone. The expression
text is now tokenized by :mod:`plc_code.parser.lexer` and parsed by
:func:`plc_code.parser.expression_parser.parse_expression` -- the one grammar every
other consumer reads SCL with, which refuses a slice it cannot read in full -- and
the resulting tree is folded into the :class:`LogicExpression` shape the tracers,
the graph builder and the Mermaid generator consume.

The public surface keeps :class:`ExpressionParser`, :class:`ParseError` and
:func:`parse_expression`, and adds :meth:`ExpressionParser.convert` for a caller
that already holds a tree, plus :func:`reference_text`.
"""

from __future__ import annotations

from plc_code.parser import expressions as ast
from plc_code.parser.expression_parser import parse_expression as parse_expression_tokens
from plc_code.parser.lexer import TokenType, tokenize

from .models import (
    DependencyNode,
    LogicExpression,
    NodeType,
    OperatorType,
    SourceLocation,
)

#: SCL binary operator spelling (upper-cased) to the dependency operator it becomes.
_BINARY_OPERATORS: dict[str, OperatorType] = {
    "AND": OperatorType.AND,
    "&": OperatorType.AND,
    "OR": OperatorType.OR,
    "XOR": OperatorType.XOR,
    "=": OperatorType.COMPARE_EQ,
    "<>": OperatorType.COMPARE_NE,
    "<": OperatorType.COMPARE_LT,
    ">": OperatorType.COMPARE_GT,
    "<=": OperatorType.COMPARE_LE,
    ">=": OperatorType.COMPARE_GE,
    "+": OperatorType.ADD,
    "-": OperatorType.SUBTRACT,
    "*": OperatorType.MULTIPLY,
    "/": OperatorType.DIVIDE,
    "MOD": OperatorType.MODULO,
    "**": OperatorType.POWER,
}


class ParseError(Exception):
    """The expression text could not be read as one SCL expression."""


class ExpressionParser:
    """Reads an SCL expression string into a :class:`LogicExpression` tree.

    Variables become :class:`DependencyNode` leaves typed through
    ``variable_lookup``; operators become the matching :class:`OperatorType` with
    their operands as children. A function call is an opaque operation that depends
    on all its input arguments (an ``AND`` of the call node and the arguments, as
    before); an indexed access depends on its base and on every index expression.

    Parameters
    ----------
    variable_lookup : dict[str, NodeType] | None
        Mapping from variable name (without ``#``) to its node type.
    source_file : str
        Source file path recorded on every node's location.
    base_line : int
        Source line recorded on every node's location.
    """

    def __init__(
        self,
        variable_lookup: dict[str, NodeType] | None = None,
        source_file: str = "",
        base_line: int = 0,
    ) -> None:
        self.variable_lookup = variable_lookup or {}
        self.source_file = source_file
        self.base_line = base_line

    def parse(self, expression: str) -> LogicExpression:
        """Parse ``expression`` into a :class:`LogicExpression` tree.

        Raises
        ------
        ParseError
            When the shared parser cannot read the text as one expression in full.
            The message is the parser's own, with its line and column relative to
            the text.
        """
        tokens = [token for token in tokenize(expression) if token.type is not TokenType.EOF]
        result = parse_expression_tokens(tokens)
        if result.expression is None:
            detail = "; ".join(error.message for error in result.errors) or "empty expression"
            raise ParseError(f"cannot read {expression.strip()!r}: {detail}")
        return self.convert(result.expression)

    # -- tree folding -------------------------------------------------------------

    def convert(self, node: ast.Expression) -> LogicExpression:
        """Fold an already-parsed expression tree into a :class:`LogicExpression`.

        The extractor's path: it walks the statement AST and hands each
        expression node here, so no text is ever re-parsed.
        """
        if isinstance(node, ast.Grouping):
            return self.convert(node.inner)
        if isinstance(node, ast.Literal):
            return self._constant(node.value, _literal_data_type(node.value))
        if isinstance(node, ast.TypedLiteral):
            return self._constant(f"{node.prefix}#{node.value}", "Number")
        if isinstance(node, ast.VariableRef | ast.Member | ast.Index):
            return self._reference(node)
        if isinstance(node, ast.UnaryOp):
            operator = OperatorType.NOT if node.operator.upper() == "NOT" else OperatorType.NEGATE
            return self._expression(operator, [self.convert(node.operand)])
        if isinstance(node, ast.BinaryOp):
            binary = _BINARY_OPERATORS.get(node.operator.upper())
            if binary is None:  # pragma: no cover - the shared grammar has no other spelling
                raise ParseError(f"unknown operator {node.operator!r}")
            return self._expression(binary, [self.convert(node.left), self.convert(node.right)])
        if isinstance(node, ast.FunctionCall):
            return self._call(node)
        raise ParseError(f"unsupported expression node {type(node).__name__}")  # pragma: no cover

    def _reference(self, node: ast.VariableRef | ast.Member | ast.Index) -> LogicExpression:
        """A variable, a member path, or an indexed access, as a leaf (plus index deps).

        The leaf names the whole path with computed indices as ``*`` (``arr[*].x``);
        every index expression anywhere along the path is a dependency of its own,
        so ``#arr[#i].x`` depends on ``i`` as well.
        """
        indices: list[ast.Expression] = []
        path: ast.Expression = node
        while isinstance(path, ast.Member | ast.Index):
            if isinstance(path, ast.Index):
                indices = [*path.indices, *indices]
            path = path.base
        leaf = self._leaf(node)
        if not indices:
            return leaf
        return self._expression(OperatorType.INDEX, [leaf, *(self.convert(index) for index in indices)])

    def _leaf(self, node: ast.Expression) -> LogicExpression:
        """The :class:`DependencyNode` a reference path names."""
        root = node
        while isinstance(root, ast.Member | ast.Index):
            root = root.base
        if not isinstance(root, ast.VariableRef):
            # `"Get"(#a).field`: a member of a call's result. Not a variable; refused
            # rather than named after a spelling that hides the call's arguments.
            raise ParseError(f"a member of a {type(root).__name__} result is not a traceable reference")
        reference = reference_text(node)
        if isinstance(root, ast.VariableRef) and root.is_local:
            # Typed by the full path when the lookup knows it, else by its root
            # variable: a member of an input struct is an input.
            name = reference.lstrip("#")
            node_type = self.variable_lookup.get(name) or self.variable_lookup.get(
                root.name, NodeType.UNKNOWN
            )
            return self._identity(name, node_type, reference, located=True)
        # `%I0.0`, `"DB".field.path` and a bare quoted symbol (`"Clock_1Hz"`, a
        # PLC tag or a global DB) are all global: named with their quotes, so
        # they never collide with a block variable of the same name.
        return self._identity(reference, NodeType.GLOBAL_DB, reference, located=True)

    def _call(self, node: ast.FunctionCall) -> LogicExpression:
        arguments = [self.convert(argument.value) for argument in node.arguments if not argument.is_output]
        call = self._identity(node.name, NodeType.FUNCTION_CALL, node.name, located=False)
        if not arguments:
            return call
        return self._expression(OperatorType.AND, [call, *arguments])

    # -- leaves -------------------------------------------------------------------

    def _constant(self, value: str, data_type: str) -> LogicExpression:
        return self._identity(value, NodeType.CONSTANT, value, located=False, data_type=data_type)

    def _identity(
        self,
        name: str,
        node_type: NodeType,
        reference: str,
        *,
        located: bool,
        data_type: str = "",
    ) -> LogicExpression:
        location = SourceLocation(self.source_file, self.base_line) if located else SourceLocation()
        leaf = DependencyNode(
            name=name,
            node_type=node_type,
            data_type=data_type,
            source_location=location,
            raw_reference=reference,
        )
        return LogicExpression(operator=OperatorType.IDENTITY, operands=[leaf])

    def _expression(self, operator: OperatorType, operands: list[LogicExpression]) -> LogicExpression:
        return LogicExpression(operator=operator, operands=list(operands))


def _literal_data_type(value: str) -> str:
    if value.upper() in ("TRUE", "FALSE"):
        return "Bool"
    if value.startswith("'"):
        return "String"
    return "Number"


def reference_text(node: ast.Expression) -> str:
    """The spelling of a reference path: ``#a.b[*]``, ``"DB".x``, ``%I0.0``."""
    if isinstance(node, ast.VariableRef):
        if node.is_local:
            return f"#{node.name}"
        if node.is_absolute:
            return f"%{node.name}"
        return f'"{node.name}"'
    if isinstance(node, ast.Member):
        # A member's own `#` (`#a.#b`) is scoping, not part of the name: `#a.b` is
        # the same variable. Its `%` is kept: `%DB1.%DBX0.0` is not `%DB1.DBX0.0`.
        name = f'"{node.name}"' if node.is_quoted else node.name
        if node.is_absolute:
            name = f"%{name}"
        return f"{reference_text(node.base)}.{name}"
    if isinstance(node, ast.Index):
        inner = ", ".join(_index_text(index) for index in node.indices)
        return f"{reference_text(node.base)}[{inner}]"
    return _index_text(node)


def _index_text(node: ast.Expression) -> str:
    """An index's spelling: a literal as written, anything computed as ``*``.

    ``arr[1]`` and ``arr[2]`` are two slots; ``arr[#i]`` and ``arr[#i + 1]`` are
    the same unknown slot, so a read and a write of it join on one name.
    """
    if isinstance(node, ast.Literal):
        return node.value
    return "*"


def parse_expression(
    expression: str,
    variable_lookup: dict[str, NodeType] | None = None,
    source_file: str = "",
    base_line: int = 0,
) -> LogicExpression:
    """Parse ``expression`` with a one-off :class:`ExpressionParser`."""
    return ExpressionParser(variable_lookup, source_file, base_line).parse(expression)
