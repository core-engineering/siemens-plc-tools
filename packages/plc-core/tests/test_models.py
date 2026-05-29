"""Tests for plc_core.models module."""

from plc_core.models import DataType, IOCategory, PLCAddress


class TestPLCAddress:
    """Tests for PLCAddress class."""

    def test_from_s7_format_bit_address(self) -> None:
        """Test parsing S7 bit address format."""
        addr = PLCAddress.from_s7_format("%I1.0")
        assert addr is not None
        assert addr.address_type == "I"
        assert addr.byte_address == 1
        assert addr.bit_address == 0

    def test_from_s7_format_word_address(self) -> None:
        """Test parsing S7 word address format."""
        addr = PLCAddress.from_s7_format("%IW70")
        assert addr is not None
        assert addr.address_type == "IW"
        assert addr.byte_address == 70
        assert addr.bit_address is None

    def test_from_s7_format_output(self) -> None:
        """Test parsing S7 output address."""
        addr = PLCAddress.from_s7_format("%Q0.2")
        assert addr is not None
        assert addr.address_type == "Q"
        assert addr.byte_address == 0
        assert addr.bit_address == 2

    def test_from_s7_format_memory_word(self) -> None:
        """Test parsing S7 memory word address."""
        addr = PLCAddress.from_s7_format("%MW100")
        assert addr is not None
        assert addr.address_type == "MW"
        assert addr.byte_address == 100

    def test_from_s7_format_invalid(self) -> None:
        """Test parsing invalid S7 address."""
        assert PLCAddress.from_s7_format("") is None
        assert PLCAddress.from_s7_format("invalid") is None
        assert PLCAddress.from_s7_format("%X1.0") is None

    def test_from_iol_format_bit_address(self) -> None:
        """Test parsing IOL bit address format."""
        addr = PLCAddress.from_iol_format("E 1.0")
        assert addr is not None
        assert addr.address_type == "I"
        assert addr.byte_address == 1
        assert addr.bit_address == 0

    def test_from_iol_format_word_address(self) -> None:
        """Test parsing IOL word address format."""
        addr = PLCAddress.from_iol_format("PEW 70")
        assert addr is not None
        assert addr.address_type == "IW"
        assert addr.byte_address == 70

    def test_from_iol_format_output(self) -> None:
        """Test parsing IOL output address."""
        addr = PLCAddress.from_iol_format("A 0.2")
        assert addr is not None
        assert addr.address_type == "Q"
        assert addr.byte_address == 0
        assert addr.bit_address == 2

    def test_to_s7_format(self) -> None:
        """Test conversion to S7 format."""
        addr = PLCAddress(address_type="I", byte_address=1, bit_address=0)
        assert addr.to_s7_format() == "%I1.0"

        addr2 = PLCAddress(address_type="IW", byte_address=70)
        assert addr2.to_s7_format() == "%IW70"

    def test_to_iol_format(self) -> None:
        """Test conversion to IOL format."""
        addr = PLCAddress(address_type="I", byte_address=1, bit_address=0)
        assert addr.to_iol_format() == "E 1.0"

        addr2 = PLCAddress(address_type="IW", byte_address=70)
        assert addr2.to_iol_format() == "PEW 70"

    def test_roundtrip_s7_to_iol(self) -> None:
        """Test roundtrip conversion S7 -> IOL -> S7."""
        original = "%I1.0"
        addr = PLCAddress.from_s7_format(original)
        assert addr is not None
        iol = addr.to_iol_format()
        addr2 = PLCAddress.from_iol_format(iol)
        assert addr2 is not None
        assert addr2.to_s7_format() == original

    def test_str_representation(self) -> None:
        """Test string representation."""
        addr = PLCAddress(address_type="I", byte_address=1, bit_address=0)
        assert str(addr) == "%I1.0"


class TestIOCategory:
    """Tests for IOCategory enum."""

    def test_is_input(self) -> None:
        """Test is_input property."""
        assert IOCategory.DI.is_input is True
        assert IOCategory.AI.is_input is True
        assert IOCategory.DO.is_input is False
        assert IOCategory.AO.is_input is False

    def test_is_output(self) -> None:
        """Test is_output property."""
        assert IOCategory.DO.is_output is True
        assert IOCategory.AO.is_output is True
        assert IOCategory.DI.is_output is False

    def test_is_digital(self) -> None:
        """Test is_digital property."""
        assert IOCategory.DI.is_digital is True
        assert IOCategory.DO.is_digital is True
        assert IOCategory.AI.is_digital is False

    def test_is_analog(self) -> None:
        """Test is_analog property."""
        assert IOCategory.AI.is_analog is True
        assert IOCategory.AO.is_analog is True
        assert IOCategory.DI.is_analog is False

    def test_is_safety(self) -> None:
        """Test is_safety property."""
        assert IOCategory.SDI.is_safety is True
        assert IOCategory.SDO.is_safety is True
        assert IOCategory.DI.is_safety is False

    def test_from_mnemonic_prefix(self) -> None:
        """Test from_mnemonic_prefix method."""
        assert IOCategory.from_mnemonic_prefix("DI") == IOCategory.DI
        assert IOCategory.from_mnemonic_prefix("di") == IOCategory.DI
        assert IOCategory.from_mnemonic_prefix("INVALID") is None


class TestDataType:
    """Tests for DataType enum."""

    def test_from_string(self) -> None:
        """Test from_string method."""
        assert DataType.from_string("Bool") == DataType.BOOL
        assert DataType.from_string("BOOL") == DataType.BOOL
        assert DataType.from_string("bool") == DataType.BOOL
        assert DataType.from_string("Int") == DataType.INT
        assert DataType.from_string("integer") == DataType.INT
        assert DataType.from_string("Real") == DataType.REAL
        assert DataType.from_string("float") == DataType.REAL

    def test_from_string_unknown(self) -> None:
        """Test from_string with unknown type defaults to BOOL."""
        assert DataType.from_string("unknown") == DataType.BOOL
