"""Pydantic schemas for the web API.

These models define the request/response formats for the REST API
endpoints, providing automatic validation and documentation.
"""

from enum import Enum

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    """Type of node in the dependency tree."""

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


class SourceLocation(BaseModel):
    """Location in source code."""

    file_path: str = ""
    line_number: int = 0
    region_name: str = ""


class VariableInfo(BaseModel):
    """Information about a variable."""

    name: str
    data_type: str = ""
    default_value: str | None = None


class DependencyNodeSchema(BaseModel):
    """A node in the dependency tree."""

    name: str
    node_type: NodeType
    data_type: str = ""
    source_location: SourceLocation | None = None


class DependencySummary(BaseModel):
    """Summary of dependencies for an output."""

    inputs: list[str] = Field(default_factory=list)
    states: list[str] = Field(default_factory=list)
    constants: list[str] = Field(default_factory=list)
    global_dbs: list[str] = Field(default_factory=list)
    intermediate_vars: list[str] = Field(default_factory=list)


class OutputDependency(BaseModel):
    """Dependency information for a single output."""

    name: str
    data_type: str = ""
    source_location: SourceLocation | None = None
    summary: DependencySummary
    input_nodes: list[DependencyNodeSchema] = Field(default_factory=list)


class BlockSummary(BaseModel):
    """Summary information for a block."""

    name: str
    block_type: str
    source_file: str
    category: str = ""
    subcategory: str = ""
    input_count: int = 0
    output_count: int = 0
    outputs: list[str] = Field(default_factory=list)


class BlockDetail(BaseModel):
    """Detailed information about a block."""

    name: str
    block_type: str
    source_file: str
    inputs: list[VariableInfo] = Field(default_factory=list)
    outputs: list[VariableInfo] = Field(default_factory=list)
    in_outs: list[VariableInfo] = Field(default_factory=list)
    static_vars: list[VariableInfo] = Field(default_factory=list)
    temp_vars: list[VariableInfo] = Field(default_factory=list)
    constants: list[VariableInfo] = Field(default_factory=list)


class BlockDependencies(BaseModel):
    """All dependencies for a block."""

    block_name: str
    source_file: str
    outputs: dict[str, OutputDependency] = Field(default_factory=dict)


class DiagramResponse(BaseModel):
    """Response containing Mermaid diagram code."""

    mermaid: str
    block_name: str
    output_name: str | None = None
    simplified: bool = False


class BlockListResponse(BaseModel):
    """Response containing list of blocks."""

    blocks: list[BlockSummary]
    total: int


class ConfigResponse(BaseModel):
    """Response containing project configuration."""

    name: str = ""
    code: str = ""
    source_path: str = ""
    has_config: bool = False
    docs_available: bool = False


class ConfigUpdate(BaseModel):
    """Request to update configuration."""

    source_path: str


class ErrorResponse(BaseModel):
    """Error response."""

    detail: str
    error_type: str = "error"


# ============== I/O Tag Schemas ==============


class IOTagSchema(BaseModel):
    """Schema for a physical I/O tag."""

    name: str
    address: str = ""
    data_type: str = ""
    comment: str = ""
    category: str  # DO, SDO, DI, SDI, AI, SAI
    direction: str  # output, input
    source_file: str = ""


class TagCategoryCount(BaseModel):
    """Count of tags by category."""

    category: str
    count: int
    direction: str


class TagListResponse(BaseModel):
    """Response containing list of I/O tags."""

    tags: list[IOTagSchema]
    total: int
    categories: list[TagCategoryCount] = Field(default_factory=list)


class TagAssignmentSchema(BaseModel):
    """Schema for tag-to-field assignment."""

    tag_name: str
    mapped_field: str
    block_name: str
    line_number: int
    assignment_type: str  # direct, ladder_coil, ladder_move
    direction: str  # write, read


class DependencyNodeSchema2(BaseModel):
    """A node in the I/O tag dependency tree."""

    name: str
    node_type: str  # io_tag, state_var, field, local
    block_name: str | None = None
    line_number: int | None = None
    expression: str | None = None
    children: list["DependencyNodeSchema2"] = Field(default_factory=list)


class DependencyChainSchema(BaseModel):
    """Complete dependency chain for an I/O tag."""

    tag_name: str
    tag_category: str
    tag_direction: str
    assignment: TagAssignmentSchema | None = None
    dependency_tree: DependencyNodeSchema2
    blocks_involved: list[str] = Field(default_factory=list)
    terminal_nodes: list[str] = Field(default_factory=list)
    trace_direction: str  # backward (outputs) or forward (inputs)
    depth: int = 0


class DataFlowNodeSchema(BaseModel):
    """A node in the forward trace data flow graph."""

    field_path: str
    block_name: str
    line_number: int
    access_type: str  # read, write, function_input, function_output
    expression: str
    output_fields: list[str] = Field(default_factory=list)
    is_terminal: bool = False
    terminal_reason: str | None = None


class DataFlowTreeNodeSchema(BaseModel):
    """A node in the hierarchical data flow tree."""

    field_path: str
    block_name: str = ""
    line_number: int = 0
    node_type: str  # io_tag, field, state_var, output_tag
    tag_name: str | None = None
    children: list["DataFlowTreeNodeSchema"] = Field(default_factory=list)


class ForwardTraceSchema(BaseModel):
    """Complete forward trace for an input tag."""

    tag_name: str
    tag_category: str
    tag_direction: str
    resolved_field: str
    assignment: TagAssignmentSchema | None = None
    nodes: list[DataFlowNodeSchema] = Field(default_factory=list)
    blocks_involved: list[str] = Field(default_factory=list)
    terminal_fields: list[str] = Field(default_factory=list)
    trace_path: list[str] = Field(default_factory=list)
    dataflow_tree: DataFlowTreeNodeSchema | None = None


class TagDiagramResponse(BaseModel):
    """Response containing Mermaid diagram for a tag's dependencies."""

    mermaid: str
    tag_name: str
    simplified: bool = False


# Enable forward reference resolution
DependencyNodeSchema2.model_rebuild()
DataFlowTreeNodeSchema.model_rebuild()
