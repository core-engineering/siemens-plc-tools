"""Trace configuration (plc.yaml ``sim.trace`` section)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plc_core.config.loader import find_config_file, load_yaml


@dataclass
class TraceConfig:
    """Trace module configuration.

    Attributes
    ----------
    db_path : str
        Tag path of the trace interface DB under the OPC UA server interface.
    fetch_chunk : int
        Maximum array elements per OPC UA read during fetch.
    output_dir : str
        Default directory (relative to the project root) for fetched traces.
    """

    db_path: str = "TraceData"
    fetch_chunk: int = 500
    output_dir: str = ".sim/traces"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TraceConfig:
        """Create from a raw YAML dictionary."""
        return cls(
            db_path=data.get("db_path", "TraceData"),
            fetch_chunk=int(data.get("fetch_chunk", 500)),
            output_dir=data.get("output_dir", ".sim/traces"),
        )


def load_trace_config(start_path: Path | None = None) -> tuple[TraceConfig, dict[str, Any]]:
    """Load the ``sim.trace`` section (and the raw ``sim`` dict) from plc.yaml.

    Returns
    -------
    tuple[TraceConfig, dict[str, Any]]
        The parsed trace config and the raw ``sim`` mapping (endpoint,
        interface, namespaces, testing, ...) for connection setup.
    """
    cfg_file = find_config_file(start_path)
    if cfg_file is None:
        raise FileNotFoundError("plc.yaml not found (searched upward from start_path)")
    raw = load_yaml(cfg_file)
    sim_raw: dict[str, Any] = raw.get("sim", {}) or {}
    return TraceConfig.from_dict(sim_raw.get("trace", {}) or {}), sim_raw
