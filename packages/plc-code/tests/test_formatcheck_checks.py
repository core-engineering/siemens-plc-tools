"""Byte-level import-readiness checks (F001 BOM, F002 CRLF, F003 UTF-8)."""

from __future__ import annotations

from pathlib import Path

from s7dcl_helpers import write_s7dcl

from plc_code.formatcheck.checks import check_bytes

FB = (
    '{\n    S7_EditorMode := "SCL";\n    S7_Optimized := "TRUE";\n'
    '    S7_Version := "0.1"\n}\nFUNCTION_BLOCK "Probe"\n'
    '    { S7_Language := "SCL" }\n    NETWORK\n    END_NETWORK\n'
    "END_FUNCTION_BLOCK\n"
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
