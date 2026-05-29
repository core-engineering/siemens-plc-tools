"""Tests for naming conventions module."""

from plc_iol.core.models import IOCategory
from plc_iol.core.naming import (
    MnemonicParts,
    NamingConvention,
    extract_io_category,
    validate_mnemonic,
)


class TestMnemonicParts:
    """Tests for MnemonicParts class."""

    def test_io_category_enum(self):
        parts = MnemonicParts(io_category="DI", full="DI_STATION_TEST")
        assert parts.io_category_enum == IOCategory.DI

    def test_io_category_enum_none(self):
        parts = MnemonicParts(full="TEST")
        assert parts.io_category_enum is None


class TestNamingConvention:
    """Tests for NamingConvention class."""

    def test_parse_standard_mnemonic(self):
        convention = NamingConvention(locations=["STATION", "DRIVE", "AXIS1"])
        parts = convention.parse("DI_STATION_PUMP_START")

        assert parts.io_category == "DI"
        assert parts.location == "STATION"
        assert parts.signal == "PUMP_START"

    def test_parse_with_safety(self):
        convention = NamingConvention(locations=["AXIS1"])
        parts = convention.parse("SDI_AXIS1_ESTOP")

        assert parts.io_category == "SDI"
        assert parts.location == "AXIS1"
        assert parts.signal == "ESTOP"

    def test_parse_no_locations(self):
        convention = NamingConvention()
        parts = convention.parse("DO_STATION_LIGHT")

        assert parts.io_category == "DO"
        assert parts.location == "STATION"
        assert parts.signal == "LIGHT"

    def test_validate_valid_mnemonic(self):
        convention = NamingConvention(locations=["STATION"])
        result = convention.validate("DI_STATION_PUMP_START")

        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_validate_invalid_category(self):
        convention = NamingConvention()
        result = convention.validate("XX_STATION_TEST")

        assert result.is_valid is False
        assert any("I/O category" in e for e in result.errors)

    def test_validate_invalid_characters(self):
        convention = NamingConvention()
        result = convention.validate("DI_STATION_TEST@123")

        assert result.is_valid is False
        assert any("invalid characters" in e for e in result.errors)

    def test_validate_too_long(self):
        convention = NamingConvention(max_length=20)
        result = convention.validate("DI_STATION_THIS_IS_A_VERY_LONG_MNEMONIC")

        assert result.is_valid is False
        assert any("maximum length" in e for e in result.errors)

    def test_validate_consecutive_underscores_warning(self):
        convention = NamingConvention()
        result = convention.validate("DI_STATION__TEST")

        assert result.is_valid is True
        assert any("consecutive underscores" in w for w in result.warnings)

    def test_validate_empty_mnemonic(self):
        convention = NamingConvention()
        result = convention.validate("")

        assert result.is_valid is False
        assert any("empty" in e for e in result.errors)

    def test_suggest_mnemonic(self):
        convention = NamingConvention()
        mnemonic = convention.suggest_mnemonic(
            io_category="DI",
            location="STATION",
            signal="Pump Start",
        )
        assert mnemonic == "DI_STATION_PUMP_START"

    def test_suggest_mnemonic_with_enum(self):
        convention = NamingConvention()
        mnemonic = convention.suggest_mnemonic(
            io_category=IOCategory.SDI,
            location="AXIS1",
            signal="Emergency Stop",
        )
        assert mnemonic == "SDI_AXIS1_EMERGENCY_STOP"

    def test_suggest_mnemonic_truncate(self):
        convention = NamingConvention(max_length=20)
        mnemonic = convention.suggest_mnemonic(
            io_category="DI",
            location="STATION",
            signal="This is a very long signal name",
        )
        assert len(mnemonic) == 20

    def test_normalize(self):
        convention = NamingConvention()
        assert convention.normalize("di_station_test") == "DI_STATION_TEST"
        assert convention.normalize("  DI_STATION_TEST  ") == "DI_STATION_TEST"
        assert convention.normalize("DI STATION TEST") == "DI_STATION_TEST"


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_validate_mnemonic(self):
        result = validate_mnemonic("DI_STATION_TEST")
        assert result.is_valid is True

    def test_validate_mnemonic_with_locations(self):
        result = validate_mnemonic("DI_STATION_TEST", locations=["STATION"])
        assert result.is_valid is True
        assert len(result.warnings) == 0

    def test_extract_io_category(self):
        assert extract_io_category("DI_STATION_TEST") == IOCategory.DI
        assert extract_io_category("SDO_AXIS1_VALVE") == IOCategory.SDO
        assert extract_io_category("INVALID") is None
        assert extract_io_category("") is None
