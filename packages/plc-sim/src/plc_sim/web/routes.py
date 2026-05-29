"""FastAPI routes for the OPC UA simulation API.

All endpoints are prefixed with ``/api/sim/``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from plc_sim.web.schemas import (
    BrowseResponse,
    ConnectRequest,
    ConnectResponse,
    ReadResponse,
    SimConfigResponse,
    StatusResponse,
    WriteMultipleRequest,
    WriteRequest,
    WriteResponse,
)
from plc_sim.web.services import get_sim_service

logger = logging.getLogger(__name__)

sim_router = APIRouter(prefix="/api/sim", tags=["sim"])


# =============================================================================
# Configuration
# =============================================================================


@sim_router.get("/config", response_model=SimConfigResponse)
async def get_sim_config() -> SimConfigResponse:
    """Get the current simulation configuration."""
    service = get_sim_service()
    config = service.config
    return SimConfigResponse(
        endpoint=config.endpoint,
        interface=config.interface,
        namespaces=config.namespaces,
        subscription_interval_ms=config.subscription_interval_ms,
        has_config=config.config_path is not None,
    )


# =============================================================================
# Connection management
# =============================================================================


@sim_router.post("/connect", response_model=ConnectResponse)
async def connect(request: ConnectRequest | None = None) -> ConnectResponse:
    """Connect to the OPC UA server."""
    service = get_sim_service()
    endpoint = request.endpoint if request and request.endpoint else None

    try:
        info = await service.connect(endpoint)
        return ConnectResponse(
            status=info.status,
            endpoint=info.endpoint,
            server_name=info.server_name,
            session_id=info.session_id,
            namespaces=info.namespaces,
            error_message=info.error_message,
            connected_since=info.connected_since,
        )
    except Exception as e:
        logger.exception("Connection error")
        raise HTTPException(status_code=500, detail=str(e)) from e


@sim_router.post("/disconnect")
async def disconnect() -> dict[str, str]:
    """Disconnect from the OPC UA server."""
    service = get_sim_service()
    await service.disconnect()
    return {"status": "disconnected"}


@sim_router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    """Get current connection status."""
    service = get_sim_service()
    info = await service.get_status()
    return StatusResponse(
        status=info.status,
        endpoint=info.endpoint,
        server_name=info.server_name,
        connected_since=info.connected_since,
        error_message=info.error_message,
    )


# =============================================================================
# Browsing
# =============================================================================


@sim_router.get("/browse", response_model=BrowseResponse)
async def browse_nodes(
    node_id: str | None = Query(None, description="NodeId to browse (None for roots)"),
) -> BrowseResponse:
    """Browse children of an OPC UA node.

    If ``node_id`` is omitted, returns the configured interface root nodes.
    """
    service = get_sim_service()
    try:
        nodes = await service.browse(node_id)
        return BrowseResponse(
            nodes=nodes,
            parent_node_id=node_id or "",
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        logger.exception("Browse error")
        raise HTTPException(status_code=500, detail=str(e)) from e


# =============================================================================
# Read / Write
# =============================================================================


@sim_router.get("/read", response_model=ReadResponse)
async def read_values(
    node_id: list[str] = Query(..., description="NodeId(s) to read"),  # noqa: B008
) -> ReadResponse:
    """Read one or more variable values."""
    service = get_sim_service()
    try:
        values = await service.read(node_id)
        return ReadResponse(values=values)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        logger.exception("Read error")
        raise HTTPException(status_code=500, detail=str(e)) from e


@sim_router.post("/write", response_model=WriteResponse)
async def write_value(request: WriteRequest) -> WriteResponse:
    """Write a value to a variable."""
    service = get_sim_service()
    try:
        success = await service.write(
            request.node_id,
            request.value,
            request.data_type,
        )
        return WriteResponse(success=success, node_id=request.node_id)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        logger.exception("Write error for %s", request.node_id)
        return WriteResponse(
            success=False,
            node_id=request.node_id,
            error=str(e),
        )


@sim_router.post("/write-multiple")
async def write_multiple(request: WriteMultipleRequest) -> list[WriteResponse]:
    """Write multiple values."""
    service = get_sim_service()
    results: list[WriteResponse] = []

    for w in request.writes:
        try:
            success = await service.write(w.node_id, w.value, w.data_type)
            results.append(WriteResponse(success=success, node_id=w.node_id))
        except Exception as e:
            results.append(WriteResponse(success=False, node_id=w.node_id, error=str(e)))

    return results


# =============================================================================
# Subscription (SSE)
# =============================================================================


@sim_router.get("/subscribe")
async def subscribe_sse(
    node_id: list[str] = Query(..., description="NodeId(s) to subscribe to"),  # noqa: B008
    interval_ms: int = Query(500, description="Subscription interval in ms"),  # noqa: B008
) -> StreamingResponse:
    """Server-Sent Events endpoint for live variable updates.

    Subscribes to the specified node(s) and streams value changes
    as SSE events.
    """
    service = get_sim_service()

    try:
        sub_id, queue = await service.start_monitoring(node_id, interval_ms)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    async def event_generator() -> AsyncIterator[str]:
        """Generate SSE events from the subscription queue."""
        try:
            async for value in service.get_change_stream(queue):
                data = json.dumps(value.model_dump())
                yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await service.stop_monitoring(sub_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
