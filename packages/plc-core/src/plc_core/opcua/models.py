"""OPC UA data models for PLC Tools.

Provides Pydantic models representing OPC UA nodes, values, and
connection state.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class NodeClass(str, Enum):
    """OPC UA node class."""

    OBJECT = "Object"
    VARIABLE = "Variable"
    METHOD = "Method"
    OBJECT_TYPE = "ObjectType"
    VARIABLE_TYPE = "VariableType"


class ConnectionStatus(str, Enum):
    """OPC UA connection state."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class OpcUaNode(BaseModel):
    """Represents an OPC UA node in the address space.

    Attributes
    ----------
    node_id : str
        OPC UA NodeId as string (e.g. ``ns=3;s=ProcessData``).
    browse_name : str
        Browse name of the node.
    display_name : str
        Human-readable display name.
    node_class : NodeClass
        Whether this is an Object, Variable, etc.
    data_type : str
        Data type name for variables (e.g. ``Boolean``, ``Float``).
    is_writable : bool
        Whether the node value can be written.
    namespace_index : int
        Namespace index.
    parent_node_id : str
        NodeId of the parent node.
    children_count : int
        Number of child nodes (for lazy loading indicator).
    """

    node_id: str
    browse_name: str
    display_name: str
    node_class: NodeClass = NodeClass.VARIABLE
    data_type: str = ""
    is_writable: bool = False
    namespace_index: int = 0
    parent_node_id: str = ""
    children_count: int = 0


class OpcUaValue(BaseModel):
    """A variable value read from OPC UA.

    Attributes
    ----------
    node_id : str
        OPC UA NodeId as string.
    display_name : str
        Human-readable name.
    value : str | int | float | bool | None
        Current value (JSON-serializable).
    data_type : str
        Data type name.
    source_timestamp : str
        Source timestamp in ISO format.
    server_timestamp : str
        Server timestamp in ISO format.
    status_code : int
        OPC UA status code (0 = Good).
    quality : str
        Human-readable quality string.
    """

    node_id: str
    display_name: str = ""
    value: str | int | float | bool | None = None
    data_type: str = ""
    source_timestamp: str = ""
    server_timestamp: str = ""
    status_code: int = 0
    quality: str = "Good"


class ConnectionInfo(BaseModel):
    """OPC UA connection status information.

    Attributes
    ----------
    status : ConnectionStatus
        Current connection state.
    endpoint : str
        Server endpoint URL.
    server_name : str
        Server application name.
    session_id : str
        Active session identifier.
    namespaces : list[str]
        Available namespace URIs.
    error_message : str
        Error description if status is ERROR.
    connected_since : str
        ISO timestamp of when the connection was established.
    """

    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    endpoint: str = ""
    server_name: str = ""
    session_id: str = ""
    namespaces: list[str] = Field(default_factory=list)
    error_message: str = ""
    connected_since: str = ""
