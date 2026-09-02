"""Resolving UDT names across the `PLC data types` folders."""

from __future__ import annotations

from pathlib import Path

import pytest
from s7dcl_helpers import write_s7dcl

from plc_code.layout.registry import TypeRegistry, UnknownTypeError

MOTOR = (
    "TYPE\n"
    "    typeMotor : STRUCT\n"
    "        speed : Real;\n"
    "        running : Bool;\n"
    "    END_STRUCT;\n"
    "END_TYPE\n"
)
AXIS = (
    "TYPE\n"
    "    typeAxis : STRUCT\n"
    "        motor : _.typeMotor;\n"
    "        limit : Int;\n"
    "    END_STRUCT;\n"
    "END_TYPE\n"
)


def test_from_directories_collects_types_recursively(tmp_path: Path) -> None:
    write_s7dcl(tmp_path / "types" / "10 - Data", "typeMotor.s7dcl", MOTOR)
    write_s7dcl(tmp_path / "types" / "20 - Parameters", "typeAxis.s7dcl", AXIS)
    registry = TypeRegistry.from_directories(tmp_path / "types")
    assert "typeMotor" in registry and "typeAxis" in registry
    assert [f.name for f in registry.get("typeAxis").fields] == ["motor", "limit"]


def test_spellings_resolve_to_the_same_type(tmp_path: Path) -> None:
    write_s7dcl(tmp_path, "typeMotor.s7dcl", MOTOR)
    registry = TypeRegistry.from_directories(tmp_path)
    assert registry.get("_.typeMotor") is registry.get('"typeMotor"') is registry.get("typeMotor")


def test_unknown_type_raises_with_the_name(tmp_path: Path) -> None:
    registry = TypeRegistry.from_directories(tmp_path)
    with pytest.raises(UnknownTypeError, match="typeGhost"):
        registry.get("typeGhost")


def test_non_type_blocks_are_ignored(tmp_path: Path) -> None:
    write_s7dcl(tmp_path, "typeMotor.s7dcl", MOTOR)
    data_block = (
        "{\n"
        '    S7_Optimized := "TRUE";\n'
        '    S7_StandardRetain := "FALSE";\n'
        '    S7_Version := "0.1"\n'
        "}\n"
        "DATA_BLOCK Probe\n"
        "END_DATA_BLOCK\n"
    )
    write_s7dcl(tmp_path, "Probe.s7dcl", data_block)
    assert len(TypeRegistry.from_directories(tmp_path)) == 1
