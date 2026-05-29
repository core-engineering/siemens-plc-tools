"""Pydantic request/response schemas for the simulation API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from plc_sim.core.models import ConnectionStatus, OpcUaNode, OpcUaValue

# =============================================================================
# Request schemas
# =============================================================================


class ConnectRequest(BaseModel):
    """Request to connect to an OPC UA server."""

    endpoint: str = ""


class WriteRequest(BaseModel):
    """Request to write a value to a variable."""

    node_id: str
    value: str | int | float | bool
    data_type: str | None = None


class WriteMultipleRequest(BaseModel):
    """Request to write multiple values."""

    writes: list[WriteRequest]


# =============================================================================
# Response schemas
# =============================================================================


class SimConfigResponse(BaseModel):
    """Configuration response."""

    endpoint: str
    interface: str
    namespaces: list[str]
    subscription_interval_ms: int
    has_config: bool


class ConnectResponse(BaseModel):
    """Connection response."""

    status: ConnectionStatus
    endpoint: str = ""
    server_name: str = ""
    session_id: str = ""
    namespaces: list[str] = Field(default_factory=list)
    error_message: str = ""
    connected_since: str = ""


class StatusResponse(BaseModel):
    """Connection status response."""

    status: ConnectionStatus
    endpoint: str = ""
    server_name: str = ""
    connected_since: str = ""
    error_message: str = ""


class BrowseResponse(BaseModel):
    """Browse response with child nodes."""

    nodes: list[OpcUaNode]
    parent_node_id: str = ""


class ReadResponse(BaseModel):
    """Read response with values."""

    values: list[OpcUaValue]


class WriteResponse(BaseModel):
    """Write result for a single variable."""

    success: bool
    node_id: str
    error: str = ""
