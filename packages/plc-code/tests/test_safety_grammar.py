"""The SD grammar rules, checked against the shapes TIA actually refused."""

from pathlib import Path

from plc_code.formatcheck.safety_grammar import check_s7res_pair, check_safety_grammar

SAFETY_HEADER = '{\n    S7_Optimized := "TRUE";\n    S7_Safety := "True";\n    S7_Version := "0.1"\n}\n'


def codes(findings) -> list[str]:
    return [f.code for f in findings]


def test_title_line_is_refused_wherever_it_sits() -> None:
    text = SAFETY_HEADER + 'DATA_BLOCK Sample\nTITLE = a berth - a tool - a date\n    VAR\n    END_VAR\nEND_DATA_BLOCK\n'
    findings = check_safety_grammar(Path("Sample.s7dcl"), text)
    assert codes(findings) == ["S001"]
    assert findings[0].line == 7  # l'en-tete d'attributs fait cinq lignes, puis DATA_BLOCK


def test_declaration_with_an_initial_value_is_refused() -> None:
    text = SAFETY_HEADER + 'DATA_BLOCK Sample\n    VAR\n        count : DInt := 4;\n        bare : DInt;\n    END_VAR\n    count := 4;\nEND_DATA_BLOCK\n'
    findings = check_safety_grammar(Path("Sample.s7dcl"), text)
    assert codes(findings) == ["S002"]
    # Seule la declaration est signalee : l'affectation apres END_VAR est la forme ADMISE.
    assert findings[0].line == 8


def test_struct_is_refused_in_a_safety_interface_only() -> None:
    body = 'DATA_BLOCK Sample\n    VAR\n        nested : Struct\n        End_Struct;\n    END_VAR\nEND_DATA_BLOCK\n'
    assert codes(check_safety_grammar(Path("S.s7dcl"), SAFETY_HEADER + body)) == ["S003"]
    standard = '{\n    S7_Optimized := "TRUE"\n}\n' + body
    assert codes(check_safety_grammar(Path("S.s7dcl"), standard)) == []


def test_variable_length_array_only_in_var_in_out() -> None:
    ok = SAFETY_HEADER + 'FUNCTION "F" : Void\n    VAR_IN_OUT\n        table : Array[*] of DInt;\n    END_VAR\nEND_FUNCTION\n'
    assert codes(check_safety_grammar(Path("F.s7dcl"), ok)) == []
    bad = SAFETY_HEADER + 'FUNCTION "F" : Void\n    VAR_INPUT\n        table : Array[*] of DInt;\n    END_VAR\nEND_FUNCTION\n'
    assert codes(check_safety_grammar(Path("F.s7dcl"), bad)) == ["S009"]


def test_user_calls_are_quoted_and_system_instructions_are_not() -> None:
    text = SAFETY_HEADER + 'FUNCTION "F" : Void\n    VAR_TEMP\n    END_VAR\n            Sub(\n            )\n            FkStage(\n            )\n            "FkTip"(\n            )\nEND_FUNCTION\n'
    findings = check_safety_grammar(Path("F.s7dcl"), text)
    assert codes(findings) == ["S007"]
    assert "FkStage" in findings[0].message


def test_a_member_read_and_written_by_the_same_safety_block() -> None:
    text = (SAFETY_HEADER + 'FUNCTION "F" : Void\n    VAR_TEMP\n    END_VAR\n'
            '            "Io".A1_fault3 := 0;\n'
            '            Sub(\n                in1 := "Io".A1_alpha,\n                out => "Io".A1_fault3\n            )\n'
            '            Contact( "Io".A1_fault3 )\n'
            '            Coil( "Io".A1_fault )\nEND_FUNCTION\n')
    findings = [f for f in check_safety_grammar(Path("F.s7dcl"), text) if f.code == "S008"]
    assert len(findings) == 1
    assert "Io.A1_fault3" in findings[0].message
    # Un membre seulement lu, ou seulement ecrit, ne dit rien.
    assert "A1_alpha" not in findings[0].message and "A1_fault\"" not in findings[0].message


def test_mlcid_identifiers_resolve_in_both_directions() -> None:
    dcl = SAFETY_HEADER.replace('S7_Optimized', 'S7_BlockTitle := "MLC_B";\n    S7_Optimized') + 'DATA_BLOCK Sample\nEND_DATA_BLOCK\n'
    resolved = 'MultiLingualTexts:\n  - id: MLC_B\n    en-US: "a title"\n'
    assert codes(check_s7res_pair(Path("S.s7dcl"), dcl, resolved)) == []
    assert codes(check_s7res_pair(Path("S.s7dcl"), dcl, None)) == ["S005"]
    missing = 'MultiLingualTexts:\n  - id: MLC_OTHER\n    en-US: "a title"\n'
    assert sorted(codes(check_s7res_pair(Path("S.s7dcl"), dcl, missing))) == ["S005", "S005"]


def test_unquoted_yaml_text_with_a_colon_is_refused() -> None:
    dcl = SAFETY_HEADER.replace('S7_Optimized', 'S7_BlockTitle := "MLC_B";\n    S7_Optimized') + 'DATA_BLOCK S\nEND_DATA_BLOCK\n'
    res = 'MultiLingualTexts:\n  - id: MLC_B\n    en-US: Cell index: relCenti / 10\n'
    findings = check_s7res_pair(Path("S.s7dcl"), dcl, res)
    assert "S006" in codes(findings)
