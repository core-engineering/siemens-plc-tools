"""Configuration loader for IOL management.

Supports both standalone iol.yaml and unified plc.yaml with iol: section.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Config filenames in order of preference
CONFIG_FILENAMES = ["plc.yaml", "plc.yml", "iol.yaml", "iol.yml"]


class ConfigError(Exception):
    """Raised when configuration is invalid or missing."""

    pass


@dataclass
class FunctionalGroupConfig:
    """Configuration for a functional group."""

    id: str
    name: str | None = None
    xml_files: list[str] = field(default_factory=list)
    iol_sheets: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> FunctionalGroupConfig:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            name=data.get("name"),
            xml_files=data.get("xml_files", []),
            iol_sheets=data.get("iol_sheets", []),
        )


@dataclass
class PathsConfig:
    """Configuration for project paths (relative to project root)."""

    tags: str = "tags"
    iol: str = "specifications/iol"
    database: str = ".iol"

    @classmethod
    def from_dict(cls, data: dict) -> PathsConfig:
        """Create from dictionary."""
        return cls(
            tags=data.get("tags", cls.tags),
            iol=data.get("iol", cls.iol),
            database=data.get("database", cls.database),
        )


@dataclass
class NamingConfig:
    """Configuration for naming conventions."""

    pattern: str = "{io_category}_{location}_{signal}"
    locations: list[str] = field(default_factory=list)
    max_length: int = 64
    allowed_characters: str = "A-Z0-9_"

    @classmethod
    def from_dict(cls, data: dict) -> NamingConfig:
        """Create from dictionary."""
        return cls(
            pattern=data.get("pattern", cls.pattern),
            locations=data.get("locations", []),
            max_length=data.get("max_length", cls.max_length),
            allowed_characters=data.get("allowed_characters", cls.allowed_characters),
        )


@dataclass
class ProjectConfig:
    """Complete project configuration loaded from iol.yaml."""

    project_root: Path
    name: str
    code: str | None = None
    description: str | None = None
    functional_groups: list[FunctionalGroupConfig] = field(default_factory=list)
    paths: PathsConfig = field(default_factory=PathsConfig)
    naming: NamingConfig = field(default_factory=NamingConfig)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def tags_path(self) -> Path:
        """Get absolute path to tags directory."""
        return self.project_root / self.paths.tags

    @property
    def iol_path(self) -> Path:
        """Get absolute path to IOL directory."""
        return self.project_root / self.paths.iol

    @property
    def database_path(self) -> Path:
        """Get absolute path to database directory."""
        return self.project_root / self.paths.database

    def get_functional_group(self, group_id: str) -> FunctionalGroupConfig | None:
        """Get functional group by ID."""
        for group in self.functional_groups:
            if group.id == group_id:
                return group
        return None

    def get_xml_files(self) -> list[Path]:
        """Get all XML tag files from all functional groups."""
        files = []
        for group in self.functional_groups:
            for xml_file in group.xml_files:
                path = self.tags_path / xml_file
                if path.exists():
                    files.append(path)
        return files

    def get_iol_files(self) -> list[Path]:
        """Get all IOL Excel files from IOL directory."""
        if not self.iol_path.exists():
            return []
        return list(self.iol_path.glob("*.xlsx")) + list(self.iol_path.glob("*.xls"))

    @classmethod
    def from_dict(cls, data: dict, project_root: Path) -> ProjectConfig:
        """Create from dictionary."""
        project_data = data.get("project", {})
        return cls(
            project_root=project_root,
            name=project_data.get("name", project_root.name),
            code=project_data.get("code"),
            description=project_data.get("description"),
            functional_groups=[FunctionalGroupConfig.from_dict(g) for g in data.get("functional_groups", [])],
            paths=PathsConfig.from_dict(data.get("paths", {})),
            naming=NamingConfig.from_dict(data.get("naming", {})),
            extra={
                k: v for k, v in data.items() if k not in ("project", "functional_groups", "paths", "naming")
            },
        )


def find_config_file(start_path: Path | None = None) -> Path | None:
    """
    Find configuration file by walking up the directory tree.

    Searches for plc.yaml (unified) or iol.yaml (standalone) in order of preference.

    Args:
        start_path: Starting directory (defaults to current directory)

    Returns:
        Path to config file or None if not found
    """
    if start_path is None:
        start_path = Path.cwd()

    current = start_path.resolve()
    while current != current.parent:
        for filename in CONFIG_FILENAMES:
            config_path = current / filename
            if config_path.exists():
                return config_path
        current = current.parent

    return None


def load_config(path: Path | str | None = None) -> ProjectConfig:
    """
    Load project configuration from plc.yaml or iol.yaml.

    Supports both unified plc.yaml (with iol: section) and standalone iol.yaml.

    Args:
        path: Path to config file, or directory containing it.
              If None, searches up from current directory.

    Returns:
        ProjectConfig instance

    Raises:
        ConfigError: If configuration file not found or invalid
    """
    if path is None:
        config_path = find_config_file()
        if config_path is None:
            raise ConfigError(
                "No plc.yaml or iol.yaml found. Run 'plc iol init' to create one, "
                "or specify a path with --config."
            )
    else:
        path = Path(path)
        if path.is_dir():
            # Search for config in specified directory
            config_path = None
            for filename in CONFIG_FILENAMES:
                candidate = path / filename
                if candidate.exists():
                    config_path = candidate
                    break
            if config_path is None:
                raise ConfigError(f"No plc.yaml or iol.yaml found in {path}")
        else:
            config_path = path

    if not config_path.exists():
        raise ConfigError(f"Configuration file not found: {config_path}")

    try:
        with open(config_path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}") from e

    if data is None:
        data = {}

    # Check if this is a unified plc.yaml with iol: section
    if config_path.name in ("plc.yaml", "plc.yml") and "iol" in data:
        # Extract IOL-specific configuration from iol: section
        iol_data = data["iol"]
        # Merge project info from top level if not in iol section
        if "project" not in iol_data and "project" in data:
            iol_data["project"] = data["project"]
        data = iol_data

    return ProjectConfig.from_dict(data, config_path.parent)


def create_default_config(
    project_root: Path,
    name: str | None = None,
    code: str | None = None,
) -> Path:
    """
    Create a default iol.yaml configuration file.

    Args:
        project_root: Project root directory
        name: Project name (defaults to directory name)
        code: Project code

    Returns:
        Path to created configuration file
    """
    config_path = project_root / "iol.yaml"

    default_config: dict[str, Any] = {
        "project": {
            "name": name or project_root.name,
        },
        "functional_groups": [
            {
                "id": "COMMON",
                "name": "Common Equipment",
                "xml_files": [],
                "iol_sheets": ["COMMON"],
            },
        ],
        "paths": {
            "tags": "tags",
            "iol": "specifications/iol",
            "database": ".iol",
        },
        "naming": {
            "pattern": "{io_category}_{location}_{signal}",
            "locations": ["LOC1", "LOC2"],
            "max_length": 64,
        },
    }

    if code:
        default_config["project"]["code"] = code

    with open(config_path, "w") as f:
        yaml.dump(default_config, f, default_flow_style=False, sort_keys=False)

    return config_path
