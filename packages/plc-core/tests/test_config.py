"""Tests for plc_core.config module."""

from pathlib import Path

import pytest

from plc_core.config import BaseConfig, PathsConfig, find_config_file, load_yaml


class TestFindConfigFile:
    """Tests for find_config_file function."""

    def test_find_in_current_directory(self, tmp_path: Path) -> None:
        """Test finding config in current directory."""
        config_path = tmp_path / "plc.yaml"
        config_path.write_text("project:\n  name: Test\n")

        found = find_config_file(tmp_path)
        assert found == config_path

    def test_find_in_parent_directory(self, tmp_path: Path) -> None:
        """Test finding config in parent directory."""
        config_path = tmp_path / "plc.yaml"
        config_path.write_text("project:\n  name: Test\n")

        subdir = tmp_path / "subdir"
        subdir.mkdir()

        found = find_config_file(subdir)
        assert found == config_path

    def test_find_yml_extension(self, tmp_path: Path) -> None:
        """Test finding config with .yml extension."""
        config_path = tmp_path / "plc.yml"
        config_path.write_text("project:\n  name: Test\n")

        found = find_config_file(tmp_path)
        assert found == config_path

    def test_not_found(self, tmp_path: Path) -> None:
        """Test when config file is not found."""
        found = find_config_file(tmp_path)
        assert found is None

    def test_custom_filenames(self, tmp_path: Path) -> None:
        """Test with custom config filenames."""
        config_path = tmp_path / "custom.yaml"
        config_path.write_text("project:\n  name: Test\n")

        found = find_config_file(tmp_path, filenames=["custom.yaml"])
        assert found == config_path


class TestLoadYaml:
    """Tests for load_yaml function."""

    def test_load_valid_yaml(self, tmp_path: Path) -> None:
        """Test loading valid YAML file."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("project:\n  name: Test\n  code: TST\n")

        data = load_yaml(config_path)
        assert data["project"]["name"] == "Test"
        assert data["project"]["code"] == "TST"

    def test_load_empty_yaml(self, tmp_path: Path) -> None:
        """Test loading empty YAML file returns empty dict."""
        config_path = tmp_path / "empty.yaml"
        config_path.write_text("")

        data = load_yaml(config_path)
        assert data == {}

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Test FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            load_yaml(tmp_path / "missing.yaml")


class TestPathsConfig:
    """Tests for PathsConfig class."""

    def test_default_values(self) -> None:
        """Test default values."""
        config = PathsConfig()
        assert config.root == "."

    def test_resolve_path(self, tmp_path: Path) -> None:
        """Test path resolution."""
        config = PathsConfig(root="subdir")
        config_file = tmp_path / "plc.yaml"
        config_file.touch()

        resolved = config.resolve(config_file)
        assert resolved == tmp_path / "subdir"


class TestBaseConfig:
    """Tests for BaseConfig class."""

    def test_default_values(self) -> None:
        """Test default values."""
        config = BaseConfig()
        assert config.name == "PLC Project"
        assert config.code == ""
        assert config.version == "1.0.0"

    def test_from_dict(self) -> None:
        """Test creating config from dictionary."""
        data = {
            "project": {
                "name": "My Project",
                "code": "MYPRJ",
                "version": "2.0.0",
            },
            "paths": {
                "root": ".",
            },
            "custom_section": {
                "key": "value",
            },
        }

        config = BaseConfig.from_dict(data)
        assert config.name == "My Project"
        assert config.code == "MYPRJ"
        assert config.version == "2.0.0"

    def test_get_section(self) -> None:
        """Test getting custom section."""
        data = {
            "project": {"name": "Test"},
            "scl": {"enabled": True},
            "iol": {"paths": {"tags": "tags"}},
        }

        config = BaseConfig.from_dict(data)
        scl_section = config.get_section("scl")
        assert scl_section == {"enabled": True}

        missing = config.get_section("nonexistent")
        assert missing == {}

    def test_root_path_with_config_path(self, tmp_path: Path) -> None:
        """Test root_path property with config_path set."""
        config_file = tmp_path / "plc.yaml"
        config_file.touch()

        config = BaseConfig(config_path=config_file)
        assert config.root_path == tmp_path

    def test_root_path_without_config_path(self) -> None:
        """Test root_path property without config_path defaults to cwd."""
        config = BaseConfig()
        assert config.root_path == Path.cwd()
