"""Tests for the core configuration module."""

from pathlib import Path

import pytest

from plc_code.core.config import (
    CONFIG_FILENAMES,
    PathsConfig,
    ProjectConfig,
    QualityConfig,
    TestingConfig,
    find_config_file,
    generate_default_config,
    load_config,
)


class TestPathsConfig:
    """Tests for PathsConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default path values."""
        config = PathsConfig()
        assert config.source == "program-listings"
        assert config.tags == "tags"
        assert config.docs == "docs"
        assert config.tests == "test-cases"

    def test_custom_values(self) -> None:
        """Test custom path values."""
        config = PathsConfig(
            source="src",
            tags="xml-tags",
            docs="output",
            tests="tests",
        )
        assert config.source == "src"
        assert config.tags == "xml-tags"
        assert config.docs == "output"
        assert config.tests == "tests"


class TestQualityConfig:
    """Tests for QualityConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default quality settings."""
        config = QualityConfig()
        assert config.enabled is True
        assert config.fail_on_error is True

    def test_disabled(self) -> None:
        """Test disabled quality analysis."""
        config = QualityConfig(enabled=False, fail_on_error=False)
        assert config.enabled is False
        assert config.fail_on_error is False


class TestTestingConfig:
    """Tests for TestingConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default testing settings."""
        config = TestingConfig()
        assert config.enabled is True
        assert config.test_dirs == ["test-cases"]

    def test_custom_test_dirs(self) -> None:
        """Test custom test directories."""
        config = TestingConfig(test_dirs=["tests", "integration-tests"])
        assert config.test_dirs == ["tests", "integration-tests"]


class TestProjectConfig:
    """Tests for ProjectConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default project configuration."""
        config = ProjectConfig()
        assert config.name == "PLC Project"
        assert config.code == ""
        assert isinstance(config.paths, PathsConfig)
        assert isinstance(config.quality, QualityConfig)
        assert isinstance(config.testing, TestingConfig)
        assert config.include_patterns == ["**/*.s7dcl"]
        assert config.exclude_patterns == []
        assert config.config_path is None

    def test_root_path_no_config(self) -> None:
        """Test root_path returns cwd when no config_path."""
        config = ProjectConfig()
        assert config.root_path == Path.cwd()

    def test_root_path_with_config(self, tmp_path: Path) -> None:
        """Test root_path returns parent of config_path."""
        config_path = tmp_path / "subdir" / "plc.yaml"
        config = ProjectConfig(config_path=config_path)
        assert config.root_path == tmp_path / "subdir"

    def test_source_path(self, tmp_path: Path) -> None:
        """Test source_path is relative to root."""
        config_path = tmp_path / "plc.yaml"
        config = ProjectConfig(config_path=config_path)
        assert config.source_path == tmp_path / "program-listings"

    def test_tags_path(self, tmp_path: Path) -> None:
        """Test tags_path is relative to root."""
        config_path = tmp_path / "plc.yaml"
        config = ProjectConfig(config_path=config_path)
        assert config.tags_path == tmp_path / "tags"

    def test_docs_path(self, tmp_path: Path) -> None:
        """Test docs_path is relative to root."""
        config_path = tmp_path / "plc.yaml"
        config = ProjectConfig(config_path=config_path)
        assert config.docs_path == tmp_path / "docs"

    def test_tests_path(self, tmp_path: Path) -> None:
        """Test tests_path is relative to root."""
        config_path = tmp_path / "plc.yaml"
        config = ProjectConfig(config_path=config_path)
        assert config.tests_path == tmp_path / "test-cases"


class TestProjectConfigGetSourceFiles:
    """Tests for ProjectConfig.get_source_files method."""

    def test_empty_when_source_not_exists(self, tmp_path: Path) -> None:
        """Test returns empty list when source directory doesn't exist."""
        config_path = tmp_path / "plc.yaml"
        config = ProjectConfig(config_path=config_path)
        assert config.get_source_files() == []

    def test_finds_s7dcl_files(self, tmp_path: Path) -> None:
        """Test finds .s7dcl files in source directory."""
        source_dir = tmp_path / "program-listings"
        source_dir.mkdir()
        (source_dir / "block1.s7dcl").write_text("test")
        (source_dir / "block2.s7dcl").write_text("test")
        (source_dir / "other.txt").write_text("test")

        config_path = tmp_path / "plc.yaml"
        config = ProjectConfig(config_path=config_path)
        files = config.get_source_files()

        assert len(files) == 2
        assert all(f.suffix == ".s7dcl" for f in files)

    def test_finds_nested_s7dcl_files(self, tmp_path: Path) -> None:
        """Test finds nested .s7dcl files."""
        source_dir = tmp_path / "program-listings"
        subdir = source_dir / "subdir"
        subdir.mkdir(parents=True)
        (source_dir / "block1.s7dcl").write_text("test")
        (subdir / "block2.s7dcl").write_text("test")

        config_path = tmp_path / "plc.yaml"
        config = ProjectConfig(config_path=config_path)
        files = config.get_source_files()

        assert len(files) == 2

    def test_exclude_patterns(self, tmp_path: Path) -> None:
        """Test exclude patterns filter out files."""
        source_dir = tmp_path / "program-listings"
        backup_dir = source_dir / "backup"
        backup_dir.mkdir(parents=True)
        (source_dir / "block1.s7dcl").write_text("test")
        (backup_dir / "block2.s7dcl").write_text("test")

        config_path = tmp_path / "plc.yaml"
        config = ProjectConfig(
            config_path=config_path,
            exclude_patterns=["backup/*.s7dcl"],
        )
        files = config.get_source_files()

        assert len(files) == 1
        assert files[0].name == "block1.s7dcl"


class TestProjectConfigGetTestDirs:
    """Tests for ProjectConfig.get_test_dirs method."""

    def test_returns_existing_dirs_only(self, tmp_path: Path) -> None:
        """Test only returns directories that exist."""
        test_dir = tmp_path / "test-cases"
        test_dir.mkdir()

        config_path = tmp_path / "plc.yaml"
        config = ProjectConfig(config_path=config_path)
        dirs = config.get_test_dirs()

        assert len(dirs) == 1
        assert dirs[0] == test_dir

    def test_includes_additional_test_dirs(self, tmp_path: Path) -> None:
        """Test includes additional test directories from config."""
        test_dir1 = tmp_path / "test-cases"
        test_dir2 = tmp_path / "integration-tests"
        test_dir1.mkdir()
        test_dir2.mkdir()

        config_path = tmp_path / "plc.yaml"
        config = ProjectConfig(
            config_path=config_path,
            testing=TestingConfig(test_dirs=["test-cases", "integration-tests"]),
        )
        dirs = config.get_test_dirs()

        assert len(dirs) == 2


class TestProjectConfigFromDict:
    """Tests for ProjectConfig.from_dict class method."""

    def test_empty_dict(self) -> None:
        """Test creating config from empty dict uses defaults."""
        config = ProjectConfig.from_dict({})
        assert config.name == "PLC Project"
        assert config.code == ""

    def test_project_section(self) -> None:
        """Test parsing project section."""
        data = {
            "project": {
                "name": "My Project",
                "code": "PRJ",
            }
        }
        config = ProjectConfig.from_dict(data)
        assert config.name == "My Project"
        assert config.code == "PRJ"

    def test_paths_section(self) -> None:
        """Test parsing paths section."""
        data = {
            "paths": {
                "source": "src",
                "tags": "xml",
                "docs": "documentation",
                "tests": "tests",
            }
        }
        config = ProjectConfig.from_dict(data)
        assert config.paths.source == "src"
        assert config.paths.tags == "xml"
        assert config.paths.docs == "documentation"
        assert config.paths.tests == "tests"

    def test_quality_section(self) -> None:
        """Test parsing quality section."""
        data = {
            "quality": {
                "enabled": False,
                "fail_on_error": False,
            }
        }
        config = ProjectConfig.from_dict(data)
        assert config.quality.enabled is False
        assert config.quality.fail_on_error is False

    def test_testing_section(self) -> None:
        """Test parsing testing section."""
        data = {
            "testing": {
                "enabled": False,
                "test_dirs": ["tests", "e2e"],
            }
        }
        config = ProjectConfig.from_dict(data)
        assert config.testing.enabled is False
        assert config.testing.test_dirs == ["tests", "e2e"]

    def test_patterns(self) -> None:
        """Test parsing include/exclude patterns."""
        data = {
            "include_patterns": ["**/*.scl"],
            "exclude_patterns": ["**/backup/**"],
        }
        config = ProjectConfig.from_dict(data)
        assert config.include_patterns == ["**/*.scl"]
        assert config.exclude_patterns == ["**/backup/**"]

    def test_config_path(self, tmp_path: Path) -> None:
        """Test config_path is set from parameter."""
        config_path = tmp_path / "plc.yaml"
        config = ProjectConfig.from_dict({}, config_path=config_path)
        assert config.config_path == config_path


class TestFindConfigFile:
    """Tests for find_config_file function."""

    def test_finds_plc_yaml(self, tmp_path: Path) -> None:
        """Test finds plc.yaml in current directory."""
        config_file = tmp_path / "plc.yaml"
        config_file.write_text("project:\n  name: Test")

        result = find_config_file(tmp_path)
        assert result == config_file

    def test_finds_plc_yml(self, tmp_path: Path) -> None:
        """Test finds plc.yml in current directory."""
        config_file = tmp_path / "plc.yml"
        config_file.write_text("project:\n  name: Test")

        result = find_config_file(tmp_path)
        assert result == config_file

    def test_prefers_yaml_over_yml(self, tmp_path: Path) -> None:
        """Test prefers plc.yaml over plc.yml."""
        yaml_file = tmp_path / "plc.yaml"
        yml_file = tmp_path / "plc.yml"
        yaml_file.write_text("project:\n  name: YAML")
        yml_file.write_text("project:\n  name: YML")

        result = find_config_file(tmp_path)
        assert result == yaml_file

    def test_searches_parent_directories(self, tmp_path: Path) -> None:
        """Test searches parent directories."""
        config_file = tmp_path / "plc.yaml"
        config_file.write_text("project:\n  name: Test")
        subdir = tmp_path / "sub" / "dir"
        subdir.mkdir(parents=True)

        result = find_config_file(subdir)
        assert result == config_file

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        """Test returns None when no config found."""
        result = find_config_file(tmp_path)
        assert result is None

    def test_handles_file_path(self, tmp_path: Path) -> None:
        """Test handles file path by using parent directory."""
        config_file = tmp_path / "plc.yaml"
        config_file.write_text("project:\n  name: Test")
        some_file = tmp_path / "some_file.txt"
        some_file.write_text("test")

        result = find_config_file(some_file)
        assert result == config_file


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_valid_config(self, tmp_path: Path) -> None:
        """Test loading valid config file."""
        config_file = tmp_path / "plc.yaml"
        config_file.write_text("""
project:
  name: "Test Project"
  code: "TST"
paths:
  source: "src"
""")

        config = load_config(config_file)
        assert config.name == "Test Project"
        assert config.code == "TST"
        assert config.paths.source == "src"
        assert config.config_path == config_file

    def test_load_from_directory(self, tmp_path: Path) -> None:
        """Test loading config from directory."""
        config_file = tmp_path / "plc.yaml"
        config_file.write_text("project:\n  name: Test")

        config = load_config(tmp_path)
        assert config.name == "Test"

    def test_load_empty_config(self, tmp_path: Path) -> None:
        """Test loading empty config uses defaults."""
        config_file = tmp_path / "plc.yaml"
        config_file.write_text("")

        config = load_config(config_file)
        assert config.name == "PLC Project"

    def test_load_not_found_raises(self, tmp_path: Path) -> None:
        """Test raises FileNotFoundError when config not found."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_config(tmp_path)
        assert "No plc.yaml found" in str(exc_info.value)

    def test_load_explicit_path_not_found_raises(self, tmp_path: Path) -> None:
        """Test raises FileNotFoundError for non-existent path."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_config(tmp_path / "nonexistent")
        assert "does not exist" in str(exc_info.value)

    def test_load_searches_parent_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test load_config searches parent directories when no path given."""
        config_file = tmp_path / "plc.yaml"
        config_file.write_text("project:\n  name: Parent Config")
        subdir = tmp_path / "sub"
        subdir.mkdir()

        monkeypatch.chdir(subdir)
        config = load_config()
        assert config.name == "Parent Config"


class TestGenerateDefaultConfig:
    """Tests for generate_default_config function."""

    def test_generates_valid_yaml(self) -> None:
        """Test generates valid YAML content."""
        import yaml

        content = generate_default_config()
        data = yaml.safe_load(content)

        assert "project" in data
        assert "paths" in data
        assert "quality" in data
        assert "testing" in data

    def test_includes_project_name(self) -> None:
        """Test includes project name."""
        content = generate_default_config(name="My Project")
        assert "My Project" in content

    def test_includes_project_code(self) -> None:
        """Test includes project code."""
        content = generate_default_config(code="PRJ")
        assert "PRJ" in content

    def test_default_paths(self) -> None:
        """Test default paths are included."""
        content = generate_default_config()
        assert "program-listings" in content
        assert "tags" in content
        assert "docs" in content
        assert "test-cases" in content

    def test_default_patterns(self) -> None:
        """Test default patterns are included."""
        content = generate_default_config()
        assert "**/*.s7dcl" in content


class TestConfigFilenames:
    """Tests for CONFIG_FILENAMES constant."""

    def test_contains_yaml_extensions(self) -> None:
        """Test contains both .yaml and .yml extensions."""
        assert "plc.yaml" in CONFIG_FILENAMES
        assert "plc.yml" in CONFIG_FILENAMES

    def test_yaml_first(self) -> None:
        """Test .yaml comes before .yml."""
        yaml_index = CONFIG_FILENAMES.index("plc.yaml")
        yml_index = CONFIG_FILENAMES.index("plc.yml")
        assert yaml_index < yml_index
