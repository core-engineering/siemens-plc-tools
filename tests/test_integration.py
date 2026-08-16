"""Integration tests for PLC Tools monorepo.

These tests verify that all packages work together correctly
and the plugin system functions as expected.
"""


class TestPackageImports:
    """Test that all packages can be imported."""

    def test_plc_tools_import(self) -> None:
        """Test plc_tools main package import."""
        import plc_tools

        assert plc_tools.__version__ == "0.3.0"

    def test_plc_core_import(self) -> None:
        """Test plc_core package import."""
        from plc_core import __version__

        assert __version__ == "0.3.0"

    def test_plc_code_import(self) -> None:
        """Test plc_code package import."""
        from plc_code import __version__
        from plc_code.cli import code_group

        assert __version__ == "0.3.0"
        assert code_group.name == "code"

    def test_plc_iol_import(self) -> None:
        """Test plc_iol package import."""
        from plc_iol import __version__
        from plc_iol.cli import iol_group

        assert __version__ == "0.3.0"
        assert iol_group.name == "iol"


class TestPluginDiscovery:
    """Test CLI plugin discovery mechanism."""

    def test_discover_plugins(self) -> None:
        """Test that plugins are discovered correctly."""
        from plc_tools.cli import discover_plugins

        plugins = discover_plugins()
        assert "code" in plugins
        assert "iol" in plugins

    def test_plugins_are_click_groups(self) -> None:
        """Test that discovered plugins are Click groups."""
        import click

        from plc_tools.cli import discover_plugins

        plugins = discover_plugins()
        for group in plugins.values():
            assert isinstance(group, click.Group)


class TestSharedModels:
    """Test that shared models work across packages."""

    def test_plc_address_roundtrip(self) -> None:
        """Test PLCAddress works consistently."""
        from plc_core.models import PLCAddress

        # Create address from S7 format
        addr = PLCAddress.from_s7_format("%I1.0")
        assert addr is not None

        # Convert to IOL and back
        iol = addr.to_iol_format()
        addr2 = PLCAddress.from_iol_format(iol)
        assert addr2 is not None
        assert addr2.to_s7_format() == "%I1.0"

    def test_io_category_shared(self) -> None:
        """Test IOCategory is consistent across packages."""
        from plc_core.models import IOCategory as CoreIOCategory
        from plc_iol import IOCategory as IOLIOCategory

        # Both should be the same class
        assert CoreIOCategory is IOLIOCategory
        assert CoreIOCategory.DI == IOLIOCategory.DI

    def test_data_type_shared(self) -> None:
        """Test DataType is consistent across packages."""
        from plc_core.models import DataType as CoreDataType
        from plc_iol import DataType as IOLDataType

        # Both should be the same class
        assert CoreDataType is IOLDataType
        assert CoreDataType.BOOL == IOLDataType.BOOL


class TestCLI:
    """Test CLI commands work correctly."""

    def test_main_cli_loads(self) -> None:
        """Test main CLI can be invoked."""
        from click.testing import CliRunner

        from plc_tools.cli import _load_plugins, cli

        _load_plugins()
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "PLC Tools" in result.output

    def test_code_subcommand_loads(self) -> None:
        """Test code subcommand is available."""
        from click.testing import CliRunner

        from plc_tools.cli import _load_plugins, cli

        _load_plugins()
        runner = CliRunner()
        result = runner.invoke(cli, ["code", "--help"])
        assert result.exit_code == 0
        assert "PLC code analysis" in result.output

    def test_iol_subcommand_loads(self) -> None:
        """Test iol subcommand is available."""
        from click.testing import CliRunner

        from plc_tools.cli import _load_plugins, cli

        _load_plugins()
        runner = CliRunner()
        result = runner.invoke(cli, ["iol", "--help"])
        assert result.exit_code == 0
        assert "IOL management" in result.output
