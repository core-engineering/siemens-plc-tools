"""Call graph and type dependency analysis module.

This module provides tools for analyzing function block and function
call dependencies, as well as UDT type dependencies in SCL code,
enabling visualization of relationships and dependency documentation.

Examples
--------
>>> from plc_code.analyzer import (
...     build_call_graph,
...     find_connected_components,
...     generate_mermaid_block,
... )
>>> from plc_code.parser import parse_scl_file
>>>
>>> # Parse blocks
>>> blocks = [parse_scl_file(path) for path in scl_files]
>>>
>>> # Build call graph
>>> graph = build_call_graph(blocks)
>>>
>>> # Find independent graphs
>>> components = find_connected_components(graph)
>>>
>>> # Generate Mermaid diagram
>>> diagram = generate_mermaid_block(components[0])
"""

from plc_code.analyzer.call_extractor import (
    extract_calls,
    extract_instance_declarations,
)
from plc_code.analyzer.db_audit import (
    AUDIT_RULES,
    AuditResult,
    AuditRule,
    AuditSeverity,
    AuditStatistics,
    AuditViolation,
    GlobalVariableAuditor,
    generate_audit_markdown,
    run_global_variable_audit,
)
from plc_code.analyzer.db_crossref import (
    DBCrossReference,
    GlobalVariable,
    VariableReference,
    build_db_crossref,
    generate_crossref_index,
    generate_crossref_markdown,
    generate_db_page,
    get_variable_anchor_link,
    normalize_array_indices,
)
from plc_code.analyzer.db_extractor import (
    BlockDBDependencies,
    GlobalDBReference,
    extract_db_references,
    get_db_summary,
)
from plc_code.analyzer.graph_builder import (
    build_call_graph,
    compute_graph_statistics,
    find_connected_components,
    get_callees,
    get_callers,
)

# Logic dependency analysis
from plc_code.analyzer.logic_dependency import (
    Assignment,
    BlockAnalysisResult,
    BlockDependencies,
    # Graph builder
    DependencyGraphBuilder,
    DependencyNode,
    # Expression parser
    ExpressionParser,
    LogicExpression,
    # Mermaid
    MermaidGenerator,
    # Models
    NodeType,
    OperatorType,
    OutputDependencyTree,
    ParseError,
    SourceLocation,
    VariableInfo,
    build_all_output_trees,
    # Extractor
    build_variable_registry,
    collect_leaf_nodes,
    extract_dependencies,
    generate_block_summary_diagram,
    generate_dependency_diagram,
    generate_simplified_diagram,
    get_dependency_summary,
    get_input_dependencies,
    get_output_assignments,
    get_state_assignments,
    parse_expression,
)
from plc_code.analyzer.mermaid import (
    generate_block_dependency_diagram,
    generate_legend_block,
    generate_mermaid_block,
    generate_mermaid_flowchart,
)
from plc_code.analyzer.models import (
    BlockNode,
    CallGraph,
    CallReference,
    CallType,
    ConnectedComponent,
)
from plc_code.analyzer.safety_crossref import (
    SafetyReport,
    build_safety_report,
    is_safety_block,
)
from plc_code.analyzer.state_machine import (
    StateConstant,
    StateMachine,
    StateTransition,
    extract_state_machine,
    generate_state_diagram,
    generate_state_diagram_block,
    has_state_machine,
)
from plc_code.analyzer.type_extractor import (
    TypeDependencies,
    TypeReference,
    extract_all_type_dependencies,
    extract_type_dependencies,
)
from plc_code.analyzer.type_graph import (
    TypeComponent,
    TypeEdge,
    TypeGraph,
    TypeNode,
    build_type_graph,
    compute_type_graph_statistics,
    find_type_components,
    get_type_dependencies,
    get_type_dependents,
)
from plc_code.analyzer.type_mermaid import (
    generate_type_component_flowchart,
    generate_type_mermaid_flowchart,
)

__all__ = [
    # Call graph models
    "BlockNode",
    "CallGraph",
    "CallReference",
    "CallType",
    "ConnectedComponent",
    # Call extraction
    "extract_calls",
    "extract_instance_declarations",
    # Global DB dependency extraction
    "BlockDBDependencies",
    "GlobalDBReference",
    "extract_db_references",
    "get_db_summary",
    # Global DB cross-reference
    "DBCrossReference",
    "GlobalVariable",
    "VariableReference",
    "build_db_crossref",
    "generate_crossref_index",
    "generate_crossref_markdown",
    "generate_db_page",
    "get_variable_anchor_link",
    "normalize_array_indices",
    # Safety boundary cross-reference
    "SafetyReport",
    "build_safety_report",
    "is_safety_block",
    # Global DB audit
    "AUDIT_RULES",
    "AuditResult",
    "AuditRule",
    "AuditSeverity",
    "AuditStatistics",
    "AuditViolation",
    "GlobalVariableAuditor",
    "generate_audit_markdown",
    "run_global_variable_audit",
    # Call graph building
    "build_call_graph",
    "find_connected_components",
    "get_callers",
    "get_callees",
    "compute_graph_statistics",
    # Call graph Mermaid generation
    "generate_mermaid_flowchart",
    "generate_mermaid_block",
    "generate_legend_block",
    "generate_block_dependency_diagram",
    # Type dependency models
    "TypeDependencies",
    "TypeReference",
    "TypeComponent",
    "TypeEdge",
    "TypeGraph",
    "TypeNode",
    # Type dependency extraction
    "extract_type_dependencies",
    "extract_all_type_dependencies",
    # Type graph building
    "build_type_graph",
    "find_type_components",
    "get_type_dependencies",
    "get_type_dependents",
    "compute_type_graph_statistics",
    # Type graph Mermaid generation
    "generate_type_mermaid_flowchart",
    "generate_type_component_flowchart",
    # State machine analysis
    "StateConstant",
    "StateMachine",
    "StateTransition",
    "has_state_machine",
    "extract_state_machine",
    "generate_state_diagram",
    "generate_state_diagram_block",
    # Logic dependency analysis - Models
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
    # Logic dependency analysis - Expression parser
    "ExpressionParser",
    "ParseError",
    "parse_expression",
    # Logic dependency analysis - Extractor
    "build_variable_registry",
    "extract_dependencies",
    "get_output_assignments",
    "get_state_assignments",
    # Logic dependency analysis - Graph builder
    "DependencyGraphBuilder",
    "build_all_output_trees",
    "get_input_dependencies",
    "get_dependency_summary",
    "collect_leaf_nodes",
    # Logic dependency analysis - Mermaid
    "MermaidGenerator",
    "generate_dependency_diagram",
    "generate_simplified_diagram",
    "generate_block_summary_diagram",
]
