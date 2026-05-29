"""Data models for logic dependency analysis.

This module defines data structures for representing output-to-input
dependency trees, including logic expressions (AND, OR, NOT) and
source location tracking for code navigation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Union


class NodeType(Enum):
    """Type of node in the dependency tree.

    Attributes
    ----------
    OUTPUT : str
        Output variable (VAR_OUTPUT).
    INPUT : str
        Input variable (VAR_INPUT).
    IN_OUT : str
        In-out variable (VAR_IN_OUT).
    STATE : str
        Static/state variable (VAR).
    TEMP : str
        Temporary variable (VAR_TEMP).
    CONSTANT : str
        Constant value (VAR CONSTANT or literal).
    GLOBAL_DB : str
        Global data block reference ("DBName".field).
    TIMER : str
        Timer function block (TON, TOF, TP).
    FUNCTION_CALL : str
        Function or FB call result.
    UNKNOWN : str
        Unknown or unresolved reference.
    """

    OUTPUT = "output"
    INPUT = "input"
    IN_OUT = "in_out"
    STATE = "state"
    TEMP = "temp"
    CONSTANT = "constant"
    GLOBAL_DB = "global_db"
    TIMER = "timer"
    FUNCTION_CALL = "function_call"
    UNKNOWN = "unknown"


class OperatorType(Enum):
    """Type of logical or comparison operator.

    Attributes
    ----------
    AND : str
        Logical AND.
    OR : str
        Logical OR.
    NOT : str
        Logical NOT (unary).
    XOR : str
        Logical XOR.
    COMPARE_EQ : str
        Equality comparison (=).
    COMPARE_NE : str
        Not equal comparison (<>).
    COMPARE_LT : str
        Less than comparison (<).
    COMPARE_GT : str
        Greater than comparison (>).
    COMPARE_LE : str
        Less than or equal (<=).
    COMPARE_GE : str
        Greater than or equal (>=).
    ASSIGN : str
        Assignment (:=).
    IF_THEN : str
        Conditional IF block.
    CASE_WHEN : str
        CASE state context.
    IDENTITY : str
        Pass-through (single operand, no operation).
    """

    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    XOR = "XOR"
    COMPARE_EQ = "="
    COMPARE_NE = "<>"
    COMPARE_LT = "<"
    COMPARE_GT = ">"
    COMPARE_LE = "<="
    COMPARE_GE = ">="
    ASSIGN = ":="
    IF_THEN = "IF"
    CASE_WHEN = "CASE"
    IDENTITY = "IDENTITY"


@dataclass
class SourceLocation:
    """Location in source code for navigation.

    Attributes
    ----------
    file_path : str
        Path to source file.
    line_number : int
        Line number (1-indexed).
    region_name : str
        Enclosing REGION name if any.
    """

    file_path: str = ""
    line_number: int = 0
    region_name: str = ""

    def __str__(self) -> str:
        """Format as file:line for display."""
        if self.file_path:
            # Extract just filename
            from pathlib import Path

            name = Path(self.file_path).name
            return f"{name}:{self.line_number}"
        return f"line {self.line_number}"


@dataclass
class DependencyNode:
    """A node in the dependency tree representing a variable or value.

    Attributes
    ----------
    name : str
        Variable or value name (e.g., "alarmTrigger", "ProcessData.controller.input.temp").
    node_type : NodeType
        Type of node (INPUT, OUTPUT, STATE, etc.).
    data_type : str
        Data type (e.g., "Bool", "Real", "USInt").
    source_location : SourceLocation
        Location where this variable is referenced.
    raw_reference : str
        Original reference string from code (e.g., "#alarmTrigger").
    """

    name: str
    node_type: NodeType
    data_type: str = ""
    source_location: SourceLocation = field(default_factory=SourceLocation)
    raw_reference: str = ""

    def __hash__(self) -> int:
        """Hash by name and type for set operations."""
        return hash((self.name, self.node_type))

    def __eq__(self, other: object) -> bool:
        """Compare by name and type."""
        if not isinstance(other, DependencyNode):
            return False
        return self.name == other.name and self.node_type == other.node_type


# Forward reference for recursive type
LogicOperand = Union["LogicExpression", DependencyNode]


@dataclass
class LogicExpression:
    """A logic expression combining operands with an operator.

    This represents AND, OR, NOT operations as well as conditionals.
    The tree structure allows representing complex nested expressions.

    Attributes
    ----------
    operator : OperatorType
        The operation (AND, OR, NOT, IF_THEN, etc.).
    operands : list[LogicOperand]
        Child expressions or terminal nodes.
    condition : LogicExpression | None
        For IF_THEN: the condition that must be true.
    case_value : str | None
        For CASE_WHEN: the case label value.
    source_location : SourceLocation
        Location of this expression in source.
    """

    operator: OperatorType
    operands: list[LogicOperand] = field(default_factory=list)
    condition: "LogicExpression | None" = None
    case_value: str | None = None
    source_location: SourceLocation = field(default_factory=SourceLocation)

    def is_terminal(self) -> bool:
        """Check if this is effectively a terminal (single node, IDENTITY)."""
        return self.operator == OperatorType.IDENTITY and len(self.operands) == 1

    def get_terminal_node(self) -> DependencyNode | None:
        """Get the terminal node if this is an IDENTITY expression."""
        if self.is_terminal() and isinstance(self.operands[0], DependencyNode):
            return self.operands[0]
        return None


@dataclass
class Assignment:
    """An assignment statement extracted from code.

    Attributes
    ----------
    target : str
        Target variable name (LHS of :=).
    target_type : NodeType
        Type of the target variable.
    expression : LogicExpression
        Parsed expression tree (RHS of :=).
    source_location : SourceLocation
        Location in source code.
    enclosing_condition : LogicExpression | None
        IF condition under which this assignment executes.
    case_context : str | None
        CASE value under which this assignment executes.
    """

    target: str
    target_type: NodeType
    expression: LogicExpression
    source_location: SourceLocation = field(default_factory=SourceLocation)
    enclosing_condition: "LogicExpression | None" = None
    case_context: str | None = None


@dataclass
class VariableInfo:
    """Information about a declared variable.

    Attributes
    ----------
    name : str
        Variable name.
    node_type : NodeType
        Type classification (INPUT, OUTPUT, STATE, etc.).
    data_type : str
        Data type string.
    default_value : str | None
        Default value if specified.
    """

    name: str
    node_type: NodeType
    data_type: str = ""
    default_value: str | None = None


@dataclass
class BlockDependencies:
    """All dependencies extracted from a single block.

    Attributes
    ----------
    block_name : str
        Name of the block.
    source_file : str
        Path to source file.
    variables : dict[str, VariableInfo]
        Registry of all declared variables.
    assignments : list[Assignment]
        All assignments found in the block.
    """

    block_name: str
    source_file: str = ""
    variables: dict[str, VariableInfo] = field(default_factory=dict)
    assignments: list[Assignment] = field(default_factory=list)


@dataclass
class OutputDependencyTree:
    """Complete dependency tree for a single output variable.

    Traces all dependencies from an output back to inputs, state
    variables, constants, and global DB references.

    Attributes
    ----------
    output : DependencyNode
        The output variable being analyzed.
    expression_tree : LogicExpression
        The full expression tree showing how output is derived.
    all_inputs : list[DependencyNode]
        All VAR_INPUT dependencies (transitive).
    all_states : list[DependencyNode]
        All VAR (state) dependencies (transitive).
    all_constants : list[DependencyNode]
        All constant dependencies (transitive).
    all_global_dbs : list[DependencyNode]
        All global DB references (transitive).
    intermediate_vars : list[str]
        Names of intermediate state variables in the chain.
    """

    output: DependencyNode
    expression_tree: LogicExpression
    all_inputs: list[DependencyNode] = field(default_factory=list)
    all_states: list[DependencyNode] = field(default_factory=list)
    all_constants: list[DependencyNode] = field(default_factory=list)
    all_global_dbs: list[DependencyNode] = field(default_factory=list)
    intermediate_vars: list[str] = field(default_factory=list)

    @property
    def all_dependencies(self) -> list[DependencyNode]:
        """Get all dependency nodes combined."""
        return self.all_inputs + self.all_states + self.all_constants + self.all_global_dbs


@dataclass
class BlockAnalysisResult:
    """Result of analyzing all outputs in a block.

    Attributes
    ----------
    block_name : str
        Name of the analyzed block.
    source_file : str
        Path to source file.
    output_trees : dict[str, OutputDependencyTree]
        Mapping from output name to its dependency tree.
    errors : list[str]
        Any errors encountered during analysis.
    """

    block_name: str
    source_file: str = ""
    output_trees: dict[str, OutputDependencyTree] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def output_count(self) -> int:
        """Get number of outputs analyzed."""
        return len(self.output_trees)

    def get_output_tree(self, output_name: str) -> OutputDependencyTree | None:
        """Get dependency tree for a specific output."""
        return self.output_trees.get(output_name)
