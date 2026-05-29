"""Build and analyze type dependency graphs.

This module provides functionality to build dependency graphs from
extracted type references and analyze the relationships between UDTs.
"""

from collections import deque
from dataclasses import dataclass, field

from plc_code.analyzer.type_extractor import TypeDependencies


@dataclass
class TypeNode:
    """A node in the type dependency graph.

    Attributes
    ----------
    name : str
        The type name.
    doc_path : str
        Path to the documentation file for this type.
    dependencies : list[str]
        Types that this type depends on (uses).
    dependents : list[str]
        Types that depend on this type (used by).
    """

    name: str
    doc_path: str = ""
    dependencies: list[str] = field(default_factory=list)
    dependents: list[str] = field(default_factory=list)


@dataclass
class TypeEdge:
    """An edge in the type dependency graph.

    Attributes
    ----------
    source : str
        Source type name (the one that depends).
    target : str
        Target type name (the one being depended on).
    field_name : str
        Name of the field creating this dependency.
    is_array : bool
        Whether this is an array dependency.
    """

    source: str
    target: str
    field_name: str
    is_array: bool = False


@dataclass
class TypeGraph:
    """A graph of type dependencies.

    Attributes
    ----------
    nodes : dict[str, TypeNode]
        Mapping of type names to their nodes.
    edges : list[TypeEdge]
        List of dependency edges.
    """

    nodes: dict[str, TypeNode] = field(default_factory=dict)
    edges: list[TypeEdge] = field(default_factory=list)


@dataclass
class TypeComponent:
    """A connected component in the type dependency graph.

    Attributes
    ----------
    nodes : list[TypeNode]
        Nodes in this component.
    edges : list[TypeEdge]
        Edges within this component.
    name : str
        Name of the component (typically the "root" type).
    """

    nodes: list[TypeNode] = field(default_factory=list)
    edges: list[TypeEdge] = field(default_factory=list)
    name: str = ""

    @property
    def node_count(self) -> int:
        """Get the number of nodes."""
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        """Get the number of edges."""
        return len(self.edges)


def build_type_graph(
    type_deps: list[TypeDependencies],
    doc_path_registry: dict[str, str] | None = None,
) -> TypeGraph:
    """Build a type dependency graph from extracted dependencies.

    Parameters
    ----------
    type_deps : list[TypeDependencies]
        Type dependencies extracted from UDT blocks.
    doc_path_registry : dict[str, str] | None
        Optional mapping of type names to documentation paths.

    Returns
    -------
    TypeGraph
        The constructed type dependency graph.
    """
    graph = TypeGraph()
    doc_paths = doc_path_registry or {}

    # First pass: create nodes for all known types (skip empty names)
    for deps in type_deps:
        if not deps.type_name:
            continue
        if deps.type_name not in graph.nodes:
            graph.nodes[deps.type_name] = TypeNode(
                name=deps.type_name,
                doc_path=doc_paths.get(deps.type_name, ""),
            )

    # Second pass: add edges and create nodes for referenced types
    for deps in type_deps:
        # Skip empty source names
        if not deps.type_name:
            continue
        source_node = graph.nodes[deps.type_name]

        for ref in deps.references:
            # Create node for target if it doesn't exist
            if ref.target_type not in graph.nodes:
                graph.nodes[ref.target_type] = TypeNode(
                    name=ref.target_type,
                    doc_path=doc_paths.get(ref.target_type, ""),
                )

            target_node = graph.nodes[ref.target_type]

            # Add dependency relationships
            if ref.target_type not in source_node.dependencies:
                source_node.dependencies.append(ref.target_type)
            if deps.type_name not in target_node.dependents:
                target_node.dependents.append(deps.type_name)

            # Add edge
            graph.edges.append(
                TypeEdge(
                    source=deps.type_name,
                    target=ref.target_type,
                    field_name=ref.field_name,
                    is_array=ref.is_array,
                )
            )

    return graph


def find_type_components(graph: TypeGraph) -> list[TypeComponent]:
    """Find connected components in the type dependency graph.

    Uses BFS to find all connected components, treating the graph
    as undirected (both dependencies and dependents create connections).

    Parameters
    ----------
    graph : TypeGraph
        The type dependency graph.

    Returns
    -------
    list[TypeComponent]
        List of connected components, sorted by size (largest first).
    """
    if not graph.nodes:
        return []

    visited: set[str] = set()
    components: list[TypeComponent] = []

    # Build adjacency list (undirected)
    adjacency: dict[str, set[str]] = {name: set() for name in graph.nodes}
    for edge in graph.edges:
        adjacency[edge.source].add(edge.target)
        adjacency[edge.target].add(edge.source)

    # Find components using BFS
    for start_name in graph.nodes:
        if start_name in visited:
            continue

        component = TypeComponent()
        queue = deque([start_name])

        while queue:
            current = queue.popleft()
            if current in visited:
                continue

            visited.add(current)
            if current in graph.nodes:
                component.nodes.append(graph.nodes[current])

            for neighbor in adjacency.get(current, set()):
                if neighbor not in visited:
                    queue.append(neighbor)

        # Add edges that belong to this component
        component_names = {node.name for node in component.nodes}
        for edge in graph.edges:
            if edge.source in component_names and edge.target in component_names:
                component.edges.append(edge)

        # Name the component after the type with most dependencies (top-level root)
        # The root is the type that uses/depends on others, not the one being used
        if component.nodes:
            root_node = max(component.nodes, key=lambda n: len(n.dependencies))
            component.name = f"{root_node.name} Graph"

        components.append(component)

    # Sort by size (largest first), then by name
    components.sort(key=lambda c: (-c.node_count, c.name))

    return components


def get_type_dependencies(graph: TypeGraph, type_name: str) -> list[str]:
    """Get the types that a given type depends on.

    Parameters
    ----------
    graph : TypeGraph
        The type dependency graph.
    type_name : str
        Name of the type to query.

    Returns
    -------
    list[str]
        List of type names that this type depends on.
    """
    if type_name not in graph.nodes:
        return []
    return list(graph.nodes[type_name].dependencies)


def get_type_dependents(graph: TypeGraph, type_name: str) -> list[str]:
    """Get the types that depend on a given type.

    Parameters
    ----------
    graph : TypeGraph
        The type dependency graph.
    type_name : str
        Name of the type to query.

    Returns
    -------
    list[str]
        List of type names that depend on this type.
    """
    if type_name not in graph.nodes:
        return []
    return list(graph.nodes[type_name].dependents)


def compute_type_graph_statistics(graph: TypeGraph) -> dict[str, int]:
    """Compute statistics for a type dependency graph.

    Parameters
    ----------
    graph : TypeGraph
        The type dependency graph.

    Returns
    -------
    dict[str, int]
        Statistics including node_count, edge_count, isolated_types.
    """
    isolated_count = sum(1 for node in graph.nodes.values() if not node.dependencies and not node.dependents)

    return {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "isolated_types": isolated_count,
    }
