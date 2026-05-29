"""OPC UA client infrastructure for PLC Tools.

Provides a shared async OPC UA client, data models, and configuration
used by plc-sim, plc-sup, and other packages that interact with PLCs.
"""

from plc_core.opcua.client import OpcUaClient, SubscriptionHandler
from plc_core.opcua.config import OpcUaConfig
from plc_core.opcua.models import (
    ConnectionInfo,
    ConnectionStatus,
    NodeClass,
    OpcUaNode,
    OpcUaValue,
)

__all__ = [
    "OpcUaClient",
    "OpcUaConfig",
    "SubscriptionHandler",
    "ConnectionInfo",
    "ConnectionStatus",
    "NodeClass",
    "OpcUaNode",
    "OpcUaValue",
]
