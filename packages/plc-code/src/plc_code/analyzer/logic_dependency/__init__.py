"""Logic dependency analyzer for SCL blocks.

This module provides functionality to trace output-to-input dependencies
in PLC blocks, producing navigable dependency trees and logic diagrams.

Example usage:
    from plc_code.parser.scl import parse_scl_file
    from plc_code.analyzer.logic_dependency import (
        extract_dependencies,
        build_all_output_trees,
        generate_dependency_diagram,
    )

    # Parse block
    block = parse_scl_file("path/to/block.s7dcl")

    # Extract dependencies
    deps = extract_dependencies(block)

    # Build output trees
    trees = build_all_output_trees(deps)

    # Generate diagram for an output
    if "alarmState" in trees:
        diagram = generate_dependency_diagram(trees["alarmState"])
        print(diagram)
"""

from .chain_builder import (
    ChainBuilder,
    DependencyChain,
    build_all_chains,
    build_dependency_chain,
    generate_chain_mermaid,
)
from .chain_builder import (
    DependencyNode as ChainDependencyNode,
)
from .expression_parser import (
    ExpressionParser,
    ParseError,
    parse_expression,
)
from .extractor import (
    build_variable_registry,
    extract_dependencies,
    get_output_assignments,
    get_state_assignments,
)
from .field_tracer import (
    FieldAccess,
    find_field_readers,
    find_field_writers,
    trace_field_through_blocks,
)
from .forward_tracer import (
    DataFlowNode,
    DataFlowTreeNode,
    ForwardTrace,
    build_dataflow_tree,
    find_field_usages,
    trace_input_forward,
)
from .graph_builder import (
    DependencyGraphBuilder,
    build_all_output_trees,
    collect_leaf_nodes,
    get_dependency_summary,
    get_input_dependencies,
)
from .index_resolver import (
    TagIndexInfo,
    extract_indices_from_tag,
    normalize_and_resolve,
    resolve_field_indices,
)
from .mermaid import (
    MermaidGenerator,
    generate_block_summary_diagram,
    generate_dependency_diagram,
    generate_simplified_diagram,
)
from .models import (
    Assignment,
    BlockAnalysisResult,
    BlockDependencies,
    DependencyNode,
    LogicExpression,
    NodeType,
    OperatorType,
    OutputDependencyTree,
    SourceLocation,
    VariableInfo,
)
from .state_detector import (
    StateVariable,
    classify_variable,
    detect_all_state_variables,
    detect_state_variables_in_block,
    get_state_variable_names,
    is_io_tag,
    is_state_var_name,
    is_state_variable,
    is_termination_point,
)
from .tag_assignment import (
    TagAssignment,
    find_all_tag_assignments,
    find_assignments_in_block,
    get_field_to_tag_mapping,
    get_tag_to_field_mapping,
)

# I/O Tag tracing modules
from .tag_parser import (
    TAG_PREFIXES,
    IOTag,
    TagCollection,
    find_tag_directory,
    parse_tag_directory,
    parse_tag_file,
)

__all__ = [
    # Models
    "NodeType",
    "OperatorType",
    "SourceLocation",
    "DependencyNode",
    "LogicExpression",
    "Assignment",
    "VariableInfo",
    "BlockDependencies",
    "OutputDependencyTree",
    "BlockAnalysisResult",
    # Expression parser
    "ExpressionParser",
    "ParseError",
    "parse_expression",
    # Extractor
    "build_variable_registry",
    "extract_dependencies",
    "get_output_assignments",
    "get_state_assignments",
    # Graph builder
    "DependencyGraphBuilder",
    "build_all_output_trees",
    "get_input_dependencies",
    "get_dependency_summary",
    "collect_leaf_nodes",
    # Mermaid
    "MermaidGenerator",
    "generate_dependency_diagram",
    "generate_simplified_diagram",
    "generate_block_summary_diagram",
    # Tag parser
    "IOTag",
    "TagCollection",
    "TAG_PREFIXES",
    "parse_tag_file",
    "parse_tag_directory",
    "find_tag_directory",
    # Tag assignment
    "TagAssignment",
    "find_assignments_in_block",
    "find_all_tag_assignments",
    "get_tag_to_field_mapping",
    "get_field_to_tag_mapping",
    # Field tracer
    "FieldAccess",
    "find_field_writers",
    "find_field_readers",
    "trace_field_through_blocks",
    # State detector
    "StateVariable",
    "is_io_tag",
    "is_state_variable",
    "is_state_var_name",
    "is_termination_point",
    "detect_state_variables_in_block",
    "detect_all_state_variables",
    "get_state_variable_names",
    "classify_variable",
    # Chain builder
    "ChainDependencyNode",
    "DependencyChain",
    "ChainBuilder",
    "build_dependency_chain",
    "build_all_chains",
    "generate_chain_mermaid",
    # Index resolver
    "TagIndexInfo",
    "extract_indices_from_tag",
    "resolve_field_indices",
    "normalize_and_resolve",
    # Forward tracer
    "DataFlowNode",
    "DataFlowTreeNode",
    "ForwardTrace",
    "build_dataflow_tree",
    "find_field_usages",
    "trace_input_forward",
]
