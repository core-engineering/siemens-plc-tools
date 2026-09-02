"""DATA_BLOCK bodies: inline VAR members, typed DB initial values, instance DBs."""

from __future__ import annotations

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
