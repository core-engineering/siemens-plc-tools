"""Byte-level import-readiness checks (F001 BOM, F002 CRLF, F003 UTF-8)."""

from __future__ import annotations

from pathlib import Path

from s7dcl_helpers import write_s7dcl

from plc_code.formatcheck.checks import (
    _strip_comments_and_strings,
    check_bytes,
    check_text,
    check_xml,
    scan_block,
)

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
UDT_WITH_INLINE_STRUCT = (
    "TYPE\n    typeAxis : STRUCT\n        cfg : Struct\n            a : Int;\n"
    "        END_STRUCT;\n    END_STRUCT;\nEND_TYPE\n"
)
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


def test_scan_block_picks_udt_name_not_inline_struct_member(tmp_path: Path) -> None:
    # Regression: a UDT whose STRUCT holds an inline `Struct` member used to
    # be picked up as if `cfg` (the member) were the UDT's own name.
    header = scan_block(UDT_WITH_INLINE_STRUCT)
    assert header is not None
    assert (header.kind, header.name) == ("TYPE", "typeAxis")
    assert check_text(tmp_path / "typeAxis.s7dcl", UDT_WITH_INLINE_STRUCT) == []


def test_clean_fb_db_udt_have_no_text_findings(tmp_path: Path) -> None:
    for name, text in (("Probe.s7dcl", FB), ("Probe.s7dcl", DB), ("typeProbe.s7dcl", UDT)):
        assert check_text(tmp_path / name, text) == []


def test_external_source_form_is_f010_only(tmp_path: Path) -> None:
    findings = check_text(tmp_path / "Other.s7dcl", EXTERNAL)
    assert [f.code for f in findings] == ["F010"]


def test_two_blocks_in_one_file_is_f011(tmp_path: Path) -> None:
    findings = check_text(tmp_path / "Probe.s7dcl", FB + FB)
    assert "F011" in [f.code for f in findings]


def test_f011_ignores_block_keyword_in_block_comment(tmp_path: Path) -> None:
    # A change-history note quoting a block keyword must not read as a
    # second block.
    text = FB.replace("NETWORK", "(* history:\nDATA_BLOCK was here\n*)\n    NETWORK")
    findings = check_text(tmp_path / "Probe.s7dcl", text)
    assert "F011" not in [f.code for f in findings]


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
    # A standalone `BEGIN` line (what _BEGIN_RE actually matches) inside a
    # block comment, not `BEGIN` as a word mid-sentence.
    text = FB.replace("NETWORK", "(* history:\nBEGIN\n*)\n    NETWORK")
    findings = check_text(tmp_path / "Probe.s7dcl", text)
    codes = [f.code for f in findings]
    assert "F010" not in codes


def test_f010_detects_real_external_source(tmp_path: Path) -> None:
    findings = check_text(tmp_path / "Other.s7dcl", EXTERNAL)
    assert [f.code for f in findings] == ["F010"]


def test_scan_block_ignores_struct_name_in_block_comment(tmp_path: Path) -> None:
    # A `name : STRUCT` line standing alone inside a `(* ... *)` comment,
    # between the TYPE keyword and the UDT's real STRUCT line, must not be
    # picked up as the UDT name.
    text = (
        "TYPE\n    (* fakeUdt : STRUCT\n       old name, see history\n    *)\n"
        "    typeProbe : STRUCT\n        a : Int;\n    END_STRUCT;\nEND_TYPE\n"
    )
    header = scan_block(text)
    assert header is not None
    assert (header.kind, header.name) == ("TYPE", "typeProbe")


def test_strip_comments_and_strings_keeps_newline_count() -> None:
    text = (
        '{\n    S7_Optimized := "TRUE";\n}\n(* multi\n    line\n    comment *)\n'
        'FUNCTION_BLOCK "Probe"\nEND_FUNCTION_BLOCK\n'
    )
    stripped = _strip_comments_and_strings(text)
    assert stripped.count("\n") == text.count("\n")


TAGS = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    "<Document>\n"
    '  <Engineering version="V21" />\n'
    '  <SW.Tags.PlcTagTable ID="0">\n'
    "    <AttributeList><Name>Probe</Name></AttributeList>\n"
    "  </SW.Tags.PlcTagTable>\n"
    "</Document>\n"
)


def test_clean_tag_table_has_no_findings(tmp_path: Path) -> None:
    assert check_xml(tmp_path / "PLC tags" / "Probe.xml", TAGS) == []


def test_malformed_xml_under_plc_tags_is_f030(tmp_path: Path) -> None:
    findings = check_xml(tmp_path / "PLC tags" / "Probe.xml", "<Document><Engineering")
    assert [f.code for f in findings] == ["F030"]


def test_missing_engineering_version_is_f030(tmp_path: Path) -> None:
    text = TAGS.replace('  <Engineering version="V21" />\n', "")
    assert [f.code for f in check_xml(tmp_path / "PLC tags" / "Probe.xml", text)] == ["F030"]


def test_xml_outside_plc_tags_that_is_not_a_tag_table_is_f031(tmp_path: Path) -> None:
    findings = check_xml(tmp_path / "other" / "Probe.xml", "<Document><Other/></Document>")
    assert [(f.code, f.severity) for f in findings] == [("F031", "WARNING")]


def test_tag_table_outside_plc_tags_is_fine(tmp_path: Path) -> None:
    assert check_xml(tmp_path / "other" / "Probe.xml", TAGS) == []


def test_tag_table_outside_plc_tags_without_version_is_f030(tmp_path: Path) -> None:
    text = TAGS.replace('  <Engineering version="V21" />\n', "")
    assert [f.code for f in check_xml(tmp_path / "other" / "Probe.xml", text)] == ["F030"]


def test_non_tag_table_under_plc_tags_with_version_is_f030(tmp_path: Path) -> None:
    text = '<Document><Engineering version="V21" /><Other/></Document>'
    findings = check_xml(tmp_path / "PLC tags" / "Probe.xml", text)
    assert [f.code for f in findings] == ["F030"]
    assert "SW.Tags.PlcTagTable" in findings[0].message


def test_malformed_xml_outside_plc_tags_is_f031_warning(tmp_path: Path) -> None:
    findings = check_xml(tmp_path / "other" / "Probe.xml", "<Document><Engineering")
    assert [(f.code, f.severity) for f in findings] == [("F031", "WARNING")]
