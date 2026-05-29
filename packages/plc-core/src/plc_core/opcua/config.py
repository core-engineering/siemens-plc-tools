"""OPC UA connection configuration.

Provides a dataclass for OPC UA client settings extracted from
the simulation and supervision configurations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OpcUaConfig:
    """OPC UA client connection configuration.

    Attributes
    ----------
    endpoint : str
        OPC UA server endpoint URL.
    interface : str
        Interface name to browse under Objects (e.g. ``Simulation``).
    namespaces : list[str]
        Namespace browse names to discover under the interface.
    subscription_interval_ms : int
        Default publishing interval for subscriptions in milliseconds.
    connect_timeout_s : float
        Connection timeout in seconds.
    """

    endpoint: str = "opc.tcp://localhost:4840"
    interface: str = "Simulation"
    namespaces: list[str] = field(default_factory=list)
    subscription_interval_ms: int = 500
    connect_timeout_s: float = 10.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpcUaConfig:
        """Create configuration from a dictionary.

        Parameters
        ----------
        data : dict[str, Any]
            Dictionary with configuration values. Unknown keys are
            silently ignored.

        Returns
        -------
        OpcUaConfig
            Populated configuration instance.
        """
        return cls(
            endpoint=data.get("endpoint", cls.endpoint),
            interface=data.get("interface", cls.interface),
            namespaces=data.get("namespaces", []),
            subscription_interval_ms=data.get("subscription_interval_ms", cls.subscription_interval_ms),
            connect_timeout_s=data.get("connect_timeout_s", cls.connect_timeout_s),
        )
