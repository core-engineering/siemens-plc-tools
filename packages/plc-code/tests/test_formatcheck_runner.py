"""Walking a workspace and aggregating findings."""

from __future__ import annotations

from pathlib import Path

from s7dcl_helpers import write_s7dcl
from test_formatcheck_checks import DB, FB, TAGS, UDT

from plc_code.formatcheck.runner import check_file, check_path


def test_check_file_runs_bytes_then_text(tmp_path: Path) -> None:
    p = write_s7dcl(tmp_path, "Wrong.s7dcl", FB, bom=False)
    assert [f.code for f in check_file(p)] == ["F001", "F012"]


def test_undecodable_file_stops_at_f003(tmp_path: Path) -> None:
    p = tmp_path / "Probe.s7dcl"
    p.write_bytes(b"\xef\xbb\xbfFUNCTION_BLOCK \xff\r\n")
    assert [f.code for f in check_file(p)] == ["F003"]


def test_check_path_walks_s7dcl_and_xml(tmp_path: Path) -> None:
    write_s7dcl(tmp_path / "Program blocks" / "100 - Process", "Probe.s7dcl", FB)
    write_s7dcl(tmp_path / "Program blocks", "Probe.s7dcl", DB)
    write_s7dcl(tmp_path / "PLC data types", "typeProbe.s7dcl", UDT)
    (tmp_path / "PLC tags").mkdir()
    (tmp_path / "PLC tags" / "Probe.xml").write_text(TAGS, encoding="utf-8")
    report = check_path(tmp_path)
    assert report.files == 4
    assert report.findings == []
    assert report.passed


def test_report_counts_and_passed(tmp_path: Path) -> None:
    write_s7dcl(tmp_path, "Probe.s7dcl", FB.replace('    S7_Optimized := "TRUE";\n', ""), bom=False)
    report = check_path(tmp_path)
    assert (report.errors, report.warnings) == (1, 1)
    assert not report.passed


def test_single_file_path(tmp_path: Path) -> None:
    p = write_s7dcl(tmp_path, "Probe.s7dcl", FB)
    assert check_path(p).files == 1


def test_findings_are_sorted_by_path(tmp_path: Path) -> None:
    write_s7dcl(tmp_path / "b", "Probe.s7dcl", FB, bom=False)
    write_s7dcl(tmp_path / "a", "Probe.s7dcl", FB, bom=False)
    report = check_path(tmp_path)
    assert [f.path.parent.name for f in report.findings] == ["a", "b"]
