"""Backward-compatible re-exports from plc-core."""

from plc_core.opcua.models import (  # noqa: F401
    ConnectionInfo,
    ConnectionStatus,
    NodeClass,
    OpcUaNode,
    OpcUaValue,
)

__all__ = [
    "ConnectionInfo",
    "ConnectionStatus",
    "NodeClass",
    "OpcUaNode",
    "OpcUaValue",
]
