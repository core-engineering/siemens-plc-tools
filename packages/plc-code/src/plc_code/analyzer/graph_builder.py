"""Build call graphs from parsed SCL blocks.

This module provides functionality to construct call graphs from a collection
of parsed blocks, including detection of connected components (independent
call graphs).
"""

from collections import deque
from pathlib import Path

from plc_code.analyzer.call_extractor import extract_calls
from plc_code.analyzer.models import BlockNode, CallGraph, CallReference, ConnectedComponent
from plc_code.parser.models import Block


def build_call_graph(
    blocks: list[Block],
    doc_paths: dict[str, str] | None = None,
    categories: dict[str, tuple[str, str]] | None = None,
) -> CallGraph:
    """Build a complete call graph from a list of parsed blocks.

    This function:
    1. Creates nodes for all FB and FC blocks
    2. Extracts calls from each block
    3. Resolves call targets and builds edges
    4. Computes bidirectional relationships (calls/called_by)

    Parameters
    ----------
    blocks : list[Block]
        List of parsed blocks to analyze.
    doc_paths : dict[str, str] | None
        Optional mapping from block name to documentation path.
    categories : dict[str, tuple[str, str]] | None
        Optional mapping from block name to (category, subcategory).

    Returns
    -------
    CallGraph
        The complete call graph.
    """
    graph = CallGraph()
    doc_paths = doc_paths or {}
    categories = categories or {}

    # First pass: Create nodes for all blocks
    block_map: dict[str, Block] = {}
    for block in blocks:
        # Only include FB, FC, and OB - not TYPE blocks
        if block.block_type in ("FUNCTION_BLOCK", "FUNCTION", "ORGANIZATION_BLOCK"):
            block_map[block.name] = block

            category, subcategory = categories.get(block.name, ("", ""))

            node = BlockNode(
                name=block.name,
                block_type=block.block_type,
                file_path=Path(block.source_file) if block.source_file else None,
                doc_path=doc_paths.get(block.name, ""),
                category=category,
                subcategory=subcategory,
            )
            graph.add_node(node)

    # Second pass: Extract calls and build edges
    for block in blocks:
        if block.block_type not in ("FUNCTION_BLOCK", "FUNCTION", "ORGANIZATION_BLOCK"):
            continue

        calls = extract_calls(block)

        for call in calls:
            # Try to resolve the callee name
            resolved_callee = _resolve_idb_name(call.callee, graph.nodes)

            # Only add edge if callee exists in our graph
            # (filters out calls to external/unknown blocks)
            if resolved_callee in graph.nodes:
                # Update the call reference with resolved name
                resolved_call = CallReference(
                    caller=call.caller,
                    callee=resolved_callee,
                    instance_name=call.instance_name,
                    call_type=call.call_type,
                    line_number=call.line_number,
                )
                graph.add_edge(resolved_call)

    return graph


def _resolve_idb_name(name: str, known_blocks: dict[str, "BlockNode"]) -> str:
    """Resolve an Instance Data Block name to its Function Block type.

    In TIA Portal, IDBs are often named with suffixes like 'Instance' or 'Data'.
    This function attempts to find the corresponding FB name.

    Parameters
    ----------
    name : str
        The callee name (possibly an IDB name).
    known_blocks : dict[str, BlockNode]
        Dictionary of known block names.

    Returns
    -------
    str
        The resolved block name, or original name if not resolved.
    """
    # If the name already exists, return it
    if name in known_blocks:
        return name

    # Common IDB naming patterns to strip
    suffixes = ["Instance", "Data", "Inst", "DB"]

    for suffix in suffixes:
        if name.endswith(suffix) and len(name) > len(suffix):
            base_name = name[: -len(suffix)]
            if base_name in known_blocks:
                return base_name

    return name


def find_connected_components(graph: CallGraph) -> list[ConnectedComponent]:
    """Find all connected components in the call graph.

    A connected component is a maximal set of nodes where each node
    is reachable from every other node (ignoring edge direction).

    Parameters
    ----------
    graph : CallGraph
        The call graph to analyze.

    Returns
    -------
    list[ConnectedComponent]
        List of connected components, sorted by size (largest first).
    """
    if not graph.nodes:
        return []

    visited: set[str] = set()
    components: list[ConnectedComponent] = []

    # Build adjacency list (undirected - both calls and called_by)
    adjacency: dict[str, set[str]] = {name: set() for name in graph.nodes}
    for edge in graph.edges:
        if edge.caller in adjacency and edge.callee in adjacency:
            adjacency[edge.caller].add(edge.callee)
            adjacency[edge.callee].add(edge.caller)

    # BFS to find each component
    for start_node in graph.nodes:
        if start_node in visited:
            continue

        # BFS from this node
        component_nodes: set[str] = set()
        queue: deque[str] = deque([start_node])

        while queue:
            node = queue.popleft()
            if node in visited:
                continue

            visited.add(node)
            component_nodes.add(node)

            # Add unvisited neighbors
            for neighbor in adjacency[node]:
                if neighbor not in visited:
                    queue.append(neighbor)

        # Build component
        component = _build_component(graph, component_nodes)
        components.append(component)

    # Sort by size (largest first)
    components.sort(key=lambda c: c.node_count, reverse=True)

    # Assign names based on primary root
    for i, component in enumerate(components):
        root = component.get_primary_root()
        if root:
            component.name = f"{root} Graph"
        else:
            component.name = f"Graph {i + 1}"

    return components


def _build_component(graph: CallGraph, node_names: set[str]) -> ConnectedComponent:
    """Build a ConnectedComponent from a set of node names.

    Parameters
    ----------
    graph : CallGraph
        The source graph.
    node_names : set[str]
        Names of nodes in this component.

    Returns
    -------
    ConnectedComponent
        The constructed component.
    """
    component = ConnectedComponent()

    # Copy nodes
    for name in node_names:
        if name in graph.nodes:
            component.nodes[name] = graph.nodes[name]

    # Copy edges within component
    for edge in graph.edges:
        if edge.caller in node_names and edge.callee in node_names:
            component.edges.append(edge)

    # Find root candidates (nodes with no incoming edges within component)
    for name in node_names:
        node = graph.nodes.get(name)
        if node:
            # Check if any callers are within this component
            has_internal_caller = any(caller in node_names for caller in node.called_by)
            if not has_internal_caller:
                component.root_candidates.append(name)

    return component


def get_callers(graph: CallGraph, block_name: str, max_depth: int = 1) -> set[str]:
    """Get all blocks that call the specified block.

    Parameters
    ----------
    graph : CallGraph
        The call graph.
    block_name : str
        Name of the block to find callers for.
    max_depth : int
        Maximum depth to traverse (1 = direct callers only).

    Returns
    -------
    set[str]
        Set of block names that call this block.
    """
    callers: set[str] = set()
    current_level: set[str] = {block_name}

    for _ in range(max_depth):
        next_level: set[str] = set()
        for name in current_level:
            node = graph.get_node(name)
            if node:
                for caller in node.called_by:
                    if caller not in callers and caller != block_name:
                        callers.add(caller)
                        next_level.add(caller)
        current_level = next_level

    return callers


def get_callees(graph: CallGraph, block_name: str, max_depth: int = 1) -> set[str]:
    """Get all blocks that are called by the specified block.

    Parameters
    ----------
    graph : CallGraph
        The call graph.
    block_name : str
        Name of the block to find callees for.
    max_depth : int
        Maximum depth to traverse (1 = direct callees only).

    Returns
    -------
    set[str]
        Set of block names that this block calls.
    """
    callees: set[str] = set()
    current_level: set[str] = {block_name}

    for _ in range(max_depth):
        next_level: set[str] = set()
        for name in current_level:
            node = graph.get_node(name)
            if node:
                for callee in node.calls:
                    if callee not in callees and callee != block_name:
                        callees.add(callee)
                        next_level.add(callee)
        current_level = next_level

    return callees


def compute_graph_statistics(graph: CallGraph) -> dict[str, int | float]:
    """Compute statistics about the call graph.

    Parameters
    ----------
    graph : CallGraph
        The call graph to analyze.

    Returns
    -------
    dict[str, int | float]
        Dictionary of statistics.
    """
    if not graph.nodes:
        return {
            "node_count": 0,
            "edge_count": 0,
            "isolated_nodes": 0,
            "max_out_degree": 0,
            "max_in_degree": 0,
            "avg_out_degree": 0.0,
        }

    isolated = sum(1 for n in graph.nodes.values() if not n.calls and not n.called_by)
    max_out = max(len(n.calls) for n in graph.nodes.values())
    max_in = max(len(n.called_by) for n in graph.nodes.values())
    avg_out = sum(len(n.calls) for n in graph.nodes.values()) / len(graph.nodes)

    return {
        "node_count": graph.node_count,
        "edge_count": graph.edge_count,
        "isolated_nodes": isolated,
        "max_out_degree": max_out,
        "max_in_degree": max_in,
        "avg_out_degree": round(avg_out, 2),
    }
