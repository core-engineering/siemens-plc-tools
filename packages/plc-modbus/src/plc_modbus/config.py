"""Modbus connection configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModbusConfig:
    """Configuration for a Modbus TCP client.

    Parameters
    ----------
    host : str
        Server hostname or IP address.
    port : int
        TCP port (default 502 — Modbus standard).
    unit_id : int
        Modbus slave/unit identifier (default 1).
    timeout_s : float
        Per-request timeout in seconds (default 5.0).
    """

    host: str
    port: int = 502
    unit_id: int = 1
    timeout_s: float = 5.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ModbusConfig:
        """Build a ``ModbusConfig`` from a YAML/dict block.

        Required keys: ``host``. Optional: ``port``, ``unit_id``, ``timeout_s``.
        """
        if "host" not in raw:
            raise ValueError("ModbusConfig requires a 'host' field")
        return cls(
            host=str(raw["host"]),
            port=int(raw.get("port", 502)),
            unit_id=int(raw.get("unit_id", 1)),
            timeout_s=float(raw.get("timeout_s", 5.0)),
        )
