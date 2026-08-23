"""Mermaid diagram generator for logic dependency trees.

This module generates Mermaid flowchart diagrams from OutputDependencyTree
structures, showing the logical flow from inputs to outputs with gates.

Node shapes by type:
- Input: ([stadium])
- Output: [[subroutine]]
- State: [/parallelogram/]
- Constant: {{hexagon}}
- Global DB: [(cylinder)]
- Logic gate: {diamond}
"""

from .models import (
    DependencyNode,
    LogicExpression,
    NodeType,
    OperatorType,
    OutputDependencyTree,
    SourceLocation,
)


class MermaidGenerator:
    """Generates Mermaid flowchart diagrams for dependency trees."""

    # Node shape templates by type
    NODE_SHAPES = {
        NodeType.INPUT: '(["{label}"])',
        NodeType.OUTPUT: '[["{label}"]]',
        NodeType.STATE: '[/"{label}"/]',
        NodeType.CONSTANT: '{{"{label}"}}',
        NodeType.GLOBAL_DB: '[("`{label}`")]',
        NodeType.IN_OUT: '(["{label}"])',
        NodeType.TEMP: '["{label}"]',
        NodeType.TIMER: '(("{label}"))',
        NodeType.FUNCTION_CALL: ">{label}]",
        NodeType.UNKNOWN: '["{label}"]',
    }

    # Gate labels
    GATE_LABELS = {
        OperatorType.AND: "AND",
        OperatorType.OR: "OR",
        OperatorType.NOT: "NOT",
        OperatorType.XOR: "XOR",
        OperatorType.COMPARE_EQ: "=",
        OperatorType.COMPARE_NE: "<>",
        OperatorType.COMPARE_LT: "<",
        OperatorType.COMPARE_GT: ">",
        OperatorType.COMPARE_LE: "<=",
        OperatorType.COMPARE_GE: ">=",
        OperatorType.IF_THEN: "IF",
        OperatorType.CASE_WHEN: "CASE",
        OperatorType.ADD: "+",
        OperatorType.SUBTRACT: "-",
        OperatorType.MULTIPLY: "*",
        OperatorType.DIVIDE: "/",
        OperatorType.MODULO: "MOD",
        OperatorType.POWER: "**",
        OperatorType.NEGATE: "-",
        OperatorType.INDEX: "INDEX",
    }

    def __init__(self, include_click_links: bool = True, base_path: str = "") -> None:
        """Initialize generator.

        Parameters
        ----------
        include_click_links : bool
            Whether to include click links to source code.
        base_path : str
            Base path for relative links.
        """
        self.include_click_links = include_click_links
        self.base_path = base_path
        self.node_counter = 0
        self.node_ids: dict[tuple[str, NodeType], str] = {}  # (name, type) -> mermaid node id
        self.expression_ids: dict[int, str] = {}  # id(expression) -> mermaid node id
        self.lines: list[str] = []
        self.click_links: list[str] = []

    def generate(self, tree: OutputDependencyTree, direction: str = "LR") -> str:
        """Generate Mermaid flowchart for a dependency tree.

        Parameters
        ----------
        tree : OutputDependencyTree
            The dependency tree to visualize.
        direction : str
            Flowchart direction (LR, RL, TB, BT).

        Returns
        -------
        str
            Mermaid flowchart code.
        """
        self.node_counter = 0
        self.node_ids = {}
        self.expression_ids = {}
        self.lines = []
        self.click_links = []

        # Start flowchart
        self.lines.append(f"flowchart {direction}")

        # Generate output node
        output_id = self._new_node_id("out")
        output_label = f"Output: {tree.output.name}"
        self.lines.append(f'    {output_id}[["{output_label}"]]')

        if tree.output.source_location.file_path:
            self._add_click_link(output_id, tree.output.source_location)

        # Generate expression tree
        expr_id = self._generate_expression(tree.expression_tree)

        # Connect expression to output
        self.lines.append(f"    {expr_id} --> {output_id}")

        # Add click links
        if self.include_click_links and self.click_links:
            self.lines.append("")
            self.lines.extend(self.click_links)

        # Add styling
        self.lines.append("")
        self._add_styles()

        return "\n".join(self.lines)

    def _new_node_id(self, prefix: str = "n") -> str:
        """Generate a new unique node ID."""
        self.node_counter += 1
        return f"{prefix}_{self.node_counter}"

    def _generate_expression(self, expr: LogicExpression) -> str:
        """Generate nodes for an expression and return its node ID.

        Parameters
        ----------
        expr : LogicExpression
            The expression to generate.

        Returns
        -------
        str
            The Mermaid node ID for this expression.
        """
        # Check if this is a terminal (single node)
        if expr.is_terminal():
            node = expr.get_terminal_node()
            if node:
                return self._generate_dependency_node(node)

        # Check if IDENTITY with expression operand
        if expr.operator == OperatorType.IDENTITY and len(expr.operands) == 1:
            operand = expr.operands[0]
            if isinstance(operand, DependencyNode):
                return self._generate_dependency_node(operand)
            else:
                return self._generate_expression(operand)

        # A subtree the graph builder shares between references is drawn once.
        if id(expr) in self.expression_ids:
            return self.expression_ids[id(expr)]

        # Generate gate node
        gate_id = self._new_node_id("op")
        self.expression_ids[id(expr)] = gate_id
        gate_label = self.GATE_LABELS.get(expr.operator, expr.operator.value)

        # Add case value annotation
        if expr.operator == OperatorType.CASE_WHEN and expr.case_value:
            gate_label = f"CASE {expr.case_value}"

        self.lines.append(f'    {gate_id}{{"{gate_label}"}}')

        if expr.source_location.file_path:
            self._add_click_link(gate_id, expr.source_location)

        # Generate operands and connect
        for operand in expr.operands:
            if isinstance(operand, DependencyNode):
                operand_id = self._generate_dependency_node(operand)
            else:
                operand_id = self._generate_expression(operand)
            self.lines.append(f"    {operand_id} --> {gate_id}")

        # Generate condition if present (for IF_THEN)
        if expr.condition:
            cond_id = self._generate_expression(expr.condition)
            self.lines.append(f"    {cond_id} -.->|condition| {gate_id}")

        return gate_id

    def _generate_dependency_node(self, node: DependencyNode) -> str:
        """Generate a dependency node.

        Parameters
        ----------
        node : DependencyNode
            The node to generate.

        Returns
        -------
        str
            The Mermaid node ID.
        """
        # Check if we already generated this node
        node_key = (node.name, node.node_type)
        if node_key in self.node_ids:
            return self.node_ids[node_key]

        # Generate new node
        prefix = self._get_node_prefix(node.node_type)
        node_id = self._new_node_id(prefix)

        # Format label
        label = self._format_node_label(node)

        # Get shape template
        shape = self.NODE_SHAPES.get(node.node_type, '["{label}"]')
        node_def = shape.format(label=label)

        self.lines.append(f"    {node_id}{node_def}")

        if node.source_location.file_path:
            self._add_click_link(node_id, node.source_location)

        # Cache for reuse
        self.node_ids[node_key] = node_id

        return node_id

    def _get_node_prefix(self, node_type: NodeType) -> str:
        """Get node ID prefix for a type."""
        prefixes = {
            NodeType.INPUT: "in",
            NodeType.OUTPUT: "out",
            NodeType.STATE: "st",
            NodeType.CONSTANT: "const",
            NodeType.GLOBAL_DB: "db",
            NodeType.IN_OUT: "io",
            NodeType.TEMP: "tmp",
            NodeType.TIMER: "tmr",
            NodeType.FUNCTION_CALL: "fn",
        }
        return prefixes.get(node_type, "n")

    def _format_node_label(self, node: DependencyNode) -> str:
        """Format a node label for display."""
        type_prefix = {
            NodeType.INPUT: "Input",
            NodeType.OUTPUT: "Output",
            NodeType.STATE: "State",
            NodeType.CONSTANT: "",
            NodeType.GLOBAL_DB: "DB",
            NodeType.IN_OUT: "InOut",
            NodeType.TEMP: "Temp",
            NodeType.TIMER: "Timer",
            NodeType.FUNCTION_CALL: "Call",
        }

        prefix = type_prefix.get(node.node_type, "")

        # Shorten global DB references
        name = node.name
        if node.node_type == NodeType.GLOBAL_DB:
            # Extract just the relevant parts
            parts = name.replace('"', "").split(".")
            if len(parts) > 2:
                name = f"{parts[0]}.{parts[-1]}"

        if prefix:
            return f"{prefix}: {name}"
        return name

    def _add_click_link(self, node_id: str, location: "SourceLocation") -> None:
        """Add a click link to source code."""
        if not self.include_click_links:
            return

        # Format as file:line
        from pathlib import Path

        filename = Path(location.file_path).name
        link = f"{filename}:{location.line_number}"

        # Use callback format for click
        self.click_links.append(f'    click {node_id} "{link}"')

    def _add_styles(self) -> None:
        """Add CSS styles for different node types."""
        self.lines.append("    %% Styling")
        self.lines.append("    classDef input fill:#90EE90,stroke:#228B22")
        self.lines.append("    classDef output fill:#87CEEB,stroke:#4169E1")
        self.lines.append("    classDef state fill:#DDA0DD,stroke:#8B008B")
        self.lines.append("    classDef constant fill:#F0E68C,stroke:#DAA520")
        self.lines.append("    classDef globaldb fill:#FFA07A,stroke:#CD5C5C")
        self.lines.append("    classDef gate fill:#E6E6FA,stroke:#9370DB")


def generate_dependency_diagram(
    tree: OutputDependencyTree,
    direction: str = "LR",
    include_click_links: bool = True,
) -> str:
    """Generate a Mermaid diagram for a dependency tree.

    Parameters
    ----------
    tree : OutputDependencyTree
        The dependency tree to visualize.
    direction : str
        Flowchart direction (LR, RL, TB, BT).
    include_click_links : bool
        Whether to include click links to source code.

    Returns
    -------
    str
        Mermaid flowchart code.
    """
    generator = MermaidGenerator(include_click_links)
    return generator.generate(tree, direction)


def generate_simplified_diagram(tree: OutputDependencyTree, direction: str = "LR") -> str:
    """Generate a simplified diagram showing only inputs and output.

    This omits intermediate logic gates for a cleaner view.

    Parameters
    ----------
    tree : OutputDependencyTree
        The dependency tree.
    direction : str
        Flowchart direction.

    Returns
    -------
    str
        Mermaid flowchart code.
    """
    lines = [f"flowchart {direction}"]

    # Output node
    lines.append(f'    out_1[["Output: {tree.output.name}"]]')

    # Input nodes
    for i, input_node in enumerate(tree.all_inputs, 1):
        lines.append(f'    in_{i}(["{input_node.name}"])')
        lines.append(f"    in_{i} --> out_1")

    # State nodes (as intermediates)
    for i, state_node in enumerate(tree.all_states, 1):
        lines.append(f'    st_{i}[/"State: {state_node.name}"/]')
        lines.append(f"    st_{i} --> out_1")

    # Constant nodes
    for i, const_node in enumerate(tree.all_constants, 1):
        lines.append(f'    const_{i}{{"{const_node.name}"}}')
        lines.append(f"    const_{i} --> out_1")

    # Global DB nodes
    for i, db_node in enumerate(tree.all_global_dbs, 1):
        short_name = db_node.name.replace('"', "").split(".")[-1]
        lines.append(f'    db_{i}[("`{short_name}`")]')
        lines.append(f"    db_{i} --> out_1")

    return "\n".join(lines)


def generate_block_summary_diagram(
    block_name: str,
    output_trees: dict[str, OutputDependencyTree],
    direction: str = "TB",
) -> str:
    """Generate a summary diagram for all outputs in a block.

    Shows each output with its direct input dependencies.

    Parameters
    ----------
    block_name : str
        Name of the block.
    output_trees : dict[str, OutputDependencyTree]
        All output dependency trees.
    direction : str
        Flowchart direction.

    Returns
    -------
    str
        Mermaid flowchart code.
    """
    lines = [f"flowchart {direction}"]
    lines.append(f"    subgraph {block_name}")

    # Collect all unique inputs
    all_inputs: dict[str, DependencyNode] = {}
    for tree in output_trees.values():
        for node in tree.all_inputs:
            all_inputs[node.name] = node

    # Generate input nodes
    for i, (name, _node) in enumerate(sorted(all_inputs.items()), 1):
        lines.append(f'    in_{i}(["{name}"])')

    # Generate output nodes with connections
    for i, (output_name, tree) in enumerate(sorted(output_trees.items()), 1):
        lines.append(f'    out_{i}[["{output_name}"]]')

        # Connect inputs to this output
        for j, (name, _) in enumerate(sorted(all_inputs.items()), 1):
            if any(n.name == name for n in tree.all_inputs):
                lines.append(f"    in_{j} --> out_{i}")

    lines.append("    end")

    return "\n".join(lines)
