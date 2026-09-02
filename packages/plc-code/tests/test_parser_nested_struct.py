"""Inline Struct members: flat list kept, nesting recorded in `parent`."""

from __future__ import annotations

from pathlib import Path

from s7dcl_helpers import write_s7dcl

from plc_code.parser import parse_scl_file

DB_HEADER = '{\n    S7_Optimized := "TRUE";\n    S7_StandardRetain := "FALSE";\n    S7_Version := "0.1"\n}\n'
FB_HEADER = '{\n    S7_EditorMode := "SCL";\n    S7_Optimized := "TRUE";\n    S7_Version := "0.1"\n}\n'

NESTED_DB = DB_HEADER + (
    "DATA_BLOCK Probe\n    VAR\n        a : Int;\n        s : Struct\n            x : Bool;\n"
    "            inner : Struct\n                y : DInt;\n            END_STRUCT;\n            z : Real;\n"
    "        END_STRUCT;\n        b : Byte;\n    END_VAR\nEND_DATA_BLOCK\n"
)

NESTED_FB = FB_HEADER + (
    'FUNCTION_BLOCK "ProbeFb"\n    VAR\n        a : Int;\n        s : Struct\n            x : Bool;\n'
    '        END_STRUCT;\n    END_VAR\n\n    { S7_Language := "SCL" }\n    NETWORK\n        #a := 1;\n'
    "    END_NETWORK\nEND_FUNCTION_BLOCK\n"
)

NESTED_UDT = (
    "TYPE\n    typeProbe : STRUCT\n        a : Int;\n        s : Struct\n            x : Bool;\n"
    "            y : Real;\n        END_STRUCT;\n    END_STRUCT;\nEND_TYPE\n"
)

ARRAY_OF_STRUCT_DB = DB_HEADER + (
    "DATA_BLOCK ProbeArr\n    VAR\n        s : Struct\n            arr : Array[0..1] of Struct\n"
    "                x : Bool;\n            END_STRUCT;\n            y : Real;\n        END_STRUCT;\n"
    "    END_VAR\nEND_DATA_BLOCK\n"
)

ARRAY_OF_STRUCT_UDT = (
    "TYPE\n    typeProbeArr : STRUCT\n        s : Struct\n            arr : Array[0..1] of Struct\n"
    "                x : Bool;\n            END_STRUCT;\n            y : Real;\n        END_STRUCT;\n"
    "    END_STRUCT;\nEND_TYPE\n"
)

SETPOINT_IN_STRUCT_DB = DB_HEADER + (
    'DATA_BLOCK ProbeSetpoint\n    VAR\n        s : Struct\n            { S7_Setpoint := "True" }\n'
    "            x : Bool;\n        END_STRUCT;\n    END_VAR\nEND_DATA_BLOCK\n"
)


def test_db_struct_children_carry_parent_paths(tmp_path: Path) -> None:
    block = parse_scl_file(write_s7dcl(tmp_path, "Probe.s7dcl", NESTED_DB))
    rows = [(v.name, v.data_type, v.parent) for v in block.variable_sections[0].variables]
    assert rows == [
        ("a", "Int", ""),
        ("s", "Struct", ""),
        ("x", "Bool", "s"),
        ("inner", "Struct", "s"),
        ("y", "DInt", "s.inner"),
        ("z", "Real", "s"),
        ("b", "Byte", ""),
    ]


def test_fb_flat_list_is_unchanged_except_the_struct_entry(tmp_path: Path) -> None:
    block = parse_scl_file(write_s7dcl(tmp_path, "ProbeFb.s7dcl", NESTED_FB))
    rows = [(v.name, v.data_type, v.parent) for v in block.variable_sections[0].variables]
    assert rows == [("a", "Int", ""), ("s", "Struct", ""), ("x", "Bool", "s")]


def test_udt_struct_fields_carry_parent_paths(tmp_path: Path) -> None:
    block = parse_scl_file(write_s7dcl(tmp_path, "typeProbe.s7dcl", NESTED_UDT))
    assert block.user_data_type is not None
    rows = [(f.name, f.data_type, f.parent) for f in block.user_data_type.fields]
    assert rows == [("a", "Int", ""), ("s", "Struct", ""), ("x", "Bool", "s"), ("y", "Real", "s")]


def test_db_array_of_struct_member_keeps_its_own_end_struct_scoped(tmp_path: Path) -> None:
    """An `Array[..] of Struct` member opens its own inline Struct body too.

    Its `END_STRUCT` must close only that member's body, not the enclosing
    Struct's - otherwise the enclosing Struct's remaining members end up
    tagged as top-level instead of nested under it.
    """
    block = parse_scl_file(write_s7dcl(tmp_path, "ProbeArr.s7dcl", ARRAY_OF_STRUCT_DB))
    rows = [(v.name, v.data_type, v.parent) for v in block.variable_sections[0].variables]
    assert rows == [
        ("s", "Struct", ""),
        ("arr", "Array[0..1] of Struct", "s"),
        ("x", "Bool", "s.arr"),
        ("y", "Real", "s"),
    ]


def test_udt_array_of_struct_field_keeps_its_own_end_struct_scoped(tmp_path: Path) -> None:
    block = parse_scl_file(write_s7dcl(tmp_path, "typeProbeArr.s7dcl", ARRAY_OF_STRUCT_UDT))
    assert block.user_data_type is not None
    rows = [(f.name, f.data_type, f.parent) for f in block.user_data_type.fields]
    assert rows == [
        ("s", "Struct", ""),
        ("arr", "Array[0..1] of Struct", "s"),
        ("x", "Bool", "s.arr"),
        ("y", "Real", "s"),
    ]


def test_db_pragma_on_struct_member_keeps_attributes_and_parent(tmp_path: Path) -> None:
    block = parse_scl_file(write_s7dcl(tmp_path, "ProbeSetpoint.s7dcl", SETPOINT_IN_STRUCT_DB))
    variables = block.variable_sections[0].variables
    x = next(v for v in variables if v.name == "x")
    assert x.attributes.setpoint == "True"
    assert x.parent == "s"
