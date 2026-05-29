"""Tests for core models."""

from plc_iol.core.models import (
    DataType,
    IOCategory,
    IODatabase,
    IOPoint,
    PLCAddress,
    generate_id,
)


class TestIOCategory:
    """Tests for IOCategory enum."""

    def test_is_input(self):
        assert IOCategory.DI.is_input is True
        assert IOCategory.AI.is_input is True
        assert IOCategory.SDI.is_input is True
        assert IOCategory.DO.is_input is False
        assert IOCategory.AO.is_input is False

    def test_is_output(self):
        assert IOCategory.DO.is_output is True
        assert IOCategory.AO.is_output is True
        assert IOCategory.SDO.is_output is True
        assert IOCategory.DI.is_output is False

    def test_is_digital(self):
        assert IOCategory.DI.is_digital is True
        assert IOCategory.DO.is_digital is True
        assert IOCategory.SDI.is_digital is True
        assert IOCategory.AI.is_digital is False
        assert IOCategory.AO.is_digital is False

    def test_is_analog(self):
        assert IOCategory.AI.is_analog is True
        assert IOCategory.AO.is_analog is True
        assert IOCategory.DI.is_analog is False

    def test_is_safety(self):
        assert IOCategory.SDI.is_safety is True
        assert IOCategory.SDO.is_safety is True
        assert IOCategory.DI.is_safety is False

    def test_from_mnemonic_prefix(self):
        assert IOCategory.from_mnemonic_prefix("DI") == IOCategory.DI
        assert IOCategory.from_mnemonic_prefix("do") == IOCategory.DO
        assert IOCategory.from_mnemonic_prefix("SDI") == IOCategory.SDI
        assert IOCategory.from_mnemonic_prefix("INVALID") is None


class TestDataType:
    """Tests for DataType enum."""

    def test_from_string(self):
        assert DataType.from_string("Bool") == DataType.BOOL
        assert DataType.from_string("boolean") == DataType.BOOL
        assert DataType.from_string("Int") == DataType.INT
        assert DataType.from_string("integer") == DataType.INT
        assert DataType.from_string("Real") == DataType.REAL
        assert DataType.from_string("float") == DataType.REAL
        assert DataType.from_string("unknown") == DataType.BOOL  # default


class TestPLCAddress:
    """Tests for PLCAddress class."""

    def test_from_s7_format_bit_address(self):
        addr = PLCAddress.from_s7_format("%I1.0")
        assert addr is not None
        assert addr.address_type == "I"
        assert addr.byte_address == 1
        assert addr.bit_address == 0

    def test_from_s7_format_output(self):
        addr = PLCAddress.from_s7_format("%Q2.5")
        assert addr is not None
        assert addr.address_type == "Q"
        assert addr.byte_address == 2
        assert addr.bit_address == 5

    def test_from_s7_format_word_address(self):
        addr = PLCAddress.from_s7_format("%IW100")
        assert addr is not None
        assert addr.address_type == "IW"
        assert addr.byte_address == 100
        assert addr.bit_address is None

    def test_from_s7_format_memory(self):
        addr = PLCAddress.from_s7_format("%M14.1")
        assert addr is not None
        assert addr.address_type == "M"
        assert addr.byte_address == 14
        assert addr.bit_address == 1

    def test_from_s7_format_invalid(self):
        assert PLCAddress.from_s7_format("") is None
        assert PLCAddress.from_s7_format("invalid") is None

    def test_from_iol_format_input(self):
        addr = PLCAddress.from_iol_format("E 1.0")
        assert addr is not None
        assert addr.address_type == "I"
        assert addr.byte_address == 1
        assert addr.bit_address == 0

    def test_from_iol_format_output(self):
        addr = PLCAddress.from_iol_format("A 2.5")
        assert addr is not None
        assert addr.address_type == "Q"
        assert addr.byte_address == 2
        assert addr.bit_address == 5

    def test_from_iol_format_word(self):
        addr = PLCAddress.from_iol_format("PEW 100")
        assert addr is not None
        assert addr.address_type == "IW"
        assert addr.byte_address == 100

    def test_to_s7_format(self):
        addr = PLCAddress(address_type="I", byte_address=1, bit_address=0)
        assert addr.to_s7_format() == "%I1.0"

        addr = PLCAddress(address_type="IW", byte_address=100)
        assert addr.to_s7_format() == "%IW100"

    def test_to_iol_format(self):
        addr = PLCAddress(address_type="I", byte_address=1, bit_address=0)
        assert addr.to_iol_format() == "E 1.0"

        addr = PLCAddress(address_type="IW", byte_address=100)
        assert addr.to_iol_format() == "PEW 100"


class TestIOPoint:
    """Tests for IOPoint class."""

    def test_create_point(self, sample_point):
        assert sample_point.mnemonic == "DI_STATION_PUMP_START"
        assert sample_point.signal_name == "PUMP START"
        assert sample_point.io_category == IOCategory.DI

    def test_generate_id(self):
        id1 = generate_id()
        id2 = generate_id()
        assert len(id1) == 8
        assert id1 != id2

    def test_infer_io_category(self):
        point = IOPoint(mnemonic="DI_TEST", signal_name="Test")
        assert point.io_category == IOCategory.DI

        point = IOPoint(mnemonic="SDO_TEST", signal_name="Test")
        assert point.io_category == IOCategory.SDO
        assert point.is_safety is True

    def test_to_dict(self, sample_point):
        data = sample_point.to_dict()
        assert data["mnemonic"] == "DI_STATION_PUMP_START"
        assert data["io_category"] == "DI"
        assert data["is_safety"] == "false"

    def test_from_dict(self):
        data = {
            "id": "test1234",
            "mnemonic": "DO_STATION_ALARM",
            "signal_name": "ALARM",
            "io_category": "DO",
            "is_safety": "false",
        }
        point = IOPoint.from_dict(data)
        assert point.mnemonic == "DO_STATION_ALARM"
        assert point.io_category == IOCategory.DO

    def test_plc_address_parsed(self, sample_point):
        addr = sample_point.plc_address_parsed
        assert addr is not None
        assert addr.address_type == "I"
        assert addr.byte_address == 1


class TestIODatabase:
    """Tests for IODatabase class."""

    def test_add_point(self, sample_database):
        assert len(sample_database) == 6

    def test_add_duplicate(self, sample_database, sample_point):
        # Should not add duplicate
        result = sample_database.add(sample_point, overwrite=False)
        assert result is False
        assert len(sample_database) == 6

    def test_add_with_overwrite(self, sample_database, sample_point):
        sample_point.signal_name = "MODIFIED"
        result = sample_database.add(sample_point, overwrite=True)
        assert result is True
        assert sample_database.get("DI_STATION_PUMP_START").signal_name == "MODIFIED"

    def test_get_point(self, sample_database):
        point = sample_database.get("DI_STATION_PUMP_START")
        assert point is not None
        assert point.signal_name == "PUMP START"

    def test_get_nonexistent(self, sample_database):
        assert sample_database.get("NONEXISTENT") is None

    def test_remove_point(self, sample_database):
        result = sample_database.remove("DI_STATION_PUMP_START")
        assert result is True
        assert len(sample_database) == 5
        assert "DI_STATION_PUMP_START" not in sample_database

    def test_update_point(self, sample_database):
        point = sample_database.update("DI_STATION_PUMP_START", signal_name="UPDATED")
        assert point is not None
        assert point.signal_name == "UPDATED"

    def test_filter_by_category(self, sample_database):
        di_points = sample_database.filter(io_category=IOCategory.DI)
        assert len(di_points) == 3  # DI_STATION_PUMP_START, DI_STATION_PUMP_STOP, DI_AXIS1_LIMIT_INNER

    def test_filter_by_group(self, sample_database):
        axis1_points = sample_database.filter(functional_group="AXIS1")
        assert len(axis1_points) == 2

    def test_filter_by_safety(self, sample_database):
        safety_points = sample_database.filter(is_safety=True)
        assert len(safety_points) == 1
        assert safety_points[0].mnemonic == "SDI_AXIS1_ESTOP"

    def test_contains(self, sample_database):
        assert "DI_STATION_PUMP_START" in sample_database
        assert "NONEXISTENT" not in sample_database

    def test_iter(self, sample_database):
        mnemonics = [p.mnemonic for p in sample_database]
        assert len(mnemonics) == 6

    def test_get_statistics(self, sample_database):
        stats = sample_database.get_statistics()
        assert stats["total"] == 6
        assert stats["by_category"]["DI"] == 3
        assert stats["by_category"]["DO"] == 1
        assert stats["safety_points"] == 1

    def test_merge(self, sample_database):
        other = IODatabase()
        other.add(IOPoint(mnemonic="NEW_POINT", signal_name="New"))
        other.add(IOPoint(mnemonic="DI_STATION_PUMP_START", signal_name="Conflict"))

        stats = sample_database.merge(other, overwrite=False)
        assert stats["added"] == 1
        assert stats["skipped"] == 1
        assert len(sample_database) == 7

    def test_merge_with_overwrite(self, sample_database):
        other = IODatabase()
        other.add(IOPoint(mnemonic="DI_STATION_PUMP_START", signal_name="Overwritten"))

        stats = sample_database.merge(other, overwrite=True)
        assert stats["overwritten"] == 1
        assert sample_database.get("DI_STATION_PUMP_START").signal_name == "Overwritten"
