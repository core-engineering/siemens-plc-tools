"""Supervision pipeline configuration.

Loads the ``sup:`` section from plc.yaml to configure OPC UA,
Redis, TimescaleDB, and API backend connection parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plc_core.config import find_config_file, load_yaml
from plc_core.opcua.config import OpcUaConfig


@dataclass
class RedisConfig:
    """Redis connection settings."""

    url: str = "redis://localhost:6379"
    stream_prefix: str = "opcua:"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RedisConfig:
        return cls(
            url=data.get("url", "redis://localhost:6379"),
            stream_prefix=data.get("stream_prefix", "opcua:"),
        )


@dataclass
class DatabaseConfig:
    """TimescaleDB connection settings."""

    url: str = "postgresql://localhost:5432/supervision"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatabaseConfig:
        return cls(url=data.get("url", "postgresql://localhost:5432/supervision"))


@dataclass
class ApiConfig:
    """API backend connection settings."""

    base_url: str = "http://localhost:8000"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApiConfig:
        return cls(base_url=data.get("base_url", "http://localhost:8000"))


@dataclass
class SupTestConfig:
    """Integration test configuration."""

    test_dir: str = "supervision-tests"
    cache_dir: str = ".sup"
    cache_ttl_hours: int = 24
    scenario_timeout_s: float = 60.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SupTestConfig:
        return cls(
            test_dir=data.get("test_dir", "supervision-tests"),
            cache_dir=data.get("cache_dir", ".sup"),
            cache_ttl_hours=data.get("cache_ttl_hours", 24),
            scenario_timeout_s=data.get("scenario_timeout_s", 60.0),
        )


@dataclass
class InfraConfig:
    """Infrastructure SSH settings for crash testing."""

    ssh_host: str = "localhost"
    ssh_user: str = "maintenance"
    expected_containers: int = 0
    ssh_auth_sock: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InfraConfig:
        return cls(
            ssh_host=data.get("ssh_host", "localhost"),
            ssh_user=data.get("ssh_user", "maintenance"),
            expected_containers=data.get("expected_containers", 0),
            ssh_auth_sock=data.get("ssh_auth_sock"),
        )


@dataclass
class SupConfig:
    """Supervision pipeline configuration.

    Attributes
    ----------
    opcua : OpcUaConfig
        OPC UA connection settings (for writing test values).
    redis : RedisConfig
        Redis connection settings (for verifying streams).
    database : DatabaseConfig
        TimescaleDB connection settings (for verifying persistence).
    api : ApiConfig
        API backend settings (for verifying REST endpoints).
    testing : SupTestConfig
        Test runner settings.
    """

    opcua: OpcUaConfig = field(default_factory=OpcUaConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    testing: SupTestConfig = field(default_factory=SupTestConfig)
    infra: InfraConfig = field(default_factory=InfraConfig)
    config_path: Path | None = None
    project_name: str | None = None
    project_code: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], config_path: Path | None = None) -> SupConfig:
        return cls(
            opcua=OpcUaConfig.from_dict(data),
            redis=RedisConfig.from_dict(data.get("redis", {})),
            database=DatabaseConfig.from_dict(data.get("database", {})),
            api=ApiConfig.from_dict(data.get("api", {})),
            testing=SupTestConfig.from_dict(data.get("testing", {})),
            infra=InfraConfig.from_dict(data.get("infra", {})),
            config_path=config_path,
        )


def load_sup_config(path: Path | None = None) -> SupConfig:
    """Load supervision configuration from plc.yaml."""
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
            raise FileNotFoundError("No plc.yaml found in current or parent directories.")
        config_path = found

    data = load_yaml(config_path)

    sup_data = data.get("sup")
    if sup_data is None:
        raise KeyError(
            f"No 'sup:' section found in {config_path}. "
            "Add a sup: section with endpoint and verification settings."
        )

    config = SupConfig.from_dict(sup_data, config_path=config_path)

    project_data = data.get("project", {})
    if project_data:
        config.project_name = project_data.get("name")
        config.project_code = project_data.get("code")

    return config
