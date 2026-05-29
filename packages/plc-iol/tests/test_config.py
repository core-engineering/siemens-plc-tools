"""Tests for configuration module."""

import pytest

from plc_iol.core.config import (
    ConfigError,
    FunctionalGroupConfig,
    NamingConfig,
    PathsConfig,
    ProjectConfig,
    create_default_config,
    find_config_file,
    load_config,
)


class TestFunctionalGroupConfig:
    """Tests for FunctionalGroupConfig."""

    def test_from_dict(self):
        data = {
            "id": "AXIS1",
            "name": "Axis 1",
            "xml_files": ["Axis1.xml"],
            "iol_sheets": ["AXIS1"],
        }
        config = FunctionalGroupConfig.from_dict(data)
        assert config.id == "AXIS1"
        assert config.name == "Axis 1"
        assert config.xml_files == ["Axis1.xml"]

    def test_from_dict_minimal(self):
        data = {"id": "TEST"}
        config = FunctionalGroupConfig.from_dict(data)
        assert config.id == "TEST"
        assert config.xml_files == []


class TestPathsConfig:
    """Tests for PathsConfig."""

    def test_defaults(self):
        config = PathsConfig()
        assert config.tags == "tags"
        assert config.iol == "specifications/iol"
        assert config.database == ".iol"

    def test_from_dict(self):
        data = {
            "tags": "custom/tags",
            "iol": "custom/iol",
        }
        config = PathsConfig.from_dict(data)
        assert config.tags == "custom/tags"
        assert config.iol == "custom/iol"
        assert config.database == ".iol"  # default


class TestNamingConfig:
    """Tests for NamingConfig."""

    def test_defaults(self):
        config = NamingConfig()
        assert "{io_category}" in config.pattern
        assert config.max_length == 64

    def test_from_dict(self):
        data = {
            "locations": ["STATION", "DRIVE"],
            "max_length": 32,
        }
        config = NamingConfig.from_dict(data)
        assert config.locations == ["STATION", "DRIVE"]
        assert config.max_length == 32


class TestProjectConfig:
    """Tests for ProjectConfig."""

    def test_paths(self, sample_config):
        assert sample_config.tags_path == sample_config.project_root / "tags"
        assert sample_config.iol_path == sample_config.project_root / "iol"
        assert sample_config.database_path == sample_config.project_root / ".iol"

    def test_get_functional_group(self, sample_config):
        group = sample_config.get_functional_group("AXIS1")
        assert group is not None
        assert group.name == "Axis 1"

        assert sample_config.get_functional_group("NONEXISTENT") is None

    def test_from_dict(self, temp_dir):
        data = {
            "project": {
                "name": "Test",
                "code": "T001",
            },
            "functional_groups": [
                {"id": "COMMON", "xml_files": ["Common.xml"]},
            ],
            "paths": {
                "tags": "tags",
            },
        }
        config = ProjectConfig.from_dict(data, temp_dir)
        assert config.name == "Test"
        assert config.code == "T001"
        assert len(config.functional_groups) == 1


class TestConfigLoading:
    """Tests for configuration loading."""

    def test_find_config_file(self, temp_dir):
        # Create config file
        config_path = temp_dir / "iol.yaml"
        config_path.write_text("project:\n  name: Test\n")

        # Find from same directory
        found = find_config_file(temp_dir)
        assert found == config_path

        # Find from subdirectory
        subdir = temp_dir / "subdir"
        subdir.mkdir()
        found = find_config_file(subdir)
        assert found == config_path

    def test_find_config_file_not_found(self, temp_dir):
        found = find_config_file(temp_dir)
        assert found is None

    def test_load_config(self, temp_dir):
        config_path = temp_dir / "iol.yaml"
        config_path.write_text("""
project:
  name: Test Project
  code: TEST001
functional_groups:
  - id: COMMON
    xml_files: [Common.xml]
paths:
  tags: tags
  iol: iol
""")
        config = load_config(config_path)
        assert config.name == "Test Project"
        assert config.code == "TEST001"
        assert len(config.functional_groups) == 1

    def test_load_config_not_found(self, temp_dir):
        with pytest.raises(ConfigError):
            load_config(temp_dir / "nonexistent.yaml")

    def test_load_config_invalid_yaml(self, temp_dir):
        config_path = temp_dir / "iol.yaml"
        config_path.write_text("invalid: yaml: content: [")

        with pytest.raises(ConfigError):
            load_config(config_path)

    def test_create_default_config(self, temp_dir):
        config_path = create_default_config(temp_dir, name="New Project", code="NEW001")
        assert config_path.exists()

        # Load and verify
        config = load_config(config_path)
        assert config.name == "New Project"
        assert config.code == "NEW001"
