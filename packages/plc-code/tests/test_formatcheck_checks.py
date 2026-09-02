"""Byte-level import-readiness checks (F001 BOM, F002 CRLF, F003 UTF-8)."""

from __future__ import annotations

from pathlib import Path

from s7dcl_helpers import write_s7dcl

from plc_code.formatcheck.checks import check_bytes, check_text, scan_block

FB = (
    '{\n    S7_EditorMode := "SCL";\n    S7_Optimized := "TRUE";\n'
    '    S7_Version := "0.1"\n}\nFUNCTION_BLOCK "Probe"\n'
    '    { S7_Language := "SCL" }\n    NETWORK\n    END_NETWORK\n'
    "END_FUNCTION_BLOCK\n"
)
DB = (
    '{\n    S7_Optimized := "TRUE";\n    S7_StandardRetain := "FALSE";\n'
    '    S7_Version := "0.1"\n}\nDATA_BLOCK Probe\n'
    "    VAR\n        a : Int;\n    END_VAR\nEND_DATA_BLOCK\n"
)
UDT = "TYPE\n    typeProbe : STRUCT\n        a : Int;\n    END_STRUCT;\nEND_TYPE\n"
EXTERNAL = (
    "FUNCTION_BLOCK \"Probe\"\nTITLE = 'Probe'\n"
    "{ S7_Optimized_Access := 'TRUE' }\nVERSION : 0.1\n"
    "BEGIN\nEND_FUNCTION_BLOCK\n"
)


def _codes(findings: list) -> list[str]:
    return [f.code for f in findings]


def test_clean_file_has_no_byte_findings(tmp_path: Path) -> None:
    p = write_s7dcl(tmp_path, "Probe.s7dcl", FB)
    assert check_bytes(p, p.read_bytes()) == []


def test_missing_bom_is_f001(tmp_path: Path) -> None:
    p = write_s7dcl(tmp_path, "Probe.s7dcl", FB, bom=False)
    findings = check_bytes(p, p.read_bytes())
    assert _codes(findings) == ["F001"]
    assert findings[0].severity == "ERROR"
    assert findings[0].line is None


def test_bare_lf_is_f002_with_first_offending_line(tmp_path: Path) -> None:
    text = FB.replace("\n", "\r\n", 2)  # first two line endings CRLF, the rest LF
    p = tmp_path / "Probe.s7dcl"
    p.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    findings = check_bytes(p, p.read_bytes())
    assert _codes(findings) == ["F002"]
    assert findings[0].line == 3


def test_invalid_utf8_is_f003_and_stops(tmp_path: Path) -> None:
    p = tmp_path / "Probe.s7dcl"
    p.write_bytes(b"\xef\xbb\xbfFUNCTION_BLOCK \xff\xfe\r\n")
    findings = check_bytes(p, p.read_bytes())
    assert _codes(findings) == ["F003"]


def test_missing_bom_and_lf_report_both(tmp_path: Path) -> None:
    p = write_s7dcl(tmp_path, "Probe.s7dcl", FB, bom=False, crlf=False)
    assert _codes(check_bytes(p, p.read_bytes())) == ["F001", "F002"]


def test_scan_block_reads_kind_name_and_pragma() -> None:
    header = scan_block(FB)
    assert header is not None
    assert (header.kind, header.name) == ("FUNCTION_BLOCK", "Probe")
    assert header.pragma["S7_EditorMode"] == "SCL"
    assert header.line == 6


def test_scan_block_reads_unquoted_db_and_udt_names() -> None:
    assert scan_block(DB).name == "Probe"  # type: ignore[union-attr]
    udt = scan_block(UDT)
    assert udt is not None and (udt.kind, udt.name) == ("TYPE", "typeProbe")


def test_clean_fb_db_udt_have_no_text_findings(tmp_path: Path) -> None:
    for name, text in (("Probe.s7dcl", FB), ("Probe.s7dcl", DB), ("typeProbe.s7dcl", UDT)):
        assert check_text(tmp_path / name, text) == []


def test_external_source_form_is_f010_only(tmp_path: Path) -> None:
    findings = check_text(tmp_path / "Other.s7dcl", EXTERNAL)
    assert [f.code for f in findings] == ["F010"]


def test_two_blocks_in_one_file_is_f011(tmp_path: Path) -> None:
    findings = check_text(tmp_path / "Probe.s7dcl", FB + FB)
    assert "F011" in [f.code for f in findings]


def test_file_stem_must_match_block_name(tmp_path: Path) -> None:
    findings = check_text(tmp_path / "Wrong.s7dcl", FB)
    assert [f.code for f in findings] == ["F012"]
    assert "Probe" in findings[0].message and "Wrong" in findings[0].message


def test_fb_without_editor_mode_is_f020(tmp_path: Path) -> None:
    text = FB.replace('    S7_EditorMode := "SCL";\n', "")
    assert [f.code for f in check_text(tmp_path / "Probe.s7dcl", text)] == ["F020"]


def test_db_without_standard_retain_is_f020(tmp_path: Path) -> None:
    text = DB.replace('    S7_StandardRetain := "FALSE";\n', "")
    assert [f.code for f in check_text(tmp_path / "Probe.s7dcl", text)] == ["F020"]


def test_missing_optimized_is_f021_warning(tmp_path: Path) -> None:
    text = FB.replace('    S7_Optimized := "TRUE";\n', "")
    findings = check_text(tmp_path / "Probe.s7dcl", text)
    assert [(f.code, f.severity) for f in findings] == [("F021", "WARNING")]


def test_udt_needs_no_pragma(tmp_path: Path) -> None:
    assert check_text(tmp_path / "typeProbe.s7dcl", UDT) == []


def test_f010_ignores_s7_optimized_access_in_line_comment(tmp_path: Path) -> None:
    text = FB.replace('    S7_Optimized := "TRUE";\n', "")
    text = text.replace("}\n", "}\n    // migrated from S7_Optimized_Access form\n")
    findings = check_text(tmp_path / "Probe.s7dcl", text)
    assert [f.code for f in findings] == ["F021"]


def test_f010_ignores_begin_in_block_comment(tmp_path: Path) -> None:
    text = FB.replace("NETWORK", "(* TODO: BEGIN here to split blocks *)\n    NETWORK")
    findings = check_text(tmp_path / "Probe.s7dcl", text)
    codes = [f.code for f in findings]
    assert "F010" not in codes


def test_f010_detects_real_external_source(tmp_path: Path) -> None:
    findings = check_text(tmp_path / "Other.s7dcl", EXTERNAL)
    assert [f.code for f in findings] == ["F010"]


def test_scan_block_ignores_struct_in_pragma_string(tmp_path: Path) -> None:
    text = (
        '{\n    S7_Optimized := "TRUE";\n    s7_note := "see x : STRUCT in spec";\n'
        '    S7_Version := "0.1"\n}\nTYPE\n    typeProbe : STRUCT\n'
        "        a : Int;\n    END_STRUCT;\nEND_TYPE\n"
    )
    header = scan_block(text)
    assert header is not None
    assert (header.kind, header.name) == ("TYPE", "typeProbe")
