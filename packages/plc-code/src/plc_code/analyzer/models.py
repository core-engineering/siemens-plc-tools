"""Data models for call graph analysis.

This module defines the data structures used to represent function block
and function call relationships, enabling dependency visualization and
cross-reference documentation.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class CallType(Enum):
    """Type of call reference.

    Attributes
    ----------
    INSTANCE : str
        Call to a function block instance (e.g., #controller()).
    FUNCTION : str
        Call to a function (e.g., MyFunction()).
    SYSTEM : str
        Call to a system function (e.g., INT_TO_REAL).
    """

    INSTANCE = "instance"
    FUNCTION = "function"
    SYSTEM = "system"


@dataclass
class CallReference:
    """Represents a single call from one block to another.

    Attributes
    ----------
    caller : str
        Name of the calling block.
    callee : str
        Name of the called block/function (resolved type name).
    instance_name : str
        Name of the instance variable (e.g., "controller" from #controller).
    call_type : CallType
        Type of call (INSTANCE, FUNCTION, SYSTEM).
    line_number : int
        Approximate line number in source file.
    """

    caller: str
    callee: str
    instance_name: str
    call_type: CallType
    line_number: int = 0


@dataclass
class BlockNode:
    """Node in the call graph representing a block.

    Attributes
    ----------
    name : str
        Block name.
    block_type : str
        Type of block (FUNCTION_BLOCK, FUNCTION).
    file_path : Path | None
        Path to source file.
    doc_path : str
        Relative path to documentation file (for cross-references).
    calls : list[str]
        Names of blocks this one calls (outgoing edges).
    called_by : list[str]
        Names of blocks that call this one (incoming edges).
    category : str
        Category extracted from file path (e.g., "Process").
    subcategory : str
        Subcategory extracted from file path (e.g., "Physical Interfaces").
    """

    name: str
    block_type: str
    file_path: Path | None = None
    doc_path: str = ""
    calls: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)
    category: str = ""
    subcategory: str = ""


@dataclass
class CallGraph:
    """Complete call graph for a project.

    Attributes
    ----------
    nodes : dict[str, BlockNode]
        Mapping from block name to node information.
    edges : list[CallReference]
        All call relationships in the graph.
    """

    nodes: dict[str, BlockNode] = field(default_factory=dict)
    edges: list[CallReference] = field(default_factory=list)

    def add_node(self, node: BlockNode) -> None:
        """Add a node to the graph.

        Parameters
        ----------
        node : BlockNode
            The node to add.
        """
        self.nodes[node.name] = node

    def add_edge(self, edge: CallReference) -> None:
        """Add an edge to the graph and update node relationships.

        Parameters
        ----------
        edge : CallReference
            The call reference to add.
        """
        self.edges.append(edge)

        # Update caller's outgoing calls
        if edge.caller in self.nodes:
            if edge.callee not in self.nodes[edge.caller].calls:
                self.nodes[edge.caller].calls.append(edge.callee)

        # Update callee's incoming calls
        if edge.callee in self.nodes:
            if edge.caller not in self.nodes[edge.callee].called_by:
                self.nodes[edge.callee].called_by.append(edge.caller)

    def get_node(self, name: str) -> BlockNode | None:
        """Get a node by name.

        Parameters
        ----------
        name : str
            The block name.

        Returns
        -------
        BlockNode | None
            The node, or None if not found.
        """
        return self.nodes.get(name)

    @property
    def node_count(self) -> int:
        """Get the number of nodes in the graph."""
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        """Get the number of unique edges in the graph."""
        # Count unique caller->callee pairs
        unique_edges = {(e.caller, e.callee) for e in self.edges}
        return len(unique_edges)


@dataclass
class ConnectedComponent:
    """A connected subgraph (independent call graph).

    Attributes
    ----------
    nodes : dict[str, BlockNode]
        Nodes in this component.
    edges : list[CallReference]
        Edges within this component.
    root_candidates : list[str]
        Nodes with no incoming edges (potential entry points).
    name : str
        Auto-generated name for the component (e.g., "Module Graph").
    """

    nodes: dict[str, BlockNode] = field(default_factory=dict)
    edges: list[CallReference] = field(default_factory=list)
    root_candidates: list[str] = field(default_factory=list)
    name: str = ""

    @property
    def node_count(self) -> int:
        """Get the number of nodes in the component."""
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        """Get the number of unique edges in the component."""
        unique_edges = {(e.caller, e.callee) for e in self.edges}
        return len(unique_edges)

    def get_primary_root(self) -> str | None:
        """Get the primary root node (entry point) of the component.

        Returns the root candidate with the most outgoing calls,
        or the first root candidate if none have calls.

        Returns
        -------
        str | None
            Name of the primary root node, or None if no nodes.
        """
        if not self.root_candidates:
            # If no roots (cycle), return node with most calls
            if self.nodes:
                return max(self.nodes.keys(), key=lambda n: len(self.nodes[n].calls))
            return None

        # Return root with most outgoing calls
        return max(
            self.root_candidates,
            key=lambda n: len(self.nodes[n].calls) if n in self.nodes else 0,
        )
