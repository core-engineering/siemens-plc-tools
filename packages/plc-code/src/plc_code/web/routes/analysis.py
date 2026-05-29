"""Dependency analysis API routes."""

from fastapi import APIRouter, HTTPException, Query

from ..schemas import BlockDependencies, DiagramResponse, OutputDependency
from ..services import get_service

router = APIRouter(prefix="/api/blocks", tags=["analysis"])


@router.get("/{name}/dependencies", response_model=BlockDependencies)
async def get_dependencies(name: str) -> BlockDependencies:
    """Get dependency trees for all outputs in a block.

    Parameters
    ----------
    name : str
        Block name (case-insensitive).

    Returns
    -------
    BlockDependencies
        Dependency information for all outputs.
    """
    service = get_service()
    deps = service.get_dependencies(name)

    if not deps:
        raise HTTPException(status_code=404, detail=f"Block '{name}' not found or has no outputs")

    return deps


@router.get("/{name}/dependencies/{output}", response_model=OutputDependency)
async def get_output_dependency(name: str, output: str) -> OutputDependency:
    """Get dependency tree for a specific output variable.

    Parameters
    ----------
    name : str
        Block name (case-insensitive).
    output : str
        Output variable name.

    Returns
    -------
    OutputDependency
        Dependency information for the output.
    """
    service = get_service()
    dep = service.get_output_dependency(name, output)

    if not dep:
        raise HTTPException(status_code=404, detail=f"Output '{output}' not found in block '{name}'")

    return dep


@router.get("/{name}/diagram", response_model=DiagramResponse)
async def get_diagram(
    name: str,
    output: str | None = Query(default=None, description="Specific output to diagram"),
    simplified: bool = Query(default=False, description="Generate simplified diagram"),
) -> DiagramResponse:
    """Generate Mermaid diagram for a block or output.

    Parameters
    ----------
    name : str
        Block name (case-insensitive).
    output : str | None
        Optional output variable name. If not specified, generates
        a summary diagram for all outputs.
    simplified : bool
        If True, generates a simplified diagram showing only
        inputs and outputs without logic gates.

    Returns
    -------
    DiagramResponse
        Mermaid diagram code.
    """
    service = get_service()
    diagram = service.get_diagram(name, output, simplified)

    if not diagram:
        raise HTTPException(
            status_code=404,
            detail=f"Cannot generate diagram for block '{name}'" + (f" output '{output}'" if output else ""),
        )

    return diagram
