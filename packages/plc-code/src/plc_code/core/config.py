"""Project configuration loading and management.

This module provides YAML-based configuration loading for PLC projects.

Supports both flat structure and unified plc.yaml with code: section.
Configuration is loaded from plc.yaml in the project directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_FILENAMES = ["plc.yaml", "plc.yml"]


@dataclass
class PathsConfig:
    """Path configuration for project directories.

    Attributes
    ----------
    source : str
        Path to SCL source files (.s7dcl)
    tags : str
        Path to XML tag exports
    docs : str
        Path for generated documentation
    tests : str
        Path to test files
    """

    source: str = "program-listings"
    tags: str = "tags"
    docs: str = "docs"
    tests: str = "test-cases"


@dataclass
class QualityConfig:
    """Quality analysis configuration.

    Attributes
    ----------
    enabled : bool
        Whether to run quality analysis
    fail_on_error : bool
        Whether to fail on quality errors
    safety_path_pattern : str
        Case-insensitive substring marking a directory as safety territory, used by
        the F003 safety-boundary heuristic to flag a block whose ``S7_Safety``
        declaration disagrees with where it lives. Matched against any directory in
        the block's path, not just the immediate one, so a source root or checkout
        directory whose own name contains the pattern makes every block in the
        project match. A project that organises its safety F-blocks under a
        different directory name should override this.
    """

    enabled: bool = True
    fail_on_error: bool = True
    safety_path_pattern: str = "safety"


@dataclass
class TestingConfig:
    """Testing configuration.

    Attributes
    ----------
    enabled : bool
        Whether to run tests
    test_dirs : list[str]
        Additional test directories to search
    """

    __test__ = False  # a result/config model, not a pytest test class

    enabled: bool = True
    test_dirs: list[str] = field(default_factory=lambda: ["test-cases"])


@dataclass
class ExternalDocsEntry:
    """One external markdown group declared in plc.yaml."""

    source: str
    dest: str
    title: str


@dataclass
class EfatYamlConfig:
    """EFAT integration-test index configuration declared in plc.yaml."""

    test_dir: str = ""
    output: str = "tests/integration.md"


@dataclass
class ProjectConfig:
    """Project configuration loaded from plc.yaml.

    Attributes
    ----------
    name : str
        Project name
    code : str
        Project code/identifier
    version : str
        Project version string
    paths : PathsConfig
        Path configuration
    quality : QualityConfig
        Quality analysis configuration
    testing : TestingConfig
        Testing configuration
    include_patterns : list[str]
        Glob patterns for files to include
    exclude_patterns : list[str]
        Glob patterns for files to exclude
    external_docs : list[ExternalDocsEntry]
        External markdown groups to copy into the docs tree
    efat : EfatYamlConfig
        EFAT integration-test index configuration
    config_path : Path | None
        Path to the config file (set after loading)
    """

    name: str = "PLC Project"
    code: str = ""
    version: str = ""
    paths: PathsConfig = field(default_factory=PathsConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    testing: TestingConfig = field(default_factory=TestingConfig)
    include_patterns: list[str] = field(default_factory=lambda: ["**/*.s7dcl"])
    exclude_patterns: list[str] = field(default_factory=list)
    external_docs: list[ExternalDocsEntry] = field(default_factory=list)
    efat: EfatYamlConfig = field(default_factory=EfatYamlConfig)
    config_path: Path | None = None

    @property
    def root_path(self) -> Path:
        """Get project root directory (parent of config file)."""
        if self.config_path:
            return self.config_path.parent
        return Path.cwd()

    @property
    def source_path(self) -> Path:
        """Get absolute path to source directory."""
        return self.root_path / self.paths.source

    @property
    def tags_path(self) -> Path:
        """Get absolute path to tags directory."""
        return self.root_path / self.paths.tags

    @property
    def docs_path(self) -> Path:
        """Get absolute path to docs directory."""
        return self.root_path / self.paths.docs

    @property
    def tests_path(self) -> Path:
        """Get absolute path to tests directory."""
        return self.root_path / self.paths.tests

    def get_source_files(self) -> list[Path]:
        """Get list of source files matching include/exclude patterns.

        Returns
        -------
        list[Path]
            List of matching source file paths
        """
        if not self.source_path.exists():
            return []

        files: list[Path] = []
        for pattern in self.include_patterns:
            files.extend(self.source_path.glob(pattern))

        # Apply exclude patterns
        if self.exclude_patterns:
            excluded: set[Path] = set()
            for pattern in self.exclude_patterns:
                excluded.update(self.source_path.glob(pattern))
            files = [f for f in files if f not in excluded]

        return sorted(files)

    def get_test_dirs(self) -> list[Path]:
        """Get list of test directories.

        Returns
        -------
        list[Path]
            List of test directory paths that exist
        """
        dirs = [self.tests_path]
        for test_dir in self.testing.test_dirs:
            path = self.root_path / test_dir
            if path not in dirs:
                dirs.append(path)
        return [d for d in dirs if d.exists()]

    @classmethod
    def from_dict(cls, data: dict[str, Any], config_path: Path | None = None) -> ProjectConfig:
        """Create config from dictionary.

        Parameters
        ----------
        data : dict[str, Any]
            Configuration dictionary
        config_path : Path | None
            Path to config file

        Returns
        -------
        ProjectConfig
            Loaded configuration
        """
        project_data = data.get("project", {})
        paths_data = data.get("paths", {})
        quality_data = data.get("quality", {})
        testing_data = data.get("testing", {})

        external_docs_raw = data.get("external_docs", []) or []
        external_docs: list[ExternalDocsEntry] = []
        if isinstance(external_docs_raw, list):
            for entry in external_docs_raw:
                if not isinstance(entry, dict) or not entry.get("source") or not entry.get("dest"):
                    continue
                external_docs.append(
                    ExternalDocsEntry(
                        source=str(entry["source"]),
                        dest=str(entry["dest"]),
                        title=str(entry.get("title", entry["dest"].title())),
                    )
                )

        efat_data = data.get("efat", {}) or {}
        efat_config = EfatYamlConfig(
            test_dir=str(efat_data.get("test_dir", "") or ""),
            output=str(efat_data.get("output", "tests/integration.md")),
        )

        return cls(
            name=project_data.get("name", "PLC Project"),
            code=project_data.get("code", ""),
            version=str(project_data.get("version", "")),
            paths=PathsConfig(
                source=paths_data.get("source", "program-listings"),
                tags=paths_data.get("tags", "tags"),
                docs=paths_data.get("docs", "docs"),
                tests=paths_data.get("tests", "test-cases"),
            ),
            quality=QualityConfig(
                enabled=quality_data.get("enabled", True),
                fail_on_error=quality_data.get("fail_on_error", True),
                safety_path_pattern=quality_data.get("safety_path_pattern", "safety"),
            ),
            testing=TestingConfig(
                enabled=testing_data.get("enabled", True),
                test_dirs=testing_data.get("test_dirs", ["test-cases"]),
            ),
            include_patterns=data.get("include_patterns", ["**/*.s7dcl"]),
            exclude_patterns=data.get("exclude_patterns", []),
            external_docs=external_docs,
            efat=efat_config,
            config_path=config_path,
        )


def find_config_file(start_path: Path | None = None) -> Path | None:
    """Find plc.yaml config file.

    Searches for config file in:
    1. start_path (if provided)
    2. Current directory
    3. Parent directories (up to root)

    Parameters
    ----------
    start_path : Path | None
        Starting directory for search

    Returns
    -------
    Path | None
        Path to config file, or None if not found
    """
    if start_path is None:
        start_path = Path.cwd()

    start_path = start_path.resolve()

    # If start_path is a file, use its parent
    if start_path.is_file():
        start_path = start_path.parent

    # Search current and parent directories
    current = start_path
    while True:
        for filename in CONFIG_FILENAMES:
            config_path = current / filename
            if config_path.exists():
                return config_path

        # Move to parent
        parent = current.parent
        if parent == current:
            # Reached root
            break
        current = parent

    return None


def load_config(path: Path | None = None) -> ProjectConfig:
    """Load project configuration from plc.yaml.

    Parameters
    ----------
    path : Path | None
        Explicit path to config file or directory.
        If None, searches current and parent directories.

    Returns
    -------
    ProjectConfig
        Loaded configuration

    Raises
    ------
    FileNotFoundError
        If no config file is found
    yaml.YAMLError
        If config file has invalid YAML
    """
    config_path: Path | None = None

    if path is not None:
        path = Path(path).resolve()
        if path.is_file():
            config_path = path
        elif path.is_dir():
            # Search for config in specified directory
            for filename in CONFIG_FILENAMES:
                candidate = path / filename
                if candidate.exists():
                    config_path = candidate
                    break
            if config_path is None:
                raise FileNotFoundError(f"No plc.yaml found in {path}. " f"Run 'plc init' to create one.")
        else:
            raise FileNotFoundError(f"Path does not exist: {path}")
    else:
        config_path = find_config_file()
        if config_path is None:
            raise FileNotFoundError(
                "No plc.yaml found in current or parent directories. " "Run 'plc init' to create one."
            )

    # Load YAML
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # Check if this is a unified plc.yaml with code: section
    if "code" in data and isinstance(data["code"], dict):
        # Extract code-specific configuration from code: section
        code_data = data["code"]
        # Merge project info from top level if not in code section
        if "project" not in code_data and "project" in data:
            code_data["project"] = data["project"]
        data = code_data

    return ProjectConfig.from_dict(data, config_path)


def generate_default_config(
    name: str = "PLC Project",
    code: str = "",
) -> str:
    """Generate default plc.yaml content.

    Parameters
    ----------
    name : str
        Project name
    code : str
        Project code

    Returns
    -------
    str
        YAML content for plc.yaml
    """
    return f"""# PLC Project Configuration
# This file configures the plc tool for this project.

project:
  name: "{name}"
  code: "{code}"

paths:
  source: program-listings          # SCL source files (.s7dcl)
  tags: tags                        # XML tag exports
  docs: docs                        # Generated documentation
  tests: test-cases                 # Test files

quality:
  enabled: true                     # Run quality analysis
  fail_on_error: true              # Fail on quality errors
  # safety_path_pattern: safety     # Matches any directory in a block's path (F003);
                                     # a root dir containing this substring matches everything

testing:
  enabled: true                     # Run tests
  test_dirs:
    - test-cases

# File patterns
include_patterns:
  - "**/*.s7dcl"

exclude_patterns: []
  # - "**/backup/**"
"""
