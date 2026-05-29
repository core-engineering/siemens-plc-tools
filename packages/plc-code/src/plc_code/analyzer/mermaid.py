"""Generate Mermaid diagrams from call graphs.

This module provides functionality to generate interactive Mermaid flowcharts
from call graphs, with clickable nodes that link to documentation pages.
"""

from plc_code.analyzer.models import BlockNode, CallGraph, ConnectedComponent


def generate_mermaid_flowchart(
    graph: CallGraph | ConnectedComponent,
    direction: str = "TB",
    include_click_links: bool = True,
    base_path: str = "",
    title: str | None = None,
) -> str:
    """Generate a Mermaid flowchart from a call graph or component.

    Parameters
    ----------
    graph : CallGraph | ConnectedComponent
        The graph or component to render.
    direction : str
        Flowchart direction: TB (top-bottom), LR (left-right),
        BT (bottom-top), RL (right-left). Default is TB.
    include_click_links : bool
        Whether to include click links to documentation pages.
    base_path : str
        Base path prefix for documentation links.
    title : str | None
        Optional title to display above the graph.

    Returns
    -------
    str
        Mermaid flowchart code (without fence markers).
    """
    lines: list[str] = []

    # Start flowchart
    lines.append(f"flowchart {direction}")

    if not graph.nodes:
        lines.append("    empty[No blocks found]")
        return "\n".join(lines)

    # Group nodes by category for subgraphs
    categories: dict[str, list[BlockNode]] = {}
    for node in graph.nodes.values():
        category = node.category or "Other"
        if category not in categories:
            categories[category] = []
        categories[category].append(node)

    # Generate nodes (with optional subgraphs for categories)
    if len(categories) > 1:
        for category, nodes in sorted(categories.items()):
            # Create subgraph for each category
            safe_category = _safe_id(category)
            lines.append(f"    subgraph {safe_category}[{category}]")
            for node in sorted(nodes, key=lambda n: n.name):
                node_def = _format_node(node)
                lines.append(f"        {node_def}")
            lines.append("    end")
    else:
        # No subgraphs - just list nodes
        for node in sorted(graph.nodes.values(), key=lambda n: n.name):
            node_def = _format_node(node)
            lines.append(f"    {node_def}")

    # Generate edges
    seen_edges: set[tuple[str, str]] = set()
    for edge in graph.edges:
        edge_key = (edge.caller, edge.callee)
        if edge_key not in seen_edges:
            seen_edges.add(edge_key)
            caller_id = _safe_id(edge.caller)
            callee_id = _safe_id(edge.callee)
            lines.append(f"    {caller_id} --> {callee_id}")

    # Add click links
    if include_click_links:
        lines.append("")
        for node in graph.nodes.values():
            if node.doc_path:
                node_id = _safe_id(node.name)
                # Use absolute path from site root for Mermaid click events
                # Convert .md to / for MkDocs URLs
                doc_link = "/" + node.doc_path.replace(".md", "/")
                tooltip = f"View {node.name} documentation"
                lines.append(f'    click {node_id} "{doc_link}" "{tooltip}"')

    # Add styling
    lines.append("")
    lines.append("    %% Styling")
    lines.append("    classDef fb fill:#e3f2fd,stroke:#1976d2,stroke-width:2px")
    lines.append("    classDef fc fill:#fff3e0,stroke:#f57c00,stroke-width:2px")
    lines.append("    classDef ob fill:#e8f5e9,stroke:#388e3c,stroke-width:2px")

    # Apply styles to nodes
    fb_nodes = [_safe_id(n.name) for n in graph.nodes.values() if n.block_type == "FUNCTION_BLOCK"]
    fc_nodes = [_safe_id(n.name) for n in graph.nodes.values() if n.block_type == "FUNCTION"]
    ob_nodes = [_safe_id(n.name) for n in graph.nodes.values() if n.block_type == "ORGANIZATION_BLOCK"]

    if fb_nodes:
        lines.append(f"    class {','.join(fb_nodes)} fb")
    if fc_nodes:
        lines.append(f"    class {','.join(fc_nodes)} fc")
    if ob_nodes:
        lines.append(f"    class {','.join(ob_nodes)} ob")

    return "\n".join(lines)


def generate_legend_block(
    graph: CallGraph | ConnectedComponent,
) -> str:
    """Generate a standalone legend as a Mermaid code block.

    The legend shows the block types present in the graph with their
    corresponding shapes and colors.

    Parameters
    ----------
    graph : CallGraph | ConnectedComponent
        The graph to generate a legend for.

    Returns
    -------
    str
        Complete Mermaid code block with legend, or empty string if no nodes.
    """
    if not graph.nodes:
        return ""

    # Determine which block types are present
    has_fb = any(n.block_type == "FUNCTION_BLOCK" for n in graph.nodes.values())
    has_fc = any(n.block_type == "FUNCTION" for n in graph.nodes.values())
    has_ob = any(n.block_type == "ORGANIZATION_BLOCK" for n in graph.nodes.values())

    if not (has_fb or has_fc or has_ob):
        return ""

    legend_lines = _generate_legend(has_fb=has_fb, has_fc=has_fc, has_ob=has_ob)
    if not legend_lines:
        return ""

    # Build a minimal flowchart with just the legend
    lines: list[str] = []
    lines.append("```mermaid")
    lines.append("flowchart LR")

    # Add legend items (remove the leading spaces and subgraph wrapper)
    legend_nodes: list[str] = []
    if has_ob:
        lines.append('    leg_ob(["OB: Organization Block"])')
        legend_nodes.append("leg_ob")
    if has_fb:
        lines.append('    leg_fb["FB: Function Block"]')
        legend_nodes.append("leg_fb")
    if has_fc:
        lines.append('    leg_fc(["FC: Function"])')
        legend_nodes.append("leg_fc")

    # Add invisible links to force horizontal alignment
    if len(legend_nodes) > 1:
        lines.append(f"    {' ~~~ '.join(legend_nodes)}")

    # Add styling
    lines.append("")
    lines.append("    %% Styling")
    lines.append("    classDef fb fill:#e3f2fd,stroke:#1976d2,stroke-width:2px")
    lines.append("    classDef fc fill:#fff3e0,stroke:#f57c00,stroke-width:2px")
    lines.append("    classDef ob fill:#e8f5e9,stroke:#388e3c,stroke-width:2px")

    if has_fb:
        lines.append("    class leg_fb fb")
    if has_fc:
        lines.append("    class leg_fc fc")
    if has_ob:
        lines.append("    class leg_ob ob")

    lines.append("```")

    return "\n".join(lines)


def generate_mermaid_block(
    graph: CallGraph | ConnectedComponent,
    direction: str = "TB",
    include_click_links: bool = True,
    base_path: str = "",
    title: str | None = None,
) -> str:
    """Generate a complete Mermaid code block with fences.

    Parameters
    ----------
    graph : CallGraph | ConnectedComponent
        The graph or component to render.
    direction : str
        Flowchart direction.
    include_click_links : bool
        Whether to include click links.
    base_path : str
        Base path prefix for documentation links.
    title : str | None
        Optional title.

    Returns
    -------
    str
        Complete Mermaid code block with ``` fences.
    """
    flowchart = generate_mermaid_flowchart(
        graph,
        direction=direction,
        include_click_links=include_click_links,
        base_path=base_path,
        title=title,
    )
    return f"```mermaid\n{flowchart}\n```"


def generate_block_dependency_diagram(
    graph: CallGraph,
    block_name: str,
    direction: str = "LR",
    include_click_links: bool = True,
    base_path: str = "",
) -> str:
    """Generate a focused dependency diagram for a specific block.

    Shows the block, what it calls, and what calls it.

    Parameters
    ----------
    graph : CallGraph
        The complete call graph.
    block_name : str
        Name of the block to focus on.
    direction : str
        Flowchart direction.
    include_click_links : bool
        Whether to include click links.
    base_path : str
        Base path prefix for documentation links.

    Returns
    -------
    str
        Mermaid flowchart code (without fences).
    """
    node = graph.get_node(block_name)
    if not node:
        return f"flowchart {direction}\n    notfound[Block '{block_name}' not found]"

    lines: list[str] = []
    lines.append(f"flowchart {direction}")

    # Collect relevant nodes
    relevant_nodes: dict[str, BlockNode] = {block_name: node}

    # Add callers (what calls this block)
    for caller_name in node.called_by:
        caller_node = graph.get_node(caller_name)
        if caller_node:
            relevant_nodes[caller_name] = caller_node

    # Add callees (what this block calls)
    for callee_name in node.calls:
        callee_node = graph.get_node(callee_name)
        if callee_node:
            relevant_nodes[callee_name] = callee_node

    # Generate subgraphs for organization
    if node.called_by:
        lines.append("    subgraph Callers[Called By]")
        for caller_name in sorted(node.called_by):
            caller_node = relevant_nodes.get(caller_name)
            if caller_node:
                lines.append(f"        {_format_node(caller_node)}")
        lines.append("    end")

    # Center block
    lines.append("    subgraph Current[Current Block]")
    lines.append(f"        {_format_node(node)}")
    lines.append("    end")

    if node.calls:
        lines.append("    subgraph Callees[Calls]")
        for callee_name in sorted(node.calls):
            callee_node = relevant_nodes.get(callee_name)
            if callee_node:
                lines.append(f"        {_format_node(callee_node)}")
        lines.append("    end")

    # Generate edges
    block_id = _safe_id(block_name)

    for caller_name in node.called_by:
        if caller_name in relevant_nodes:
            caller_id = _safe_id(caller_name)
            lines.append(f"    {caller_id} --> {block_id}")

    for callee_name in node.calls:
        if callee_name in relevant_nodes:
            callee_id = _safe_id(callee_name)
            lines.append(f"    {block_id} --> {callee_id}")

    # Add click links
    if include_click_links:
        lines.append("")
        for rel_node in relevant_nodes.values():
            if rel_node.doc_path:
                node_id = _safe_id(rel_node.name)
                doc_link = _compute_link_path(rel_node.doc_path, base_path)
                tooltip = f"View {rel_node.name} documentation"
                lines.append(f'    click {node_id} "{doc_link}" "{tooltip}"')

    # Styling
    lines.append("")
    lines.append("    %% Styling")
    lines.append("    classDef fb fill:#e3f2fd,stroke:#1976d2,stroke-width:2px")
    lines.append("    classDef fc fill:#fff3e0,stroke:#f57c00,stroke-width:2px")
    lines.append("    classDef current fill:#c8e6c9,stroke:#388e3c,stroke-width:3px")

    fb_nodes = [
        _safe_id(n.name)
        for n in relevant_nodes.values()
        if n.block_type == "FUNCTION_BLOCK" and n.name != block_name
    ]
    fc_nodes = [
        _safe_id(n.name)
        for n in relevant_nodes.values()
        if n.block_type == "FUNCTION" and n.name != block_name
    ]

    if fb_nodes:
        lines.append(f"    class {','.join(fb_nodes)} fb")
    if fc_nodes:
        lines.append(f"    class {','.join(fc_nodes)} fc")

    # Current block gets special styling
    lines.append(f"    class {block_id} current")

    return "\n".join(lines)


def _format_node(node: BlockNode, max_label_width: int = 25) -> str:
    """Format a node definition for Mermaid.

    Parameters
    ----------
    node : BlockNode
        The node to format.
    max_label_width : int
        Maximum characters per line before wrapping. Default is 25.

    Returns
    -------
    str
        Mermaid node definition.
    """
    node_id = _safe_id(node.name)
    label = _wrap_label(node.name, max_label_width)

    # Use rounded rectangle for FB, stadium for FC
    if node.block_type == "FUNCTION_BLOCK":
        return f'{node_id}["{label}"]'
    else:
        return f'{node_id}(["{label}"])'


def _generate_legend(
    has_fb: bool = True,
    has_fc: bool = True,
    has_ob: bool = True,
) -> list[str]:
    """Generate a legend subgraph for the diagram.

    Parameters
    ----------
    has_fb : bool
        Include Function Block in legend.
    has_fc : bool
        Include Function in legend.
    has_ob : bool
        Include Organization Block in legend.

    Returns
    -------
    list[str]
        Lines for the legend subgraph.
    """
    # Only show legend if there's at least one block type
    if not (has_fb or has_fc or has_ob):
        return []

    lines: list[str] = []
    lines.append("")
    lines.append("    %% Legend")
    lines.append("    subgraph Legend[ ]")

    if has_ob:
        lines.append('        leg_ob(["OB: Organization Block"])')
    if has_fb:
        lines.append('        leg_fb["FB: Function Block"]')
    if has_fc:
        lines.append('        leg_fc(["FC: Function"])')

    lines.append("    end")

    # Apply styles to legend nodes
    if has_fb:
        lines.append("    class leg_fb fb")
    if has_fc:
        lines.append("    class leg_fc fc")
    if has_ob:
        lines.append("    class leg_ob ob")

    return lines


def _wrap_label(text: str, max_width: int) -> str:
    """Wrap long labels with line breaks for Mermaid.

    Parameters
    ----------
    text : str
        The label text.
    max_width : int
        Maximum characters per line.

    Returns
    -------
    str
        Label with <br/> tags for line breaks if needed.
    """
    if len(text) <= max_width:
        return text

    # Try to break at underscores or camelCase boundaries
    parts: list[str] = []
    current_line = ""

    # Split by underscores first
    segments = text.split("_")

    for i, segment in enumerate(segments):
        separator = "_" if i > 0 else ""
        test_line = current_line + separator + segment

        if len(test_line) <= max_width:
            current_line = test_line
        else:
            if current_line:
                parts.append(current_line)
            current_line = segment

    if current_line:
        parts.append(current_line)

    return "<br/>".join(parts)


def _safe_id(name: str) -> str:
    """Convert a block name to a safe Mermaid node ID.

    Parameters
    ----------
    name : str
        The block name.

    Returns
    -------
    str
        Safe node ID (alphanumeric with underscores).
    """
    # Replace non-alphanumeric characters with underscores
    safe = "".join(c if c.isalnum() else "_" for c in name)
    # Ensure it starts with a letter
    if safe and not safe[0].isalpha():
        safe = "N" + safe
    return safe


def _compute_link_path(doc_path: str, base_path: str) -> str:
    """Compute the relative link path from base to target.

    Parameters
    ----------
    doc_path : str
        Path to the target documentation file.
    base_path : str
        Path of the current file (for computing relative path).

    Returns
    -------
    str
        Relative path from base to doc.
    """
    if not base_path:
        return doc_path

    # Simple relative path computation
    # Both paths should be relative to docs root
    from pathlib import PurePosixPath

    doc = PurePosixPath(doc_path)
    base = PurePosixPath(base_path)

    # Find common ancestor
    doc_parts = list(doc.parts)
    base_parts = list(base.parent.parts)  # Parent because base is a file

    # Find common prefix length
    common_length = 0
    for d, b in zip(doc_parts, base_parts, strict=False):
        if d == b:
            common_length += 1
        else:
            break

    # Go up from base to common ancestor
    ups = len(base_parts) - common_length
    up_path = "../" * ups

    # Go down from common ancestor to doc
    down_path = "/".join(doc_parts[common_length:])

    return up_path + down_path
