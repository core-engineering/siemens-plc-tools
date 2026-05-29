"""Generate Mermaid diagrams for type dependency graphs.

This module provides functionality to generate Mermaid flowchart diagrams
from type dependency graphs for documentation visualization.
"""

from plc_code.analyzer.type_graph import TypeComponent, TypeGraph


def _safe_id(name: str) -> str:
    """Convert a type name to a safe Mermaid node ID.

    Parameters
    ----------
    name : str
        The type name.

    Returns
    -------
    str
        A safe identifier for use in Mermaid diagrams.
    """
    # Replace characters that might cause issues in Mermaid
    return name.replace("-", "_").replace(".", "_").replace(" ", "_")


def generate_type_mermaid_flowchart(
    graph: TypeGraph,
    direction: str = "LR",
    include_click_links: bool = True,
) -> str:
    """Generate a Mermaid flowchart from a type dependency graph.

    Parameters
    ----------
    graph : TypeGraph
        The type dependency graph.
    direction : str
        Flowchart direction (TB, BT, LR, RL). Default is LR (left to right).
    include_click_links : bool
        Whether to include click links for navigation.

    Returns
    -------
    str
        Mermaid flowchart code.
    """
    if not graph.nodes:
        return ""

    lines = [f"flowchart {direction}"]

    # Add nodes with labels (skip empty names)
    for node in graph.nodes.values():
        if not node.name:
            continue
        node_id = _safe_id(node.name)
        lines.append(f'    {node_id}["{node.name}"]')

    # Add edges (dependency arrows: source depends on target)
    for edge in graph.edges:
        source_id = _safe_id(edge.source)
        target_id = _safe_id(edge.target)
        # Skip edges with empty source or target
        if not edge.source or not edge.target:
            continue
        # Arrow points from dependent to dependency
        # (source uses target, so arrow goes source --> target)
        # Include field name as label (with array indicator if applicable)
        if edge.is_array:
            # Use text indicator instead of [] which can cause Mermaid issues
            label = f"{edge.field_name} array"
        else:
            label = edge.field_name
        lines.append(f'    {source_id} -->|"{label}"| {target_id}')

    # Add click links (skip empty names)
    if include_click_links:
        lines.append("")
        for node in graph.nodes.values():
            if node.doc_path and node.name:
                node_id = _safe_id(node.name)
                # Use absolute path from site root for Mermaid click events
                doc_link = "/" + node.doc_path.replace(".md", "/")
                tooltip = f"View {node.name} documentation"
                lines.append(f'    click {node_id} "{doc_link}" "{tooltip}"')

    # Add styling
    lines.append("")
    lines.append("    %% Styling")
    lines.append("    classDef udt fill:#e8f5e9,stroke:#388e3c,stroke-width:2px")

    # Apply styles to all nodes (skip empty names)
    valid_names = [name for name in graph.nodes.keys() if name]
    if valid_names:
        node_ids = ",".join(_safe_id(name) for name in valid_names)
        lines.append(f"    class {node_ids} udt")

    return "\n".join(lines)


def generate_type_component_flowchart(
    component: TypeComponent,
    direction: str = "LR",
    include_click_links: bool = True,
) -> str:
    """Generate a Mermaid flowchart for a type component.

    Parameters
    ----------
    component : TypeComponent
        The connected component to visualize.
    direction : str
        Flowchart direction.
    include_click_links : bool
        Whether to include click links.

    Returns
    -------
    str
        Mermaid flowchart code.
    """
    if not component.nodes:
        return ""

    # Build a mini graph for this component
    graph = TypeGraph()
    for node in component.nodes:
        graph.nodes[node.name] = node
    graph.edges = list(component.edges)

    return generate_type_mermaid_flowchart(graph, direction, include_click_links)
