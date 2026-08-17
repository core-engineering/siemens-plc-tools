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
