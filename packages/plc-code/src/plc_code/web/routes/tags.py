"""I/O Tag listing and dependency tracing API routes."""

from fastapi import APIRouter, HTTPException, Query

from plc_code.analyzer.logic_dependency import ForwardTrace
from plc_code.analyzer.logic_dependency.chain_builder import DependencyNode
from plc_code.analyzer.logic_dependency.forward_tracer import DataFlowTreeNode

from ..schemas import (
    DataFlowNodeSchema,
    DataFlowTreeNodeSchema,
    DependencyChainSchema,
    DependencyNodeSchema2,
    ForwardTraceSchema,
    IOTagSchema,
    TagAssignmentSchema,
    TagCategoryCount,
    TagDiagramResponse,
    TagListResponse,
)
from ..services import get_service

router = APIRouter(prefix="/api/tags", tags=["tags"])


def _convert_node(node: DependencyNode) -> DependencyNodeSchema2:
    """Convert a DependencyNode to schema."""
    return DependencyNodeSchema2(
        name=node.name,
        node_type=node.node_type,
        block_name=node.block_name,
        line_number=node.line_number,
        expression=node.expression,
        children=[_convert_node(c) for c in node.children],
    )


def _convert_tree_node(node: DataFlowTreeNode) -> DataFlowTreeNodeSchema:
    """Convert a DataFlowTreeNode to schema."""
    return DataFlowTreeNodeSchema(
        field_path=node.field_path,
        block_name=node.block_name,
        line_number=node.line_number,
        node_type=node.node_type,
        tag_name=node.tag_name,
        children=[_convert_tree_node(c) for c in node.children],
    )


@router.get("", response_model=TagListResponse)
async def list_tags(
    category: str | None = Query(None, description="Filter by category (DO, SDO, DI, SDI, AI, SAI)"),
    direction: str | None = Query(None, description="Filter by direction (input, output)"),
) -> TagListResponse:
    """List all I/O tags in the configured PLC program.

    Returns a list of I/O tags grouped by category.
    """
    service = get_service()
    if not service.source_path:
        return TagListResponse(tags=[], total=0, categories=[])

    tags_collection = service.get_tags()
    if tags_collection is None:
        return TagListResponse(tags=[], total=0, categories=[])

    # Convert to schema
    all_tags = []
    for tag in tags_collection.tags:
        # Apply filters
        if category and tag.category != category:
            continue
        if direction and tag.direction != direction:
            continue

        all_tags.append(
            IOTagSchema(
                name=tag.name,
                address=tag.address,
                data_type=tag.data_type,
                comment=tag.comment,
                category=tag.category,
                direction=tag.direction,
                source_file=tag.source_file,
            )
        )

    # Get category counts (unfiltered)
    categories = []
    for cat, count in tags_collection.categories().items():
        # Determine direction from category
        dir_ = "output" if cat in ("DO", "SDO") else "input"
        categories.append(
            TagCategoryCount(
                category=cat,
                count=count,
                direction=dir_,
            )
        )

    # Sort categories
    cat_order = ["DO", "SDO", "DI", "SDI", "AI", "SAI"]
    categories.sort(key=lambda c: cat_order.index(c.category) if c.category in cat_order else 99)

    return TagListResponse(
        tags=all_tags,
        total=len(all_tags),
        categories=categories,
    )


@router.get("/{name}", response_model=IOTagSchema)
async def get_tag(name: str) -> IOTagSchema:
    """Get information about a specific I/O tag.

    Parameters
    ----------
    name : str
        Tag name (case-sensitive).

    Returns
    -------
    IOTagSchema
        Tag information.
    """
    service = get_service()
    tags = service.get_tags()

    if tags is None:
        raise HTTPException(status_code=404, detail="No tags loaded")

    tag = tags.get(name)
    if tag is None:
        raise HTTPException(status_code=404, detail=f"Tag '{name}' not found")

    return IOTagSchema(
        name=tag.name,
        address=tag.address,
        data_type=tag.data_type,
        comment=tag.comment,
        category=tag.category,
        direction=tag.direction,
        source_file=tag.source_file,
    )


@router.get("/{name}/trace")
async def trace_tag(name: str) -> DependencyChainSchema | ForwardTraceSchema:
    """Get the dependency chain for an I/O tag.

    For output tags (DO_, SDO_), traces backward to find inputs.
    For input tags (DI_, SDI_, AI_, SAI_), traces forward to find outputs.

    Parameters
    ----------
    name : str
        Tag name.

    Returns
    -------
    DependencyChainSchema | ForwardTraceSchema
        The complete dependency chain or forward trace.
    """
    service = get_service()
    result = service.trace_tag(name)

    if result is None:
        raise HTTPException(status_code=404, detail=f"Tag '{name}' not found or cannot be traced")

    # Check if it's a ForwardTrace (input tags)
    if isinstance(result, ForwardTrace):
        # Get tag info for response
        tags = service.get_tags()
        tag = tags.get(name) if tags else None
        tag_category = tag.category if tag else ""
        tag_direction = tag.direction if tag else "input"

        # Build assignment schema from the tree root info
        assignment_schema = None
        if result.dataflow_tree and result.dataflow_tree.children:
            resolved_node = result.dataflow_tree.children[0]
            if resolved_node.block_name:
                assignment_schema = TagAssignmentSchema(
                    tag_name=name,
                    mapped_field=result.resolved_field,
                    block_name=resolved_node.block_name,
                    line_number=resolved_node.line_number,
                    assignment_type="direct",
                    direction="read",
                )

        # Convert the tree
        tree_schema = None
        if result.dataflow_tree:
            tree_schema = _convert_tree_node(result.dataflow_tree)

        return ForwardTraceSchema(
            tag_name=result.tag_name,
            tag_category=tag_category,
            tag_direction=tag_direction,
            resolved_field=result.resolved_field,
            assignment=assignment_schema,
            nodes=[
                DataFlowNodeSchema(
                    field_path=n.field_path,
                    block_name=n.block_name,
                    line_number=n.line_number,
                    access_type=n.access_type,
                    expression=n.expression,
                    output_fields=n.output_fields,
                    is_terminal=n.is_terminal,
                    terminal_reason=n.terminal_reason,
                )
                for n in result.nodes
            ],
            blocks_involved=result.blocks_involved,
            terminal_fields=result.terminal_fields,
            trace_path=result.trace_path,
            dataflow_tree=tree_schema,
        )

    # It's a DependencyChain (output tags)
    chain = result

    # Convert assignment
    assignment = None
    if chain.assignment:
        assignment = TagAssignmentSchema(
            tag_name=chain.assignment.tag_name,
            mapped_field=chain.assignment.mapped_field,
            block_name=chain.assignment.block_name,
            line_number=chain.assignment.line_number,
            assignment_type=chain.assignment.assignment_type,
            direction=chain.assignment.direction,
        )

    return DependencyChainSchema(
        tag_name=chain.root_tag.name,
        tag_category=chain.root_tag.category,
        tag_direction=chain.root_tag.direction,
        assignment=assignment,
        dependency_tree=_convert_node(chain.dependency_tree),
        blocks_involved=chain.blocks_involved,
        terminal_nodes=chain.terminal_nodes,
        trace_direction=chain.direction,
        depth=chain.depth,
    )


@router.get("/{name}/diagram", response_model=TagDiagramResponse)
async def get_tag_diagram(
    name: str,
    simplified: bool = Query(False, description="Show simplified diagram"),
) -> TagDiagramResponse:
    """Get a Mermaid diagram for a tag's dependencies.

    Parameters
    ----------
    name : str
        Tag name.
    simplified : bool
        If True, show only termination points.

    Returns
    -------
    TagDiagramResponse
        Mermaid diagram code.
    """
    service = get_service()
    diagram = service.get_tag_diagram(name, simplified)

    if diagram is None:
        raise HTTPException(status_code=404, detail=f"Tag '{name}' not found or cannot be traced")

    return TagDiagramResponse(
        mermaid=diagram,
        tag_name=name,
        simplified=simplified,
    )
