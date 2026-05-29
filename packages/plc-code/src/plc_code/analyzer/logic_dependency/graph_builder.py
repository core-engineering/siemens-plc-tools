"""Graph builder for transitive dependency analysis.

This module builds complete dependency trees by tracing assignments
transitively through intermediate state variables. For each output,
it constructs a tree showing all inputs, states, constants, and
global DB references that contribute to its value.
"""

from collections import defaultdict

from .models import (
    Assignment,
    BlockDependencies,
    DependencyNode,
    LogicExpression,
    NodeType,
    OperatorType,
    OutputDependencyTree,
)


def collect_leaf_nodes(expr: LogicExpression) -> list[DependencyNode]:
    """Collect all leaf (terminal) nodes from an expression tree.

    Parameters
    ----------
    expr : LogicExpression
        The expression tree.

    Returns
    -------
    list[DependencyNode]
        All terminal DependencyNodes in the tree.
    """
    nodes: list[DependencyNode] = []

    def traverse(e: LogicExpression | DependencyNode) -> None:
        if isinstance(e, DependencyNode):
            nodes.append(e)
        elif isinstance(e, LogicExpression):
            for operand in e.operands:
                traverse(operand)
            if e.condition:
                traverse(e.condition)

    traverse(expr)
    return nodes


def get_referenced_variables(expr: LogicExpression) -> set[str]:
    """Get names of all variables referenced in an expression.

    Parameters
    ----------
    expr : LogicExpression
        The expression tree.

    Returns
    -------
    set[str]
        Set of variable names.
    """
    nodes = collect_leaf_nodes(expr)
    return {
        node.name
        for node in nodes
        if node.node_type in (NodeType.INPUT, NodeType.STATE, NodeType.IN_OUT, NodeType.TEMP)
    }


class DependencyGraphBuilder:
    """Builds transitive dependency trees for outputs.

    This class traces dependencies through intermediate state variables
    to produce complete input-to-output dependency trees.
    """

    def __init__(self, deps: BlockDependencies) -> None:
        """Initialize builder.

        Parameters
        ----------
        deps : BlockDependencies
            Extracted block dependencies.
        """
        self.deps = deps
        # Index assignments by target
        self.assignments_by_target: dict[str, list[Assignment]] = defaultdict(list)
        for assignment in deps.assignments:
            self.assignments_by_target[assignment.target].append(assignment)

    def build_output_tree(self, output_name: str) -> OutputDependencyTree | None:
        """Build complete dependency tree for an output variable.

        Parameters
        ----------
        output_name : str
            Name of the output variable.

        Returns
        -------
        OutputDependencyTree | None
            The dependency tree, or None if output not found.
        """
        # Get output variable info
        if output_name not in self.deps.variables:
            return None

        var_info = self.deps.variables[output_name]
        if var_info.node_type != NodeType.OUTPUT:
            return None

        # Find assignments to this output
        output_assignments = self.assignments_by_target.get(output_name, [])
        if not output_assignments:
            return None

        # Build combined expression tree from all assignments
        combined_expr = self._combine_assignments(output_assignments)

        # Trace transitive dependencies
        visited: set[str] = set()
        intermediate_vars: list[str] = []
        expanded_expr = self._expand_dependencies(combined_expr, visited, intermediate_vars)

        # Collect all leaf nodes by type
        all_nodes = collect_leaf_nodes(expanded_expr)

        all_inputs = [n for n in all_nodes if n.node_type == NodeType.INPUT]
        all_states = [n for n in all_nodes if n.node_type == NodeType.STATE]
        all_constants = [n for n in all_nodes if n.node_type == NodeType.CONSTANT]
        all_global_dbs = [n for n in all_nodes if n.node_type == NodeType.GLOBAL_DB]

        # Deduplicate
        all_inputs = list({(n.name, n.node_type): n for n in all_inputs}.values())
        all_states = list({(n.name, n.node_type): n for n in all_states}.values())
        all_constants = list({(n.name, n.node_type): n for n in all_constants}.values())
        all_global_dbs = list({(n.name, n.node_type): n for n in all_global_dbs}.values())

        # Create output node
        first_assign = output_assignments[0]
        output_node = DependencyNode(
            name=output_name,
            node_type=NodeType.OUTPUT,
            data_type=var_info.data_type,
            source_location=first_assign.source_location,
        )

        return OutputDependencyTree(
            output=output_node,
            expression_tree=expanded_expr,
            all_inputs=all_inputs,
            all_states=all_states,
            all_constants=all_constants,
            all_global_dbs=all_global_dbs,
            intermediate_vars=intermediate_vars,
        )

    def _combine_assignments(self, assignments: list[Assignment]) -> LogicExpression:
        """Combine multiple assignments into a single expression.

        If there are multiple assignments (e.g., in different CASE branches),
        they are combined with OR since any path could produce the output.

        Parameters
        ----------
        assignments : list[Assignment]
            List of assignments to the same target.

        Returns
        -------
        LogicExpression
            Combined expression.
        """
        if len(assignments) == 1:
            assignment = assignments[0]
            expr = assignment.expression

            # Add enclosing condition if present
            if assignment.enclosing_condition:
                return LogicExpression(
                    operator=OperatorType.IF_THEN,
                    operands=[expr],
                    condition=assignment.enclosing_condition,
                    source_location=assignment.source_location,
                )

            # Add case context if present
            if assignment.case_context:
                return LogicExpression(
                    operator=OperatorType.CASE_WHEN,
                    operands=[expr],
                    case_value=assignment.case_context,
                    source_location=assignment.source_location,
                )

            return expr

        # Multiple assignments - combine with OR
        exprs: list[LogicExpression | DependencyNode] = []
        for assignment in assignments:
            expr = assignment.expression

            # Wrap with condition if present
            if assignment.enclosing_condition:
                expr = LogicExpression(
                    operator=OperatorType.IF_THEN,
                    operands=[expr],
                    condition=assignment.enclosing_condition,
                    source_location=assignment.source_location,
                )
            elif assignment.case_context:
                expr = LogicExpression(
                    operator=OperatorType.CASE_WHEN,
                    operands=[expr],
                    case_value=assignment.case_context,
                    source_location=assignment.source_location,
                )

            exprs.append(expr)

        return LogicExpression(
            operator=OperatorType.OR,
            operands=exprs,
        )

    def _expand_dependencies(
        self,
        expr: LogicExpression,
        visited: set[str],
        intermediate_vars: list[str],
    ) -> LogicExpression:
        """Expand state variable references to their definitions.

        Parameters
        ----------
        expr : LogicExpression
            Expression to expand.
        visited : set[str]
            Already visited variables (for cycle detection).
        intermediate_vars : list[str]
            List to collect intermediate variable names.

        Returns
        -------
        LogicExpression
            Expanded expression.
        """
        # If this is an IDENTITY with a single DependencyNode
        if expr.is_terminal():
            node = expr.get_terminal_node()
            if node and node.node_type == NodeType.STATE:
                # Check if we have assignments for this state variable
                if node.name not in visited and node.name in self.assignments_by_target:
                    visited.add(node.name)
                    intermediate_vars.append(node.name)

                    # Get assignments and combine
                    state_assignments = self.assignments_by_target[node.name]
                    combined = self._combine_assignments(state_assignments)

                    # Recursively expand
                    return self._expand_dependencies(combined, visited, intermediate_vars)

            # No expansion needed
            return expr

        # Expand operands recursively
        new_operands: list[LogicExpression | DependencyNode] = []
        for operand in expr.operands:
            if isinstance(operand, DependencyNode):
                # Wrap in IDENTITY and expand
                wrapped = LogicExpression(
                    operator=OperatorType.IDENTITY,
                    operands=[operand],
                )
                expanded = self._expand_dependencies(wrapped, visited.copy(), intermediate_vars)
                new_operands.append(expanded)
            else:
                expanded = self._expand_dependencies(operand, visited.copy(), intermediate_vars)
                new_operands.append(expanded)

        # Expand condition if present
        new_condition = None
        if expr.condition:
            new_condition = self._expand_dependencies(expr.condition, visited.copy(), intermediate_vars)

        return LogicExpression(
            operator=expr.operator,
            operands=new_operands,
            condition=new_condition,
            case_value=expr.case_value,
            source_location=expr.source_location,
        )


def build_all_output_trees(deps: BlockDependencies) -> dict[str, OutputDependencyTree]:
    """Build dependency trees for all outputs in a block.

    Parameters
    ----------
    deps : BlockDependencies
        Extracted block dependencies.

    Returns
    -------
    dict[str, OutputDependencyTree]
        Mapping from output name to its dependency tree.
    """
    builder = DependencyGraphBuilder(deps)
    trees: dict[str, OutputDependencyTree] = {}

    # Find all output variables
    for name, var_info in deps.variables.items():
        if var_info.node_type == NodeType.OUTPUT:
            tree = builder.build_output_tree(name)
            if tree:
                trees[name] = tree

    return trees


def get_input_dependencies(tree: OutputDependencyTree) -> list[str]:
    """Get list of input variable names that an output depends on.

    Parameters
    ----------
    tree : OutputDependencyTree
        The dependency tree.

    Returns
    -------
    list[str]
        Sorted list of input variable names.
    """
    return sorted(node.name for node in tree.all_inputs)


def get_dependency_summary(tree: OutputDependencyTree) -> dict[str, list[str]]:
    """Get a summary of all dependencies by type.

    Parameters
    ----------
    tree : OutputDependencyTree
        The dependency tree.

    Returns
    -------
    dict[str, list[str]]
        Mapping from type name to list of variable names.
    """
    return {
        "inputs": sorted(n.name for n in tree.all_inputs),
        "states": sorted(n.name for n in tree.all_states),
        "constants": sorted(n.name for n in tree.all_constants),
        "global_dbs": sorted(n.name for n in tree.all_global_dbs),
        "intermediate": sorted(tree.intermediate_vars),
    }
