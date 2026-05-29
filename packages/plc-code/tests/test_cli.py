"""Tests for the CLI module."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from plc_code import __version__
from plc_code.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    """Create a Click CLI runner."""
    return CliRunner()


class TestCLIVersion:
    """Tests for CLI version display."""

    def test_version_flag(self, runner: CliRunner) -> None:
        """Test --version flag displays correct version."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_version_in_package(self) -> None:
        """Test version is defined in package."""
        assert __version__
        # PEP 440 prefix check — keep tolerant to bumps.
        assert __version__[0].isdigit()


class TestCLIHelp:
    """Tests for CLI help display."""

    def test_help_flag(self, runner: CliRunner) -> None:
        """Test --help flag displays help."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "PLC code analysis" in result.output

    def test_commands_listed(self, runner: CliRunner) -> None:
        """Test all commands are listed in help."""
        result = runner.invoke(cli, ["--help"])
        assert "init" in result.output
        assert "status" in result.output
        assert "lint" in result.output
        assert "export" in result.output
        assert "docs" in result.output
        assert "test" in result.output


class TestCLIInit:
    """Tests for the init command."""

    def test_init_creates_config(self, runner: CliRunner) -> None:
        """Test init creates plc.yaml file."""
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0
            assert "Created" in result.output
            assert Path("plc.yaml").exists()

    def test_init_with_name(self, runner: CliRunner) -> None:
        """Test init with custom project name."""
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["init", "--name", "My Project"])
            assert result.exit_code == 0
            content = Path("plc.yaml").read_text()
            assert "My Project" in content

    def test_init_with_code(self, runner: CliRunner) -> None:
        """Test init with project code."""
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["init", "--code", "TST"])
            assert result.exit_code == 0
            content = Path("plc.yaml").read_text()
            assert "TST" in content

    def test_init_refuses_overwrite(self, runner: CliRunner) -> None:
        """Test init refuses to overwrite existing config."""
        with runner.isolated_filesystem():
            Path("plc.yaml").write_text("existing")
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 1
            assert "already exists" in result.output

    def test_init_force_overwrites(self, runner: CliRunner) -> None:
        """Test init --force overwrites existing config."""
        with runner.isolated_filesystem():
            Path("plc.yaml").write_text("existing")
            result = runner.invoke(cli, ["init", "--force"])
            assert result.exit_code == 0
            content = Path("plc.yaml").read_text()
            assert "project:" in content


class TestCLIStatus:
    """Tests for the status command."""

    def test_status_no_config(self, runner: CliRunner) -> None:
        """Test status fails without config file."""
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 1
            assert "No plc.yaml found" in result.output

    def test_status_with_config(self, runner: CliRunner) -> None:
        """Test status shows project information."""
        with runner.isolated_filesystem():
            Path("plc.yaml").write_text("""
project:
  name: "Test Project"
  code: "TST"
""")
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            assert "Test Project" in result.output
            assert "TST" in result.output


class TestCLILint:
    """Tests for the lint command."""

    def test_lint_no_config_no_path(self, runner: CliRunner) -> None:
        """Test lint fails without config and path."""
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["lint"])
            assert result.exit_code == 1
            assert "No plc.yaml found" in result.output

    def test_lint_nonexistent_path(self, runner: CliRunner) -> None:
        """Test lint fails with nonexistent path."""
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["lint", "nonexistent"])
            assert result.exit_code == 2
            assert "does not exist" in result.output

    def test_lint_help(self, runner: CliRunner) -> None:
        """Test lint --help displays options."""
        result = runner.invoke(cli, ["lint", "--help"])
        assert result.exit_code == 0
        assert "--format" in result.output
        assert "--verbose" in result.output


class TestCLIExport:
    """Tests for the export command group."""

    def test_export_help(self, runner: CliRunner) -> None:
        """Test export --help displays subcommands."""
        result = runner.invoke(cli, ["export", "--help"])
        assert result.exit_code == 0
        assert "pdf" in result.output

    def test_export_pdf_help(self, runner: CliRunner) -> None:
        """Test export pdf --help displays options."""
        result = runner.invoke(cli, ["export", "pdf", "--help"])
        assert result.exit_code == 0
        assert "--output" in result.output
        assert "--title" in result.output
        assert "--company" in result.output


class TestCLIDocs:
    """Tests for the docs command."""

    def test_docs_no_config_no_path(self, runner: CliRunner) -> None:
        """Test docs fails without config and path."""
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["docs"])
            assert result.exit_code == 1
            assert "No plc.yaml found" in result.output

    def test_docs_help(self, runner: CliRunner) -> None:
        """Test docs --help displays options."""
        result = runner.invoke(cli, ["docs", "--help"])
        assert result.exit_code == 0
        assert "--output" in result.output
        assert "--serve" in result.output


class TestCLITest:
    """Tests for the test command."""

    def test_test_help(self, runner: CliRunner) -> None:
        """Test test --help displays options."""
        result = runner.invoke(cli, ["test", "--help"])
        assert result.exit_code == 0
        assert "--verbose" in result.output
