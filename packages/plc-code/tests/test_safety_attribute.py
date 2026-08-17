"""S7_Safety must reach the model, in both spellings the corpus uses.

The attribute is how a Siemens F block declares itself. Before this, it was
parsed nowhere in plc-code, so every rule, document and diagnostic treated an
F block exactly like a standard one — 36 files in one delivered project.

Both spellings are real: the corpus has "TRUE" 20 times and "True" 16 times,
so a strict comparison would miss 44% of the F blocks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plc_code.parser import parse_scl_file


def _block(pragma: str) -> str:
    return f"""
{{
    S7_Optimized := "TRUE";{pragma}
}}
FUNCTION_BLOCK "Probe"
    VAR_INPUT
        a : Bool;
    END_VAR
    {{ S7_Language := "SCL" }}
    NETWORK
        REGION Logic
            #a := FALSE;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


def _parse(tmp_path: Path, pragma: str):
    path = tmp_path / "Probe.s7dcl"
    path.write_text(_block(pragma), encoding="utf-8")
    return parse_scl_file(path)


class TestSafetyAttribute:
    @pytest.mark.parametrize("value", ["TRUE", "True", "true"])
    def test_truthy_spellings_all_set_the_flag(self, tmp_path: Path, value: str) -> None:
        block = _parse(tmp_path, f'\n        S7_Safety := "{value}";')
        assert block.attributes.is_safety is True

    def test_absent_attribute_means_not_safety(self, tmp_path: Path) -> None:
        block = _parse(tmp_path, "")
        assert block.attributes.is_safety is False

    @pytest.mark.parametrize("value", ["FALSE", "False", ""])
    def test_falsy_values_do_not_set_the_flag(self, tmp_path: Path, value: str) -> None:
        block = _parse(tmp_path, f'\n        S7_Safety := "{value}";')
        assert block.attributes.is_safety is False

    def test_other_attributes_still_parse(self, tmp_path: Path) -> None:
        """The new branch must not shadow the existing chain."""
        block = _parse(tmp_path, '\n    S7_Safety := "True";')
        assert block.attributes.optimized is True

    def test_pragma_before_declaration_sets_safety(self, tmp_path: Path) -> None:
        """Verify that S7_Safety in pragma-before-declaration (real corpus shape) works."""
        code = """
{
    S7_Safety := "TRUE";
}
FUNCTION_BLOCK "RealCorpusShape"
    VAR_INPUT
        input1 : Bool;
    END_VAR
    NETWORK
        REGION Logic
            #input1 := FALSE;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        path = tmp_path / "test.s7dcl"
        path.write_text(code, encoding="utf-8")
        block = parse_scl_file(path)
        assert block.attributes.is_safety is True


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _udt(tmp_path: Path, pragma: str) -> str:
    path = tmp_path / "typeFoo.s7dcl"
    path.write_text(
        f"TYPE\n{pragma}    typeFoo : STRUCT\n        a : Bool;\n    END_STRUCT;\nEND_TYPE\n",
        encoding="utf-8",
    )
    return path


class TestUdtSafetyAttribute:
    """The pragma sits before the type name and used to block it.

    `_parse_udt` expected an IDENTIFIER at the cursor, so a leading pragma left
    both `Block.name` and `UserDataType.name` empty. Reading the flag requires
    consuming the pragma, which fixes the name too — one change, two effects.
    """

    def test_pragma_sets_the_udt_flag(self, tmp_path: Path) -> None:
        block = parse_scl_file(_udt(tmp_path, '    { S7_Safety := "True" }\n'))
        assert block.user_data_type is not None
        assert block.user_data_type.is_safety is True

    def test_pragma_no_longer_blocks_the_type_name(self, tmp_path: Path) -> None:
        block = parse_scl_file(_udt(tmp_path, '    { S7_Safety := "True" }\n'))
        assert block.name == "typeFoo"
        assert block.user_data_type is not None
        assert block.user_data_type.name == "typeFoo"

    def test_udt_without_a_pragma_still_parses_its_name(self, tmp_path: Path) -> None:
        """The fix must not trade one break for another."""
        block = parse_scl_file(_udt(tmp_path, ""))
        assert block.name == "typeFoo"
        assert block.user_data_type is not None
        assert block.user_data_type.name == "typeFoo"
        assert block.user_data_type.is_safety is False

    def test_non_safety_pragma_leaves_the_flag_false_and_the_name_read(self, tmp_path: Path) -> None:
        block = parse_scl_file(_udt(tmp_path, '    { S7_Setpoint := "False" }\n'))
        assert block.name == "typeFoo"
        assert block.user_data_type is not None
        assert block.user_data_type.is_safety is False

    def test_shipped_fixture_is_recognised(self) -> None:
        block = parse_scl_file(FIXTURES / "typeSafetyProbe.s7dcl")
        assert block.name == "typeSafetyProbe"
        assert block.user_data_type is not None
        assert block.user_data_type.is_safety is True
