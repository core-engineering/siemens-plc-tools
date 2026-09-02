"""DATA_BLOCK bodies: inline VAR members, typed DB initial values, instance DBs."""

from __future__ import annotations

from pathlib import Path

from s7dcl_helpers import write_s7dcl

from plc_code.parser import parse_scl_file
from plc_code.parser.models import Block, StructField, VariableAttributes, VariableDeclaration


def test_models_carry_db_fields() -> None:
    attrs = VariableAttributes()
    assert attrs.setpoint == "" and attrs.extra == {}
    var = VariableDeclaration(name="a", data_type="Int")
    assert var.parent == ""
    field = StructField(name="a", data_type="Int")
    assert field.parent == ""
    block = Block(name="Probe", block_type="DATA_BLOCK")
    assert block.initial_values == {}


HEADER = '{\n    S7_Optimized := "TRUE";\n    S7_StandardRetain := "FALSE";\n    S7_Version := "0.1"\n}\n'

INLINE = HEADER + (
    'DATA_BLOCK Probe\n    VAR\n        { S7_Setpoint := "False" }\n        count : Int := 3;\n'
    "        ratio : LReal;\n        motor : _.typeMotor;\n        hist : Array[0..7] of DInt;\n"
    "        label : String[16] := 'hello';\n    END_VAR\nEND_DATA_BLOCK\n"
)

TYPED = HEADER + (
    "DATA_BLOCK ProbeParameter : typeProbeParameter\n    axes[1].absKind := 1;\n"
    "    axes[1].coderLsbDeg := 0.0439453125;\n    axes[2].mountingOffsetDeg := -45.0;\n"
    "    delay := T#150ms;\n    mask := 16#A5;\n    name := 'deep';\n    hist := [1, 2, 3, 4];\n"
    "END_DATA_BLOCK\n"
)

INSTANCE = HEADER + "DATA_BLOCK ProbeInstance : Probe\nEND_DATA_BLOCK\n"


def _parse(tmp_path: Path, name: str, text: str):
    return parse_scl_file(write_s7dcl(tmp_path, name, text))


def test_inline_db_members_land_in_a_var_section(tmp_path: Path) -> None:
    block = _parse(tmp_path, "Probe.s7dcl", INLINE)
    assert block.block_type == "DATA_BLOCK" and block.base_type is None
    assert [s.section_type for s in block.variable_sections] == ["VAR"]
    names = [(v.name, v.data_type, v.default_value) for v in block.variable_sections[0].variables]
    assert names == [
        ("count", "Int", "3"),
        ("ratio", "LReal", None),
        ("motor", "_.typeMotor", None),
        ("hist", "Array[0..7] of DInt", None),
        ("label", "String[16]", "'hello'"),
    ]


def test_setpoint_pragma_is_kept_on_the_member(tmp_path: Path) -> None:
    block = _parse(tmp_path, "Probe.s7dcl", INLINE)
    count, ratio = block.variable_sections[0].variables[:2]
    assert count.attributes.setpoint == "False"
    assert ratio.attributes.setpoint == ""


def test_unknown_member_pragma_goes_to_extra(tmp_path: Path) -> None:
    text = INLINE.replace(
        '{ S7_Setpoint := "False" }', '{ S7_Setpoint := "True"; S7_HMI_Visible := "False" }'
    )
    block = _parse(tmp_path, "Probe.s7dcl", text)
    attrs = block.variable_sections[0].variables[0].attributes
    assert attrs.setpoint == "True" and attrs.extra == {"S7_HMI_Visible": "False"}


def test_typed_db_initial_values_in_source_order(tmp_path: Path) -> None:
    block = _parse(tmp_path, "ProbeParameter.s7dcl", TYPED)
    assert block.base_type == "typeProbeParameter"
    assert block.variable_sections == []
    assert list(block.initial_values.items()) == [
        ("axes[1].absKind", "1"),
        ("axes[1].coderLsbDeg", "0.0439453125"),
        ("axes[2].mountingOffsetDeg", "-45.0"),
        ("delay", "T#150ms"),
        ("mask", "16#A5"),
        ("name", "'deep'"),
        ("hist", "[1, 2, 3, 4]"),
    ]


def test_instance_db_has_base_type_and_nothing_else(tmp_path: Path) -> None:
    block = _parse(tmp_path, "ProbeInstance.s7dcl", INSTANCE)
    assert block.base_type == "Probe" and block.initial_values == {} and block.variable_sections == []
