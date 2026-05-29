"""Dependency extractor for SCL blocks.

This module extracts variable assignments and their dependencies from
parsed Block objects. It:
- Builds a variable registry from VAR sections
- Extracts all assignments with line numbers
- Tracks enclosing IF/CASE context
- Parses expressions into LogicExpression trees
"""

import re

from plc_code.parser.models import Block, Network, Region

from .expression_parser import ExpressionParser, ParseError
from .models import (
    Assignment,
    BlockDependencies,
    LogicExpression,
    NodeType,
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
    """Extracts assignments from SCL code with context tracking."""

    # Pattern for simple assignments: target := expression
    # Note: Parser may add spaces after # (e.g., "# alarmState" instead of "#alarmState")
    ASSIGNMENT_PATTERN = re.compile(
        r"(#\s*[a-zA-Z_][a-zA-Z0-9_.]*|\"[^\"]+\"[a-zA-Z0-9_.\[\]\"]*)\s*:=\s*([^;]+);",
        re.MULTILINE | re.DOTALL,
    )

    # Pattern for IF statements
    IF_PATTERN = re.compile(r"\bIF\s+(.+?)\s+THEN\b", re.IGNORECASE | re.DOTALL)

    # Pattern for ELSIF statements
    ELSIF_PATTERN = re.compile(r"\bELSIF\s+(.+?)\s+THEN\b", re.IGNORECASE | re.DOTALL)

    # Pattern for END_IF
    END_IF_PATTERN = re.compile(r"\bEND_IF\b", re.IGNORECASE)

    # Pattern for ELSE
    ELSE_PATTERN = re.compile(r"\bELSE\b", re.IGNORECASE)

    # Pattern for CASE statements (handles space after #)
    CASE_PATTERN = re.compile(r"\bCASE\s+(#\s*\S+|\S+)\s+OF\b", re.IGNORECASE)

    # Pattern for case labels (e.g., #NO_ALARM: or # NO_ALARM:)
    CASE_LABEL_PATTERN = re.compile(r"^\s*(#\s*[a-zA-Z_][a-zA-Z0-9_]*)\s*:", re.MULTILINE)

    # Pattern for END_CASE
    END_CASE_PATTERN = re.compile(r"\bEND_CASE\b", re.IGNORECASE)

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
        self.variable_lookup = {name: info.node_type for name, info in variable_registry.items()}

    def extract_from_block(self, block: Block) -> list[Assignment]:
        """Extract all assignments from a block.

        Parameters
        ----------
        block : Block
            The parsed block.

        Returns
        -------
        list[Assignment]
            All assignments found.
        """
        assignments: list[Assignment] = []

        for network in block.networks:
            assignments.extend(self._extract_from_network(network))

        return assignments

    def _extract_from_network(self, network: Network) -> list[Assignment]:
        """Extract assignments from a network."""
        assignments: list[Assignment] = []

        # Process content directly
        if network.content:
            assignments.extend(self._extract_from_code(network.content, region_name=""))

        # Process regions
        for region in network.regions:
            assignments.extend(self._extract_from_region(region))

        return assignments

    def _extract_from_region(self, region: Region, parent_region: str = "") -> list[Assignment]:
        """Extract assignments from a region."""
        assignments: list[Assignment] = []
        region_name = region.name if not parent_region else f"{parent_region}/{region.name}"

        # Process region content
        if region.content:
            assignments.extend(self._extract_from_code(region.content, region_name=region_name))

        # Process nested regions
        for nested in region.nested_regions:
            assignments.extend(self._extract_from_region(nested, region_name))

        return assignments

    def _extract_from_code(
        self,
        code: str,
        region_name: str = "",
        base_line: int = 1,
    ) -> list[Assignment]:
        """Extract assignments from code string with context tracking.

        Parameters
        ----------
        code : str
            The code to analyze.
        region_name : str
            Name of enclosing region.
        base_line : int
            Base line number offset.

        Returns
        -------
        list[Assignment]
            Extracted assignments.
        """
        assignments: list[Assignment] = []

        # Track context stack.
        # Each entry: (kind, condition, case_value) where kind is one of
        # 'IF', 'ELSIF', 'ELSE', 'CASE'.
        context_stack: list[tuple[str, LogicExpression | None, str | None]] = []

        lines = code.split("\n")
        line_starts = [0]
        for line in lines[:-1]:
            line_starts.append(line_starts[-1] + len(line) + 1)

        def get_line_number(pos: int) -> int:
            """Get line number for a position."""
            for i, start in enumerate(line_starts):
                if pos < start:
                    return base_line + i - 1
            return base_line + len(line_starts) - 1

        # Process code sequentially to track context
        pos = 0
        current_case_var: str | None = None

        while pos < len(code):
            # Check for IF
            if_match = self.IF_PATTERN.match(code, pos)
            if if_match:
                condition_str = if_match.group(1).strip()
                try:
                    condition_expr = self._parse_condition(condition_str, get_line_number(pos))
                    context_stack.append(("IF", condition_expr, None))
                except ParseError:
                    context_stack.append(("IF", None, None))
                pos = if_match.end()
                continue

            # Check for ELSIF
            elsif_match = self.ELSIF_PATTERN.match(code, pos)
            if elsif_match:
                # Pop previous IF/ELSIF
                if context_stack and context_stack[-1][0] in ("IF", "ELSIF"):
                    context_stack.pop()
                condition_str = elsif_match.group(1).strip()
                try:
                    condition_expr = self._parse_condition(condition_str, get_line_number(pos))
                    context_stack.append(("ELSIF", condition_expr, None))
                except ParseError:
                    context_stack.append(("ELSIF", None, None))
                pos = elsif_match.end()
                continue

            # Check for ELSE
            else_match = self.ELSE_PATTERN.match(code, pos)
            if else_match:
                # Pop previous IF/ELSIF
                if context_stack and context_stack[-1][0] in ("IF", "ELSIF"):
                    context_stack.pop()
                context_stack.append(("ELSE", None, None))
                pos = else_match.end()
                continue

            # Check for END_IF
            end_if_match = self.END_IF_PATTERN.match(code, pos)
            if end_if_match:
                # Pop all IF/ELSIF/ELSE entries until we find the IF
                while context_stack and context_stack[-1][0] in ("IF", "ELSIF", "ELSE"):
                    context_stack.pop()
                pos = end_if_match.end()
                continue

            # Check for CASE
            case_match = self.CASE_PATTERN.match(code, pos)
            if case_match:
                current_case_var = case_match.group(1)
                context_stack.append(("CASE", None, None))
                pos = case_match.end()
                continue

            # Check for case label
            label_match = self.CASE_LABEL_PATTERN.match(code, pos)
            if label_match and current_case_var:
                label = label_match.group(1)
                # Pop previous case label if any
                if context_stack and context_stack[-1][0] == "CASE_LABEL":
                    context_stack.pop()
                context_stack.append(("CASE_LABEL", None, label))
                pos = label_match.end()
                continue

            # Check for END_CASE
            end_case_match = self.END_CASE_PATTERN.match(code, pos)
            if end_case_match:
                # Pop case context
                while context_stack and context_stack[-1][0] in ("CASE", "CASE_LABEL"):
                    context_stack.pop()
                current_case_var = None
                pos = end_case_match.end()
                continue

            # Check for assignment
            assign_match = self.ASSIGNMENT_PATTERN.match(code, pos)
            if assign_match:
                target = assign_match.group(1)
                expr_str = assign_match.group(2).strip()
                line_num = get_line_number(assign_match.start())

                # Get current context
                enclosing_condition = None
                case_context = None
                for ctx_type, ctx_cond, ctx_case in context_stack:
                    if ctx_type in ("IF", "ELSIF") and ctx_cond:
                        enclosing_condition = ctx_cond
                    elif ctx_type == "CASE_LABEL" and ctx_case:
                        case_context = ctx_case

                # Parse the expression
                try:
                    expr = self._parse_expression(expr_str, line_num)

                    # Determine target type (strip # and any spaces)
                    target_name = target.lstrip("#").strip()
                    target_type = get_variable_type(target_name, self.variable_registry)

                    # Check for global DB target
                    if target.startswith('"'):
                        target_type = NodeType.GLOBAL_DB

                    assignment = Assignment(
                        target=target_name,
                        target_type=target_type,
                        expression=expr,
                        source_location=SourceLocation(self.source_file, line_num, region_name),
                        enclosing_condition=enclosing_condition,
                        case_context=case_context,
                    )
                    assignments.append(assignment)
                except ParseError:
                    # Skip unparseable expressions
                    pass

                pos = assign_match.end()
                continue

            # Move forward
            pos += 1

        return assignments

    def _parse_condition(self, condition: str, line_number: int) -> LogicExpression:
        """Parse a condition expression."""
        parser = ExpressionParser(self.variable_lookup, self.source_file, line_number)
        return parser.parse(condition)

    def _parse_expression(self, expr: str, line_number: int) -> LogicExpression:
        """Parse an expression."""
        parser = ExpressionParser(self.variable_lookup, self.source_file, line_number)
        return parser.parse(expr)


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
