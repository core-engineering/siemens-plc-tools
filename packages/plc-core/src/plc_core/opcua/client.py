"""Async OPC UA client wrapper.

Provides a clean interface over ``asyncua.Client`` for connection
lifecycle management, node browsing, variable read/write, and
subscription management.

Example
-------
>>> import asyncio
>>> from plc_core.opcua.client import OpcUaClient
>>> from plc_core.opcua.config import OpcUaConfig
>>>
>>> async def main():
...     client = OpcUaClient(OpcUaConfig(endpoint="opc.tcp://192.168.1.50:4840"))
...     info = await client.connect()
...     nodes = await client.browse_node()
...     await client.disconnect()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from asyncua import Client, Node, ua

from plc_core.opcua.config import OpcUaConfig
from plc_core.opcua.models import (
    ConnectionInfo,
    ConnectionStatus,
    NodeClass,
    OpcUaNode,
    OpcUaValue,
)

logger = logging.getLogger(__name__)

# Map OPC UA NodeClass enum to our simplified model
_NODE_CLASS_MAP = {
    ua.NodeClass.Object: NodeClass.OBJECT,
    ua.NodeClass.Variable: NodeClass.VARIABLE,
    ua.NodeClass.Method: NodeClass.METHOD,
    ua.NodeClass.ObjectType: NodeClass.OBJECT_TYPE,
    ua.NodeClass.VariableType: NodeClass.VARIABLE_TYPE,
}

# OPC UA data type NodeId → human-readable name
_DATA_TYPE_NAMES: dict[int, str] = {
    1: "Boolean",
    2: "SByte",
    3: "Byte",
    4: "Int16",
    5: "UInt16",
    6: "Int32",
    7: "UInt32",
    8: "Int64",
    9: "UInt64",
    10: "Float",
    11: "Double",
    12: "String",
    13: "DateTime",
    14: "Guid",
    15: "ByteString",
}

# Reverse: name → type for writing
_TYPE_CONVERTERS: dict[str, Callable[[Any], Any]] = {
    "Boolean": lambda v: v if isinstance(v, bool) else str(v).lower() in ("true", "1", "yes"),
    "SByte": lambda v: int(v),
    "Byte": lambda v: int(v),
    "Int16": lambda v: int(v),
    "UInt16": lambda v: int(v),
    "Int32": lambda v: int(v),
    "UInt32": lambda v: int(v),
    "Int64": lambda v: int(v),
    "UInt64": lambda v: int(v),
    "Float": lambda v: float(v),
    "Double": lambda v: float(v),
    "String": lambda v: str(v),
}


class SubscriptionHandler:
    """Handler for OPC UA data change notifications.

    Pushes value changes into an asyncio queue for SSE streaming.
    """

    def __init__(self, queue: asyncio.Queue[OpcUaValue]) -> None:
        self._queue = queue

    def datachange_notification(self, node: Node, val: Any, data: Any) -> None:
        """Called by asyncua when a subscribed variable changes."""
        try:
            node_id = node.nodeid.to_string()
            source_ts = ""
            server_ts = ""
            status_code = 0

            if data and data.monitored_item and data.monitored_item.Value:
                dv = data.monitored_item.Value
                if dv.SourceTimestamp:
                    source_ts = dv.SourceTimestamp.isoformat()
                if dv.ServerTimestamp:
                    server_ts = dv.ServerTimestamp.isoformat()
                if dv.StatusCode:
                    status_code = dv.StatusCode.value

            value = OpcUaValue(
                node_id=node_id,
                value=_to_json_value(val),
                source_timestamp=source_ts,
                server_timestamp=server_ts,
                status_code=status_code,
                quality="Good" if status_code == 0 else f"Bad (0x{status_code:08X})",
            )
            # Non-blocking put — drop if queue is full
            try:
                self._queue.put_nowait(value)
            except asyncio.QueueFull:
                pass
        except Exception:
            logger.exception("Error in datachange_notification")


def _to_json_value(val: Any) -> str | int | float | bool | None:
    """Convert an OPC UA value to a JSON-serializable Python type."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return val
    if isinstance(val, str):
        return val
    # Handle numpy types from asyncua
    try:
        item = val.item()  # type: ignore[union-attr]
        if isinstance(item, bool | int | float | str) or item is None:
            return item
    except (AttributeError, ValueError):
        pass
    return str(val)


def _get_data_type_name(type_node_id: ua.NodeId) -> str:
    """Get human-readable data type name from NodeId."""
    if isinstance(type_node_id.Identifier, int):
        if type_node_id.NamespaceIndex == 0:
            return _DATA_TYPE_NAMES.get(type_node_id.Identifier, f"Type_{type_node_id.Identifier}")
        # Non-standard namespace — likely a struct/UDT
        return "Struct"
    if isinstance(type_node_id.Identifier, str):
        return type_node_id.Identifier
    return "Struct"


class OpcUaClient:
    """Async OPC UA client for PLC interaction.

    Parameters
    ----------
    config : OpcUaConfig
        Connection and interface configuration.
    """

    def __init__(self, config: OpcUaConfig) -> None:
        self._config = config
        self._client: Client | None = None
        self._status = ConnectionStatus.DISCONNECTED
        self._error_message = ""
        self._connected_since: datetime | None = None
        self._server_name = ""
        self._namespace_uris: list[str] = []
        self._session_id = ""
        self._subscriptions: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    @property
    def status(self) -> ConnectionStatus:
        """Current connection status."""
        return self._status

    @property
    def is_connected(self) -> bool:
        """Whether the client is connected."""
        return self._status == ConnectionStatus.CONNECTED and self._client is not None

    async def connect(self, endpoint: str | None = None) -> ConnectionInfo:
        """Connect to the OPC UA server.

        Parameters
        ----------
        endpoint : str | None
            Override endpoint URL. Uses config value if None.

        Returns
        -------
        ConnectionInfo
            Connection status after attempting to connect.
        """
        async with self._lock:
            if self.is_connected:
                return await self.get_status()

            url = endpoint or self._config.endpoint
            self._status = ConnectionStatus.CONNECTING
            self._error_message = ""

            try:
                self._client = Client(url=url, timeout=self._config.connect_timeout_s)
                await self._client.connect()

                # Read server info
                self._namespace_uris = await self._client.get_namespace_array()
                self._connected_since = datetime.now(UTC)

                # Try to read server application name
                try:
                    server_node = self._client.get_node(ua.NodeId(ua.ObjectIds.Server))
                    server_status = await server_node.get_child(
                        ["0:ServerStatus", "0:BuildInfo", "0:ProductName"]
                    )
                    self._server_name = str(await server_status.read_value())
                except Exception:
                    self._server_name = "Unknown"

                try:
                    self._session_id = str(self._client.uaclient.protocol.channel.security_token.TokenId)
                except (AttributeError, Exception):
                    self._session_id = "active"
                self._status = ConnectionStatus.CONNECTED
                logger.info("Connected to OPC UA server at %s", url)

            except Exception as e:
                self._status = ConnectionStatus.ERROR
                self._error_message = str(e)
                self._client = None
                logger.error("Failed to connect to %s: %s", url, e)

        return await self.get_status()

    async def disconnect(self) -> None:
        """Disconnect from the OPC UA server."""
        async with self._lock:
            if self._client is not None:
                try:
                    # Cancel all subscriptions
                    for sub in self._subscriptions.values():
                        try:
                            await sub.delete()
                        except Exception:
                            pass
                    self._subscriptions.clear()

                    await self._client.disconnect()
                    logger.info("Disconnected from OPC UA server")
                except Exception as e:
                    logger.warning("Error during disconnect: %s", e)
                finally:
                    self._client = None
                    self._status = ConnectionStatus.DISCONNECTED
                    self._connected_since = None
                    self._server_name = ""
                    self._session_id = ""
                    self._namespace_uris = []

    async def get_status(self) -> ConnectionInfo:
        """Get current connection status.

        Returns
        -------
        ConnectionInfo
            Current connection information.
        """
        return ConnectionInfo(
            status=self._status,
            endpoint=self._config.endpoint,
            server_name=self._server_name,
            session_id=self._session_id,
            namespaces=self._namespace_uris,
            error_message=self._error_message,
            connected_since=(self._connected_since.isoformat() if self._connected_since else ""),
        )

    async def _resolve_interface_root(self) -> list[Node]:
        """Resolve the configured interface root nodes.

        Searches for the interface node under Objects, and also under
        common S7 locations like ServerInterfaces. Then finds the
        configured namespace nodes under the interface.

        Navigates: Objects → [ServerInterfaces] → <interface> → <namespace1>, ...

        Returns
        -------
        list[Node]
            Root nodes under the configured interface.

        Raises
        ------
        RuntimeError
            If not connected or interface not found.
        """
        if not self._client:
            raise RuntimeError("Not connected to OPC UA server")

        objects = self._client.nodes.objects
        children = await objects.get_children()

        # Find the interface node (e.g., "Simulation")
        # Search directly under Objects first, then under ServerInterfaces
        interface_node: Node | None = None

        for child in children:
            name = await child.read_browse_name()
            if name.Name == self._config.interface:
                interface_node = child
                break

        if interface_node is None:
            # Search under ServerInterfaces (Siemens S7 pattern)
            for child in children:
                name = await child.read_browse_name()
                if name.Name == "ServerInterfaces":
                    sub_children = await child.get_children()
                    for sub_child in sub_children:
                        sub_name = await sub_child.read_browse_name()
                        if sub_name.Name == self._config.interface:
                            interface_node = sub_child
                            break
                    break

        if interface_node is None:
            logger.warning(
                "Interface '%s' not found. Returning all Objects children.",
                self._config.interface,
            )
            interface_node = objects

        # Return all children under the interface — discover dynamically
        # rather than filtering by the static namespaces config list
        interface_children: list[Node] = await interface_node.get_children()
        return interface_children

    async def browse_node(self, node_id: str | None = None) -> list[OpcUaNode]:
        """Browse children of a node.

        Parameters
        ----------
        node_id : str | None
            NodeId to browse. If None, returns the configured interface
            root nodes.

        Returns
        -------
        list[OpcUaNode]
            Child nodes with metadata.
        """
        if not self._client:
            raise RuntimeError("Not connected to OPC UA server")

        if node_id is None:
            # Return interface root nodes
            roots = await self._resolve_interface_root()
            return [await self._node_to_model(root) for root in roots]

        node = self._client.get_node(node_id)
        children = await node.get_children()
        return [await self._node_to_model(child, parent_node_id=node_id) for child in children]

    async def _node_to_model(self, node: Node, parent_node_id: str = "") -> OpcUaNode:
        """Convert an asyncua Node to our OpcUaNode model.

        Parameters
        ----------
        node : Node
            The asyncua node object.
        parent_node_id : str
            NodeId of the parent.

        Returns
        -------
        OpcUaNode
            Node metadata model.
        """
        node_id = node.nodeid.to_string()
        browse_name = await node.read_browse_name()
        display_name = (await node.read_display_name()).Text or browse_name.Name
        node_class_raw = await node.read_node_class()
        node_class = _NODE_CLASS_MAP.get(node_class_raw, NodeClass.OBJECT)

        data_type = ""
        is_writable = False

        if node_class == NodeClass.VARIABLE:
            try:
                dt_node_id = await node.read_data_type()
                data_type = _get_data_type_name(dt_node_id)
            except Exception:
                pass

            try:
                access_level = await node.read_attribute(ua.AttributeIds.AccessLevel)
                access_val = access_level.Value.Value
                if isinstance(access_val, int):
                    is_writable = bool(access_val & ua.AccessLevel.CurrentWrite.mask)
                else:
                    is_writable = bool(int(access_val) & ua.AccessLevel.CurrentWrite.mask)
            except Exception:
                pass

        # Count children for UI tree expansion
        try:
            children = await node.get_children()
            children_count = len(children)
        except Exception:
            children_count = 0

        return OpcUaNode(
            node_id=node_id,
            browse_name=browse_name.Name,
            display_name=display_name,
            node_class=node_class,
            data_type=data_type,
            is_writable=is_writable,
            namespace_index=node.nodeid.NamespaceIndex,
            parent_node_id=parent_node_id,
            children_count=children_count,
        )

    async def read_value(self, node_id: str) -> OpcUaValue:
        """Read a single variable value.

        Parameters
        ----------
        node_id : str
            NodeId string of the variable.

        Returns
        -------
        OpcUaValue
            Current value with metadata.
        """
        if not self._client:
            raise RuntimeError("Not connected to OPC UA server")

        node = self._client.get_node(node_id)
        data_value = await node.read_data_value()

        display_name = ""
        data_type = ""
        try:
            display_name = (await node.read_display_name()).Text or ""
            dt_node_id = await node.read_data_type()
            data_type = _get_data_type_name(dt_node_id)
        except Exception:
            pass

        source_ts = ""
        server_ts = ""
        if data_value.SourceTimestamp:
            source_ts = data_value.SourceTimestamp.isoformat()
        if data_value.ServerTimestamp:
            server_ts = data_value.ServerTimestamp.isoformat()

        status_code = 0
        if data_value.StatusCode:
            status_code = data_value.StatusCode.value

        return OpcUaValue(
            node_id=node_id,
            display_name=display_name,
            value=_to_json_value(data_value.Value.Value if data_value.Value else None),
            data_type=data_type,
            source_timestamp=source_ts,
            server_timestamp=server_ts,
            status_code=status_code,
            quality="Good" if status_code == 0 else f"Bad (0x{status_code:08X})",
        )

    async def read_values(self, node_ids: list[str]) -> list[OpcUaValue]:
        """Read multiple variable values.

        Parameters
        ----------
        node_ids : list[str]
            NodeId strings to read.

        Returns
        -------
        list[OpcUaValue]
            Current values with metadata.
        """
        return [await self.read_value(nid) for nid in node_ids]

    async def write_value(
        self,
        node_id: str,
        value: Any,
        data_type: str | None = None,
    ) -> bool:
        """Write a value to a variable.

        Parameters
        ----------
        node_id : str
            NodeId string of the variable.
        value : Any
            Value to write (will be type-converted).
        data_type : str | None
            Override data type name for conversion. If None,
            reads the node's data type.

        Returns
        -------
        bool
            True if write succeeded.

        Raises
        ------
        RuntimeError
            If not connected.
        ValueError
            If the value cannot be converted.
        """
        if not self._client:
            raise RuntimeError("Not connected to OPC UA server")

        node = self._client.get_node(node_id)

        # Determine data type
        if data_type is None:
            dt_node_id = await node.read_data_type()
            data_type = _get_data_type_name(dt_node_id)

        # For unknown/struct types, read the actual variant type from the node
        variant_type = self._get_variant_type(data_type)
        if variant_type == ua.VariantType.Variant:
            dv_current = await node.read_data_value()
            if dv_current.Value and dv_current.Value.VariantType:
                variant_type = dv_current.Value.VariantType
                # Re-resolve data_type name for converter lookup
                reverse = {
                    v: k
                    for k, v in {
                        "Boolean": ua.VariantType.Boolean,
                        "Byte": ua.VariantType.Byte,
                        "SByte": ua.VariantType.SByte,
                        "Int16": ua.VariantType.Int16,
                        "UInt16": ua.VariantType.UInt16,
                        "Int32": ua.VariantType.Int32,
                        "UInt32": ua.VariantType.UInt32,
                        "Int64": ua.VariantType.Int64,
                        "UInt64": ua.VariantType.UInt64,
                        "Float": ua.VariantType.Float,
                        "Double": ua.VariantType.Double,
                        "String": ua.VariantType.String,
                    }.items()
                }
                data_type = reverse.get(variant_type, data_type)

        # Convert value to the correct Python type
        converter = _TYPE_CONVERTERS.get(data_type)
        if converter:
            converted = converter(value)
        else:
            converted = value

        # Build the appropriate ua.Variant
        variant = ua.Variant(converted, variant_type)

        dv = ua.DataValue(variant)
        await node.write_value(dv)
        logger.info("Wrote %s = %s (%s) to %s", node_id, converted, data_type, node_id)
        return True

    @staticmethod
    def _get_variant_type(data_type: str) -> ua.VariantType:
        """Map data type name to ua.VariantType."""
        mapping: dict[str, ua.VariantType] = {
            "Boolean": ua.VariantType.Boolean,
            "SByte": ua.VariantType.SByte,
            "Byte": ua.VariantType.Byte,
            "Int16": ua.VariantType.Int16,
            "UInt16": ua.VariantType.UInt16,
            "Int32": ua.VariantType.Int32,
            "UInt32": ua.VariantType.UInt32,
            "Int64": ua.VariantType.Int64,
            "UInt64": ua.VariantType.UInt64,
            "Float": ua.VariantType.Float,
            "Double": ua.VariantType.Double,
            "String": ua.VariantType.String,
        }
        return mapping.get(data_type, ua.VariantType.Variant)

    async def subscribe(
        self,
        node_ids: list[str],
        queue: asyncio.Queue[OpcUaValue],
        interval_ms: int | None = None,
    ) -> str:
        """Subscribe to data changes on variables.

        Parameters
        ----------
        node_ids : list[str]
            NodeIds to subscribe to.
        queue : asyncio.Queue[OpcUaValue]
            Queue to push value changes into.
        interval_ms : int | None
            Publishing interval. Uses config default if None.

        Returns
        -------
        str
            Subscription identifier for later unsubscription.
        """
        if not self._client:
            raise RuntimeError("Not connected to OPC UA server")

        interval = interval_ms or self._config.subscription_interval_ms
        handler = SubscriptionHandler(queue)

        sub = await self._client.create_subscription(interval, handler)
        nodes = [self._client.get_node(nid) for nid in node_ids]
        await sub.subscribe_data_change(nodes)

        sub_id = str(sub.subscription_id)
        self._subscriptions[sub_id] = sub
        logger.info("Created subscription %s for %d nodes", sub_id, len(node_ids))
        return sub_id

    async def unsubscribe(self, subscription_id: str) -> None:
        """Cancel a subscription.

        Parameters
        ----------
        subscription_id : str
            Subscription identifier from :meth:`subscribe`.
        """
        sub = self._subscriptions.pop(subscription_id, None)
        if sub is not None:
            try:
                await sub.delete()
                logger.info("Deleted subscription %s", subscription_id)
            except Exception as e:
                logger.warning("Error deleting subscription %s: %s", subscription_id, e)
