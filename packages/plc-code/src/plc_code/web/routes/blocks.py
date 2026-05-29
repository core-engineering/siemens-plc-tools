"""Block listing and details API routes."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from ..schemas import BlockDetail, BlockListResponse
from ..services import get_service

router = APIRouter(prefix="/api/blocks", tags=["blocks"])


@router.get("", response_model=BlockListResponse)
async def list_blocks() -> BlockListResponse:
    """List all blocks in the configured source directory.

    Returns a list of block summaries with basic information.
    """
    service = get_service()
    if not service.source_path:
        return BlockListResponse(blocks=[], total=0)

    return service.list_blocks()


@router.get("/{name}", response_model=BlockDetail)
async def get_block(name: str) -> BlockDetail:
    """Get detailed information about a specific block.

    Parameters
    ----------
    name : str
        Block name (case-insensitive).

    Returns
    -------
    BlockDetail
        Detailed block information including all variable sections.
    """
    service = get_service()
    detail = service.get_block_detail(name)

    if not detail:
        raise HTTPException(status_code=404, detail=f"Block '{name}' not found")

    return detail


@router.get("/{name}/source")
async def get_block_source(
    name: str,
    line: int = Query(0, description="Center the excerpt around this line"),
    context: int = Query(0, description="Number of context lines (0 = full file)"),
) -> JSONResponse:
    """Get the source code of a block.

    Parameters
    ----------
    name : str
        Block name.
    line : int
        Line number to center around (0 = return full file).
    context : int
        Number of lines before and after to include (0 = full file).

    Returns
    -------
    JSONResponse
        Source code with line information.
    """
    service = get_service()
    source = service.get_block_source(name)

    if source is None:
        raise HTTPException(status_code=404, detail=f"Block '{name}' source not found")

    lines = source.splitlines()
    total_lines = len(lines)
    start_line = 1
    end_line = total_lines

    if line > 0 and context > 0:
        start_line = max(1, line - context)
        end_line = min(total_lines, line + context)
        lines = lines[start_line - 1 : end_line]

    return JSONResponse(
        {
            "block_name": name,
            "source": "\n".join(lines),
            "total_lines": total_lines,
            "start_line": start_line,
            "end_line": end_line,
            "highlight_line": line,
        }
    )
