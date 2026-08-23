"""Dependency extractor for SCL blocks.

This module extracts variable assignments and their dependencies from
parsed Block objects. It:
- Builds a variable registry from VAR sections
- Walks the shared statement AST of every region and network
- Tracks enclosing IF/CASE context
- Folds expression trees into LogicExpression trees
"""

from plc_code.parser.expressions import Expression, Index, Literal, Member, TypedLiteral, VariableRef
from plc_code.parser.lexer import Token
from plc_code.parser.models import Block, Network, Region
from plc_code.parser.statement_parser import parse_statements, verify_no_silent_loss
from plc_code.parser.statements import Assignment as StmtAssignment
from plc_code.parser.statements import Call, Case, For, If, Statement, While

from .expression_parser import ExpressionParser, ParseError, reference_text
from .models import (
    Assignment,
    BlockDependencies,
    LogicExpression,
    NodeType,
    OperatorType,
    SourceLocation,
    VariableInfo,
)


def build_variable_registry(block: Block) -> dict[str, VariableInfo]:
    """Build a registry of all declared variables in a block.

    Parameters
    ----------
    block : Block
        The parsed block.

    Returns
    -------
    dict[str, VariableInfo]
        Mapping from variable name to its info.
    """
    registry: dict[str, VariableInfo] = {}

    section_type_map = {
        "VAR_INPUT": NodeType.INPUT,
        "VAR_OUTPUT": NodeType.OUTPUT,
        "VAR_IN_OUT": NodeType.IN_OUT,
        "VAR": NodeType.STATE,
        "VAR_TEMP": NodeType.TEMP,
        "VAR_CONSTANT": NodeType.CONSTANT,
    }

    for section in block.variable_sections:
        node_type = section_type_map.get(section.section_type, NodeType.UNKNOWN)

        # Override for constants
        if section.is_constant:
            node_type = NodeType.CONSTANT

        for var in section.variables:
            registry[var.name] = VariableInfo(
                name=var.name,
                node_type=node_type,
                data_type=var.data_type,
                default_value=var.default_value,
            )

    return registry


def get_variable_type(name: str, registry: dict[str, VariableInfo]) -> NodeType:
    """Look up the type of a variable.

    Parameters
    ----------
    name : str
        Variable name (without # prefix).
    registry : dict[str, VariableInfo]
        Variable registry.

    Returns
    -------
    NodeType
        The variable type, or UNKNOWN if not found.
    """
    if name in registry:
        return registry[name].node_type
    return NodeType.UNKNOWN


class AssignmentExtractor:
    """Extracts assignments, with their enclosing IF/CASE context, from a block.

    Walks the statement AST the shared parser builds from each region's and
    network's token slice (:func:`plc_code.parser.statement_parser.parse_statements`),
    so an assignment's target and value are expression trees, never text sliced by
    regex. The old text walk read ``Region.content`` -- a re-spaced rendering in
    which ``<=`` had become ``< =`` and ``T#0s`` ``T # 0 s`` -- with patterns that
    could capture several statements as one expression and parse only its first
    token. What it could not read it skipped without a word; what this walker
    cannot read is recorded in ``parse_errors``.

    An FB or FC call statement with ``=>`` output bindings yields one assignment per
    bound output: the output depends on the callee and every input argument. The
    text walk never saw those (``=>`` is not ``:=``).
    """

    def __init__(
        self,
        variable_registry: dict[str, VariableInfo],
        source_file: str = "",
    ) -> None:
        """Initialize extractor.

        Parameters
        ----------
        variable_registry : dict[str, VariableInfo]
            Registry of declared variables.
        source_file : str
            Path to source file for location tracking.
        """
        self.variable_registry = variable_registry
        self.source_file = source_file
        self.parse_errors: list[str] = []
        self.variable_lookup = {name: info.node_type for name, info in variable_registry.items()}

    def extract_from_block(self, block: Block) -> list[Assignment]:
        """Extract all assignments from a block, in source order."""
        assignments: list[Assignment] = []
        for network in block.networks:
            assignments.extend(self._extract_from_network(network))
        return assignments

    def _extract_from_network(self, network: Network) -> list[Assignment]:
        assignments: list[Assignment] = []
        if network.tokens:
            assignments.extend(self._extract_from_tokens(network.tokens, region_name=""))
        for region in network.regions:
            assignments.extend(self._extract_from_region(region))
        return assignments

    def _extract_from_region(self, region: Region, parent_region: str = "") -> list[Assignment]:
        # ``region.tokens`` already carries the nested regions' tokens flattened
        # in (the SCL parser's doing), so the nesting only names the context.
        region_name = region.name if not parent_region else f"{parent_region}/{region.name}"
        if region.tokens:
            return self._extract_from_tokens(region.tokens, region_name=region_name)
        return []

    def _extract_from_tokens(self, tokens: list[Token], region_name: str) -> list[Assignment]:
        result = parse_statements(tokens)
        for error in result.errors:
            self.parse_errors.append(error.message)
        for problem in verify_no_silent_loss(tokens, result):
            self.parse_errors.append(problem)
        return self._walk(result.statements, region_name, condition=None, case_context=None)

    # -- the walk ------------------------------------------------------------------

    def _walk(
        self,
        statements: list[Statement],
        region_name: str,
        condition: LogicExpression | None,
        case_context: str | None,
    ) -> list[Assignment]:
        """Assignments in ``statements``, each under the innermost IF condition and
        CASE label enclosing it (an ELSE body carries no condition, as before)."""
        found: list[Assignment] = []
        for statement in statements:
            if isinstance(statement, StmtAssignment):
                assignment = self._assignment(statement, region_name, condition, case_context)
                if assignment is not None:
                    found.append(assignment)
            elif isinstance(statement, Call):
                found.extend(self._call_outputs(statement, region_name, condition, case_context))
            elif isinstance(statement, If):
                for branch in statement.branches:
                    branch_condition = self._condition(branch.condition_expr, statement.line) or condition
                    found.extend(self._walk(branch.body, region_name, branch_condition, case_context))
                found.extend(self._walk(statement.else_body, region_name, condition, case_context))
            elif isinstance(statement, Case):
                for arm in statement.branches:
                    label = ", ".join(_label_text(value) for value in arm.values_expr)
                    found.extend(self._walk(arm.body, region_name, condition, label or case_context))
                found.extend(self._walk(statement.default, region_name, condition, case_context))
            elif isinstance(statement, For):
                loop_variable = self._for_variable(statement, region_name, condition, case_context)
                if loop_variable is not None:
                    found.append(loop_variable)
                found.extend(self._walk(statement.body, region_name, condition, case_context))
            elif isinstance(statement, While):
                found.extend(self._walk(statement.body, region_name, condition, case_context))
            # Return / Exit: nothing assigned.
        return found

    def _condition(self, expression: Expression | None, line: int) -> LogicExpression | None:
        if expression is None:
            return None
        try:
            return self._parser(line).convert(expression)
        except ParseError as error:
            self._record(error, line)
            return None

    def _assignment(
        self,
        statement: StmtAssignment,
        region_name: str,
        condition: LogicExpression | None,
        case_context: str | None,
    ) -> Assignment | None:
        if statement.target_expr is None or statement.value_expr is None:
            self.parse_errors.append(f"line {statement.line}: assignment has no parsed expression tree")
            return None
        try:
            expression = self._parser(statement.line).convert(statement.value_expr)
        except ParseError as error:
            self._record(error, statement.line)
            return None
        target, target_type = self._target(statement.target_expr)
        return Assignment(
            target=target,
            target_type=target_type,
            expression=expression,
            source_location=SourceLocation(self.source_file, statement.line, region_name),
            enclosing_condition=condition,
            case_context=case_context,
        )

    def _call_outputs(
        self,
        statement: Call,
        region_name: str,
        condition: LogicExpression | None,
        case_context: str | None,
    ) -> list[Assignment]:
        """One assignment per ``=>`` output of a call: it depends on the callee and inputs."""
        outputs = [argument for argument in statement.arguments if argument.is_output]
        if not outputs or statement.callee_expr is None:
            return []
        parser = self._parser(statement.line)
        try:
            callee = parser.convert(statement.callee_expr)
            inputs = [
                parser.convert(argument.value_expr)
                for argument in statement.arguments
                if not argument.is_output and argument.value_expr is not None
            ]
        except ParseError as error:
            self._record(error, statement.line)
            return []
        depends_on = (
            LogicExpression(operator=OperatorType.AND, operands=[callee, *inputs]) if inputs else callee
        )
        found: list[Assignment] = []
        for argument in outputs:
            if argument.value_expr is None:
                self.parse_errors.append(
                    f"line {statement.line}: output {argument.name!r} has no parsed expression tree"
                )
                continue
            target, target_type = self._target(argument.value_expr)
            found.append(
                Assignment(
                    target=target,
                    target_type=target_type,
                    expression=depends_on,
                    source_location=SourceLocation(self.source_file, statement.line, region_name),
                    enclosing_condition=condition,
                    case_context=case_context,
                )
            )
        return found

    def _for_variable(
        self,
        statement: For,
        region_name: str,
        condition: LogicExpression | None,
        case_context: str | None,
    ) -> Assignment | None:
        """The loop variable as an assignment from the loop's bounds (and step)."""
        bounds = [expr for expr in (statement.start_expr, statement.end_expr, statement.step_expr) if expr]
        variable = _for_variable_text(statement.variable)
        if not bounds or variable is None:
            return None
        parser = self._parser(statement.line)
        try:
            operands = [parser.convert(expr) for expr in bounds]
        except ParseError as error:
            self._record(error, statement.line)
            return None
        expression = (
            operands[0]
            if len(operands) == 1
            else LogicExpression(operator=OperatorType.AND, operands=list(operands))
        )
        name = variable.lstrip("#")
        return Assignment(
            target=name,
            target_type=get_variable_type(name, self.variable_registry),
            expression=expression,
            source_location=SourceLocation(self.source_file, statement.line, region_name),
            enclosing_condition=condition,
            case_context=case_context,
        )

    def _target(self, expression: Expression) -> tuple[str, NodeType]:
        """The assignment target's name (``#``-less path text) and node type."""
        text = reference_text(expression)
        if text.startswith("#"):
            name = text[1:]
            root = name.split(".")[0].split("[")[0]
            node_type = get_variable_type(name, self.variable_registry)
            if node_type is NodeType.UNKNOWN:
                node_type = get_variable_type(root, self.variable_registry)
            return name, node_type
        return text, NodeType.GLOBAL_DB

    def _parser(self, line: int) -> ExpressionParser:
        return ExpressionParser(self.variable_lookup, self.source_file, line)

    def _record(self, error: ParseError, line_number: int) -> None:
        """Keep an expression the parser refused, with its line, for the caller."""
        self.parse_errors.append(f"line {line_number}: {error}")


def _for_variable_text(tokens: list[Token]) -> str | None:
    """``#name`` from a FOR variable's token slice (``#`` then an identifier), else None."""
    values = [token.value for token in tokens]
    if len(values) == 2 and values[0] == "#":
        return f"#{values[1]}"
    if len(values) == 1 and values[0].startswith("#"):
        return values[0]
    return None


def _label_text(value: Expression | None) -> str:
    """A CASE label as written: a literal's text, a reference's spelling, else ``*``."""
    if value is None:
        return "*"
    if isinstance(value, Literal):
        return value.value
    if isinstance(value, TypedLiteral):
        return f"{value.prefix}#{value.value}"
    if isinstance(value, VariableRef | Member | Index):
        return reference_text(value)
    return "*"


def extract_dependencies(block: Block) -> BlockDependencies:
    """Extract all dependencies from a block.

    Parameters
    ----------
    block : Block
        The parsed block.

    Returns
    -------
    BlockDependencies
        All dependencies found in the block.
    """
    # Build variable registry
    registry = build_variable_registry(block)

    # Extract assignments
    extractor = AssignmentExtractor(registry, block.source_file)
    assignments = extractor.extract_from_block(block)

    return BlockDependencies(
        block_name=block.name,
        source_file=block.source_file,
        variables=registry,
        assignments=assignments,
        parse_errors=list(extractor.parse_errors),
    )


def get_output_assignments(deps: BlockDependencies) -> list[Assignment]:
    """Get all assignments to output variables.

    Parameters
    ----------
    deps : BlockDependencies
        Block dependencies.

    Returns
    -------
    list[Assignment]
        Assignments targeting VAR_OUTPUT variables.
    """
    return [a for a in deps.assignments if a.target_type == NodeType.OUTPUT]


def get_state_assignments(deps: BlockDependencies) -> list[Assignment]:
    """Get all assignments to state variables.

    Parameters
    ----------
    deps : BlockDependencies
        Block dependencies.

    Returns
    -------
    list[Assignment]
        Assignments targeting VAR (state) variables.
    """
    return [a for a in deps.assignments if a.target_type == NodeType.STATE]
