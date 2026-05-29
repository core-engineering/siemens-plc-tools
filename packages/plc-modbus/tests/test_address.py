"""Tests for register-address parsing and value decoding."""

from __future__ import annotations

import pytest

from plc_modbus.client import (
    RegisterAddress,
    decode_value,
    parse_register_address,
)


class TestParseRegisterAddress:
    """Parsing of ``"AREA:N"`` and ``"AREA:N/B"`` register specifiers."""

    def test_holding_whole_word(self) -> None:
        assert parse_register_address("HOLDING:0") == RegisterAddress(area="HOLDING", address=0, bit=None)

    def test_holding_high_address(self) -> None:
        assert parse_register_address("HOLDING:65535") == RegisterAddress(
            area="HOLDING", address=65535, bit=None
        )

    def test_input_register(self) -> None:
        assert parse_register_address("INPUT:42") == RegisterAddress(area="INPUT", address=42, bit=None)

    def test_coil(self) -> None:
        assert parse_register_address("COIL:7") == RegisterAddress(area="COIL", address=7, bit=None)

    def test_discrete_input(self) -> None:
        assert parse_register_address("DISCRETE:3") == RegisterAddress(area="DISCRETE", address=3, bit=None)

    def test_holding_bit(self) -> None:
        assert parse_register_address("HOLDING:5/3") == RegisterAddress(area="HOLDING", address=5, bit=3)

    def test_input_bit(self) -> None:
        assert parse_register_address("INPUT:0/15") == RegisterAddress(area="INPUT", address=0, bit=15)

    def test_whitespace_tolerated(self) -> None:
        assert parse_register_address("  HOLDING:42  ") == RegisterAddress(
            area="HOLDING", address=42, bit=None
        )

    def test_unknown_area(self) -> None:
        with pytest.raises(ValueError, match="Unknown Modbus area 'FOO'"):
            parse_register_address("FOO:0")

    def test_lowercase_area_rejected(self) -> None:
        # Area must be uppercase per the regex.
        with pytest.raises(ValueError, match="Invalid Modbus register address"):
            parse_register_address("holding:0")

    def test_malformed_no_colon(self) -> None:
        with pytest.raises(ValueError, match="Invalid Modbus register address"):
            parse_register_address("HOLDING42")

    def test_malformed_negative_bit(self) -> None:
        with pytest.raises(ValueError, match="Invalid Modbus register address"):
            parse_register_address("HOLDING:5/-1")

    def test_bit_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="Bit 16 out of range"):
            parse_register_address("HOLDING:5/16")

    def test_bit_on_coil_rejected(self) -> None:
        with pytest.raises(ValueError, match="Bit indexing 'AREA:N/B' only valid"):
            parse_register_address("COIL:5/3")


class TestRegisterAddressIsBit:
    """The ``is_bit`` derived property — handy for runner dispatch."""

    def test_holding_word_is_not_bit(self) -> None:
        assert RegisterAddress("HOLDING", 5, None).is_bit is False

    def test_holding_with_bit_is_bit(self) -> None:
        assert RegisterAddress("HOLDING", 5, 3).is_bit is True

    def test_coil_is_bit(self) -> None:
        assert RegisterAddress("COIL", 5, None).is_bit is True

    def test_discrete_is_bit(self) -> None:
        assert RegisterAddress("DISCRETE", 5, None).is_bit is True


class TestDecodeValue:
    """Per-dtype decoding of a 16-bit register value."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (0, 0),
            (12345, 12345),
            (0xFFFF, 0xFFFF),
        ],
    )
    def test_uint16(self, raw: int, expected: int) -> None:
        assert decode_value(raw, "uint16") == expected

    def test_word_alias(self) -> None:
        assert decode_value(12345, "word") == 12345

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (0, 0),
            (32767, 32767),  # 0x7FFF — max positive
            (32768, -32768),  # 0x8000 — min negative
            (65535, -1),  # 0xFFFF
        ],
    )
    def test_int16_two_complement(self, raw: int, expected: int) -> None:
        assert decode_value(raw, "int16") == expected

    @pytest.mark.parametrize("raw,expected", [(0, False), (1, True), (12345, True)])
    def test_bool(self, raw: int, expected: bool) -> None:
        assert decode_value(raw, "bool") is expected

    def test_unknown_dtype_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported dtype"):
            decode_value(0, "float32")

    def test_dtype_case_insensitive(self) -> None:
        assert decode_value(12345, "UINT16") == 12345
