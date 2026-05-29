"""Simulation configuration loading and management.

Loads the ``sim:`` section from plc.yaml to configure OPC UA
connection parameters.

Example
-------
>>> from plc_sim.core.config import load_sim_config
>>> config = load_sim_config()
>>> print(config.endpoint)
opc.tcp://192.168.1.50:4840
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plc_core.config import find_config_file, load_yaml
from plc_core.opcua.config import OpcUaConfig
from plc_modbus import ModbusConfig

_DEFAULT_BASELINE_GLOBS: tuple[str, ...] = (
    "program-blocks/**/*.s7dcl",
    "data-types/**/*.s7dcl",
    "tags/**/*.xml",
)


@dataclass
class SimTestConfig:
    """Integration test configuration.

    Attributes
    ----------
    test_dir : str
        Directory containing YAML test scenarios.
    cache_dir : str
        Directory for tag resolution cache.
    cache_ttl_hours : int
        Hours before tag cache is considered stale.
    scenario_timeout_s : float
        Default scenario timeout in seconds.
    baseline_source_globs : list[str]
        Glob patterns (relative to the project root) used to compute the
        baseline fingerprint for the persisted test-results cache.
    results_cache_filename : str
        Filename of the persisted test-results cache, written under ``cache_dir``.
    """

    test_dir: str = "integration-tests"
    cache_dir: str = ".sim"
    cache_ttl_hours: int = 24
    scenario_timeout_s: float = 60.0
    baseline_source_globs: list[str] = field(default_factory=lambda: list(_DEFAULT_BASELINE_GLOBS))
    results_cache_filename: str = "test_results.json"
    write_settle_s: float = 0.3

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SimTestConfig:
        """Create from dictionary."""
        globs = data.get("baseline_source_globs")
        return cls(
            test_dir=data.get("test_dir", "integration-tests"),
            cache_dir=data.get("cache_dir", ".sim"),
            cache_ttl_hours=data.get("cache_ttl_hours", 24),
            scenario_timeout_s=data.get("scenario_timeout_s", 60.0),
            baseline_source_globs=(list(globs) if globs is not None else list(_DEFAULT_BASELINE_GLOBS)),
            results_cache_filename=data.get("results_cache_filename", "test_results.json"),
            write_settle_s=data.get("write_settle_s", 0.3),
        )


@dataclass
class SimConfig:
    """OPC UA simulation configuration.

    Attributes
    ----------
    opcua : OpcUaConfig
        OPC UA connection settings (endpoint, interface, namespaces, etc.).
    config_path : Path | None
        Path to the config file (set after loading).
    testing : SimTestConfig
        Integration test settings.
    project_name : str | None
        Project name from plc.yaml.
    project_code : str | None
        Project code from plc.yaml.
    """

    opcua: OpcUaConfig = field(default_factory=OpcUaConfig)
    config_path: Path | None = None
    testing: SimTestConfig = field(default_factory=SimTestConfig)
    project_name: str | None = None
    project_code: str | None = None
    # Optional Modbus TCP client configuration. When present, the test
    # runner exposes the modbus_read / modbus_assert / modbus_wait_until
    # step types. When None, those steps return ERROR with a clear message.
    modbus: ModbusConfig | None = None

    # ------------------------------------------------------------------
    # Backward-compatible properties delegating to self.opcua
    # ------------------------------------------------------------------

    @property
    def endpoint(self) -> str:
        """OPC UA server endpoint URL."""
        return self.opcua.endpoint

    @endpoint.setter
    def endpoint(self, value: str) -> None:
        self.opcua.endpoint = value

    @property
    def interface(self) -> str:
        """Name of the OPC UA server interface to browse."""
        return self.opcua.interface

    @interface.setter
    def interface(self, value: str) -> None:
        self.opcua.interface = value

    @property
    def namespaces(self) -> list[str]:
        """Root node names under the interface to expose."""
        return self.opcua.namespaces

    @namespaces.setter
    def namespaces(self, value: list[str]) -> None:
        self.opcua.namespaces = value

    @property
    def subscription_interval_ms(self) -> int:
        """Default subscription interval in milliseconds."""
        return self.opcua.subscription_interval_ms

    @subscription_interval_ms.setter
    def subscription_interval_ms(self, value: int) -> None:
        self.opcua.subscription_interval_ms = value

    @property
    def connect_timeout_s(self) -> float:
        """Connection timeout in seconds."""
        return self.opcua.connect_timeout_s

    @connect_timeout_s.setter
    def connect_timeout_s(self, value: float) -> None:
        self.opcua.connect_timeout_s = value

    @classmethod
    def from_dict(cls, data: dict[str, Any], config_path: Path | None = None) -> SimConfig:
        """Create config from dictionary.

        Parameters
        ----------
        data : dict[str, Any]
            Configuration dictionary (the ``sim:`` section).
        config_path : Path | None
            Path to the plc.yaml file.

        Returns
        -------
        SimConfig
            Loaded configuration.
        """
        testing_data = data.get("testing", {})
        testing = SimTestConfig.from_dict(testing_data) if testing_data else SimTestConfig()

        opcua = OpcUaConfig.from_dict(data)

        modbus_data = data.get("modbus")
        modbus = ModbusConfig.from_dict(modbus_data) if modbus_data else None

        return cls(
            opcua=opcua,
            config_path=config_path,
            testing=testing,
            modbus=modbus,
        )


def load_sim_config(path: Path | None = None) -> SimConfig:
    """Load simulation configuration from plc.yaml.

    Reads the ``sim:`` section from the unified plc.yaml config file.

    Parameters
    ----------
    path : Path | None
        Explicit path to config file or directory.
        If None, searches current and parent directories.

    Returns
    -------
    SimConfig
        Loaded configuration.

    Raises
    ------
    FileNotFoundError
        If no config file is found.
    KeyError
        If the ``sim:`` section is missing.
    """
    if path is not None:
        config_path = Path(path).resolve()
        if config_path.is_dir():
            found = find_config_file(config_path)
            if found is None:
                raise FileNotFoundError(f"No plc.yaml found in {config_path}")
            config_path = found
    else:
        found = find_config_file()
        if found is None:
            raise FileNotFoundError(
                "No plc.yaml found in current or parent directories. " "Run 'plc init' to create one."
            )
        config_path = found

    data = load_yaml(config_path)

    sim_data = data.get("sim")
    if sim_data is None:
        raise KeyError(
            f"No 'sim:' section found in {config_path}. "
            "Add a sim: section with endpoint and interface settings."
        )

    config = SimConfig.from_dict(sim_data, config_path=config_path)

    # Read project metadata from top-level project: section
    project_data = data.get("project", {})
    if project_data:
        config.project_name = project_data.get("name")
        config.project_code = project_data.get("code")

    return config
