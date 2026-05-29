"""Backward-compatible re-exports from plc-core."""

from plc_core.opcua.client import (  # noqa: F401
    OpcUaClient,
    SubscriptionHandler,
    _get_data_type_name,
    _to_json_value,
)

__all__ = [
    "OpcUaClient",
    "SubscriptionHandler",
]
