"""Base configuration classes for PLC tools.

This module provides base dataclasses for configuration that can be
extended by specific packages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PathsConfig:
    """Base path configuration for project directories.

    Attributes
    ----------
    root : str
        Project root directory (relative path from config file).
    """

    root: str = "."

    def resolve(self, config_path: Path) -> Path:
        """Resolve root path relative to config file location.

        Parameters
        ----------
        config_path : Path
            Path to the configuration file.

        Returns
        -------
        Path
            Resolved absolute path to root directory.
        """
        config_dir = config_path.parent if config_path.is_file() else config_path
        return (config_dir / self.root).resolve()


@dataclass
class BaseConfig:
    """Base configuration loaded from plc.yaml.

    Attributes
    ----------
    name : str
        Project name.
    code : str
        Project code/identifier.
    version : str
        Project version.
    paths : PathsConfig
        Path configuration.
    config_path : Path | None
        Path to the config file (set after loading).
    raw_data : dict[str, Any]
        Raw configuration data from YAML.
    """

    name: str = "PLC Project"
    code: str = ""
    version: str = "1.0.0"
    paths: PathsConfig = field(default_factory=PathsConfig)
    config_path: Path | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)

    @property
    def root_path(self) -> Path:
        """Get project root directory.

        Returns
        -------
        Path
            Absolute path to project root.
        """
        if self.config_path:
            return self.paths.resolve(self.config_path)
        return Path.cwd()

    def get_section(self, section_name: str) -> dict[str, Any]:
        """Get a configuration section by name.

        Parameters
        ----------
        section_name : str
            Name of the section to retrieve.

        Returns
        -------
        dict[str, Any]
            Section data, or empty dict if not found.
        """
        section = self.raw_data.get(section_name, {})
        return section if isinstance(section, dict) else {}

    @classmethod
    def from_dict(cls, data: dict[str, Any], config_path: Path | None = None) -> BaseConfig:
        """Create config from dictionary.

        Parameters
        ----------
        data : dict[str, Any]
            Configuration dictionary.
        config_path : Path | None
            Path to config file.

        Returns
        -------
        BaseConfig
            Loaded configuration.
        """
        project_data = data.get("project", {})
        paths_data = data.get("paths", {})

        return cls(
            name=project_data.get("name", "PLC Project"),
            code=project_data.get("code", ""),
            version=project_data.get("version", "1.0.0"),
            paths=PathsConfig(
                root=paths_data.get("root", "."),
            ),
            config_path=config_path,
            raw_data=data,
        )
