"""Parsing the data-type strings the parser produces."""

from __future__ import annotations

from plc_code.layout.typespec import parse_type_spec


def test_scalar() -> None:
    spec = parse_type_spec("Int")
    assert (spec.base, spec.dims, spec.string_length, spec.is_struct) == ("Int", (), None, False)


def test_udt_prefixes_are_stripped() -> None:
    assert parse_type_spec("_.typeMotor").base == "typeMotor"
    assert parse_type_spec('"typeMotor"').base == "typeMotor"


def test_string_lengths() -> None:
    assert parse_type_spec("String[16]").string_length == 16
    assert parse_type_spec("String").string_length == 254
    assert parse_type_spec("WString[8]").string_length == 8
    assert parse_type_spec("WString").string_length == 254


def test_arrays() -> None:
    spec = parse_type_spec("Array[0..7] of DInt")
    assert (spec.base, spec.dims, spec.element_count) == ("DInt", ((0, 7),), 8)
    spec = parse_type_spec("Array[1..2, 0..3] of _.typeMotor")
    assert (spec.base, spec.dims, spec.element_count) == ("typeMotor", ((1, 2), (0, 3)), 8)


def test_array_of_string_keeps_length() -> None:
    spec = parse_type_spec("Array[0..1] of String[4]")
    assert (spec.base, spec.string_length, spec.element_count) == ("String", 4, 2)


def test_struct() -> None:
    assert parse_type_spec("Struct").is_struct
