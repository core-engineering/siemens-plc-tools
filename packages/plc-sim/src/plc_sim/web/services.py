"""Service layer for the simulation web API.

Manages the OPC UA client connection as a singleton and provides
business logic for the API routes.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator

from plc_sim.core.client import OpcUaClient
from plc_sim.core.config import SimConfig, load_sim_config
from plc_sim.core.models import ConnectionInfo, ConnectionStatus, OpcUaNode, OpcUaValue

logger = logging.getLogger(__name__)


class SimService:
    """Service for OPC UA interaction.

    Manages a single OPC UA client connection and provides
    async methods for the web routes.
    """

    def __init__(self) -> None:
        self._client: OpcUaClient | None = None
        self._config: SimConfig | None = None
        self._change_queues: list[asyncio.Queue[OpcUaValue]] = []

    @property
    def config(self) -> SimConfig:
        """Get the current configuration, loading from plc.yaml if needed."""
        if self._config is None:
            try:
                self._config = load_sim_config()
            except (FileNotFoundError, KeyError):
                self._config = SimConfig()
        return self._config

    def set_config(self, config: SimConfig) -> None:
        """Override the configuration.

        Parameters
        ----------
        config : SimConfig
            New configuration to use.
        """
        self._config = config
        # Reset client if endpoint changed
        if self._client is not None:
            self._client = None

    @property
    def client(self) -> OpcUaClient | None:
        """Current OPC UA client (None if not connected)."""
        return self._client

    async def connect(self, endpoint: str | None = None) -> ConnectionInfo:
        """Connect to the OPC UA server.

        Parameters
        ----------
        endpoint : str | None
            Override endpoint URL.

        Returns
        -------
        ConnectionInfo
            Connection result.
        """
        config = self.config
        if endpoint:
            config.endpoint = endpoint

        self._client = OpcUaClient(config.opcua)
        return await self._client.connect()

    async def disconnect(self) -> None:
        """Disconnect from the OPC UA server."""
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    async def get_status(self) -> ConnectionInfo:
        """Get current connection status.

        Returns
        -------
        ConnectionInfo
            Current status.
        """
        if self._client is not None:
            return await self._client.get_status()

        return ConnectionInfo(
            status=ConnectionStatus.DISCONNECTED,
            endpoint=self.config.endpoint,
        )

    async def browse(self, node_id: str | None = None) -> list[OpcUaNode]:
        """Browse children of a node.

        Parameters
        ----------
        node_id : str | None
            Node to browse. None for interface roots.

        Returns
        -------
        list[OpcUaNode]
            Child nodes.

        Raises
        ------
        RuntimeError
            If not connected.
        """
        if self._client is None or not self._client.is_connected:
            raise RuntimeError("Not connected to OPC UA server")
        return await self._client.browse_node(node_id)

    async def read(self, node_ids: list[str]) -> list[OpcUaValue]:
        """Read variable values.

        Parameters
        ----------
        node_ids : list[str]
            NodeIds to read.

        Returns
        -------
        list[OpcUaValue]
            Current values.
        """
        if self._client is None or not self._client.is_connected:
            raise RuntimeError("Not connected to OPC UA server")
        return await self._client.read_values(node_ids)

    async def write(
        self,
        node_id: str,
        value: str | int | float | bool,
        data_type: str | None = None,
    ) -> bool:
        """Write a value to a variable.

        Parameters
        ----------
        node_id : str
            NodeId to write to.
        value : str | int | float | bool
            Value to write.
        data_type : str | None
            Optional data type override.

        Returns
        -------
        bool
            True if successful.
        """
        if self._client is None or not self._client.is_connected:
            raise RuntimeError("Not connected to OPC UA server")
        return await self._client.write_value(node_id, value, data_type)

    async def start_monitoring(
        self,
        node_ids: list[str],
        interval_ms: int | None = None,
    ) -> tuple[str, asyncio.Queue[OpcUaValue]]:
        """Start monitoring variables via subscription.

        Parameters
        ----------
        node_ids : list[str]
            NodeIds to monitor.
        interval_ms : int | None
            Subscription interval.

        Returns
        -------
        tuple[str, asyncio.Queue[OpcUaValue]]
            Subscription ID and queue for changes.
        """
        if self._client is None or not self._client.is_connected:
            raise RuntimeError("Not connected to OPC UA server")

        queue: asyncio.Queue[OpcUaValue] = asyncio.Queue(maxsize=1000)
        self._change_queues.append(queue)

        sub_id = await self._client.subscribe(node_ids, queue, interval_ms)
        return sub_id, queue

    async def stop_monitoring(self, subscription_id: str) -> None:
        """Stop monitoring a subscription.

        Parameters
        ----------
        subscription_id : str
            Subscription to cancel.
        """
        if self._client is not None:
            await self._client.unsubscribe(subscription_id)

    async def get_change_stream(self, queue: asyncio.Queue[OpcUaValue]) -> AsyncGenerator[OpcUaValue, None]:
        """Yield value changes from a subscription queue.

        Parameters
        ----------
        queue : asyncio.Queue[OpcUaValue]
            Queue to read from.

        Yields
        ------
        OpcUaValue
            Each value change as it arrives.
        """
        try:
            while True:
                value = await queue.get()
                yield value
        except asyncio.CancelledError:
            pass
        finally:
            if queue in self._change_queues:
                self._change_queues.remove(queue)


# =============================================================================
# Global singleton
# =============================================================================

_service: SimService | None = None


def get_sim_service() -> SimService:
    """Get or create the global SimService singleton.

    Returns
    -------
    SimService
        The shared service instance.
    """
    global _service
    if _service is None:
        _service = SimService()
    return _service
