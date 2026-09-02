"""compute_layout over parsed blocks: typed DB, inline DB, optimized refusal, instance DB."""

from __future__ import annotations

from pathlib import Path

import pytest
from s7dcl_helpers import write_s7dcl

from plc_code.layout.api import OptimizedBlockError, compute_layout
from plc_code.layout.registry import TypeRegistry, UnknownTypeError
from plc_code.parser import parse_scl_file

STD = '{\n    S7_Optimized := "FALSE";\n    S7_StandardRetain := "FALSE";\n    S7_Version := "0.1"\n}\n'
OPT = STD.replace('"FALSE";\n    S7_StandardRetain', '"TRUE";\n    S7_StandardRetain')
MOTOR = (
    "TYPE\n    typeMotor : STRUCT\n        speed : Real;\n"
    "        running : Bool;\n    END_STRUCT;\nEND_TYPE\n"
)

READ_ONLY = STD + (
    "DATA_BLOCK ReadOnly\n    VAR\n        int1 : Int := 10;\n        int2 : Int := 255;\n"
    "        float1 : Real := 123.45;\n        float2 : Real := 543.21;\n"
    "        byte1 : Byte := 16#0F;\n        byte2 : Byte := 16#F0;\n"
    "        word1 : Word := 16#ABCD;\n        word2 : Word := 16#1234;\n"
    "        dword1 : DWord := 16#12345678;\n        dword2 : DWord := 16#89ABCDEF;\n"
    "        dint1 : DInt := 2147483647;\n        dint2 : DInt := 42;\n"
    "        char1 : Char := 'F';\n        char2 : Char := '-';\n"
    "        bool0 : Bool := TRUE;\n        bool1 : Bool;\n        bool2 : Bool;\n        bool3 : Bool;\n"
    "        bool4 : Bool;\n        bool5 : Bool;\n        bool6 : Bool;\n        bool7 : Bool;\n"
    "    END_VAR\nEND_DATA_BLOCK\n"
)


def test_the_37_byte_reference_block(tmp_path: Path) -> None:
    block = parse_scl_file(write_s7dcl(tmp_path, "ReadOnly.s7dcl", READ_ONLY))
    layout = compute_layout(block, TypeRegistry())
    assert layout.block == "ReadOnly" and not layout.optimized
    assert layout.leaf("float1").byte_offset == 4
    assert layout.leaf("byte2").byte_offset == 13
    assert layout.leaf("dint2").byte_offset == 30
    assert layout.leaf("char2").byte_offset == 35
    assert (layout.leaf("bool0").byte_offset, layout.leaf("bool7").bit_offset) == (36, 7)
    assert layout.total_size == 38


def test_typed_db_uses_its_udt(tmp_path: Path) -> None:
    write_s7dcl(tmp_path / "types", "typeMotor.s7dcl", MOTOR)
    source = STD + "DATA_BLOCK MotorData : typeMotor\nEND_DATA_BLOCK\n"
    block = parse_scl_file(write_s7dcl(tmp_path, "MotorData.s7dcl", source))
    layout = compute_layout(block, TypeRegistry.from_directories(tmp_path / "types"))
    assert [(m.path, m.byte_offset) for m in layout.members if m.is_leaf] == [("speed", 0), ("running", 4)]


def test_optimized_db_is_refused_unless_forced(tmp_path: Path) -> None:
    source = OPT + "DATA_BLOCK Opt\n    VAR\n        a : Int;\n    END_VAR\nEND_DATA_BLOCK\n"
    block = parse_scl_file(write_s7dcl(tmp_path, "Opt.s7dcl", source))
    with pytest.raises(OptimizedBlockError, match="Opt"):
        compute_layout(block, TypeRegistry())
    layout = compute_layout(block, TypeRegistry(), force=True)
    assert layout.optimized and layout.leaf("a").byte_offset == 0


def test_instance_db_has_no_layout_from_source(tmp_path: Path) -> None:
    source = STD + "DATA_BLOCK ProbeInstance : Probe\nEND_DATA_BLOCK\n"
    block = parse_scl_file(write_s7dcl(tmp_path, "ProbeInstance.s7dcl", source))
    with pytest.raises(UnknownTypeError, match="Probe"):
        compute_layout(block, TypeRegistry())


def test_non_db_block_is_rejected(tmp_path: Path) -> None:
    block = parse_scl_file(write_s7dcl(tmp_path, "typeMotor.s7dcl", MOTOR))
    with pytest.raises(ValueError, match="DATA_BLOCK"):
        compute_layout(block, TypeRegistry())
