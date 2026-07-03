"""Scaffold generator tests (golden + errors)."""

from pathlib import Path

import pytest
from click.testing import CliRunner
from plc_trace.cli import trace_group
from plc_trace.scaffold import ScaffoldError, generate_trace_blocks

FIXTURES = Path(__file__).parent / "fixtures"


def test_generate_blocks_golden():
    blocks = generate_trace_blocks(FIXTURES / "typeDemoTrace.s7dcl", depth=4, name="TraceData")
    assert set(blocks) == {"type", "db", "fc"}
    t = blocks["type"]
    assert "typeTraceData : STRUCT" in t
    assert "sampleCycles : Array[0..3] of UDInt;" in t
    assert "posX : Array[0..3] of Real;" in t
    assert "flag : Array[0..3] of Bool;" in t
    assert t.index("posX") < t.index("speedY") < t.index("counter") < t.index("flag")
    db = blocks["db"]
    assert "DATA_BLOCK TraceData : typeTraceData" in db
    assert "status.depth := 4;" in db
    fc = blocks["fc"]
    assert 'FUNCTION "TraceDataRecorder" : Void' in fc
    assert "trace : _.typeTraceData;" in fc
    assert "--- FILL SAMPLE" in fc and fc.count("// TODO: assign your signal") == 4
    assert "#trace.status.wrapped := TRUE;" in fc
    assert "MOD" not in fc  # decimation via down-counter, transpiler-safe


def test_generated_blocks_parse():
    from plc_code.parser import parse_scl_file

    blocks = generate_trace_blocks(FIXTURES / "typeDemoTrace.s7dcl", depth=4, name="TraceData")
    for key, text in blocks.items():
        p = Path(__file__).parent / f"_tmp_{key}.s7dcl"
        p.write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))
        try:
            assert parse_scl_file(p) is not None, key
        finally:
            p.unlink()


def test_scaffold_rejects_nested_udt(tmp_path: Path):
    bad = tmp_path / "typeBad.s7dcl"
    bad.write_text(
        "TYPE\n    typeBad : STRUCT\n        sub : _.typeOther;\n    END_STRUCT;\nEND_TYPE\n",
        encoding="utf-8",
    )
    with pytest.raises(ScaffoldError, match="flatten"):
        generate_trace_blocks(bad, depth=4, name="T")


def test_scaffold_rejects_forbidden_type(tmp_path: Path):
    bad = tmp_path / "typeBad.s7dcl"
    bad.write_text(
        "TYPE\n    typeBad : STRUCT\n        s : String;\n    END_STRUCT;\nEND_TYPE\n",
        encoding="utf-8",
    )
    with pytest.raises(ScaffoldError, match="String"):
        generate_trace_blocks(bad, depth=4, name="T")


def test_cli_scaffold_writes_crlf_bom_and_respects_force(tmp_path: Path):
    runner = CliRunner()
    args = [
        "scaffold",
        "--udt",
        str(FIXTURES / "typeDemoTrace.s7dcl"),
        "--depth",
        "4",
        "--name",
        "TraceData",
        "--out",
        str(tmp_path),
    ]
    result = runner.invoke(trace_group, args)
    assert result.exit_code == 0, result.output
    fc = tmp_path / "TraceDataRecorder.s7dcl"
    raw = fc.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw and b"\n" == raw[-1:]
    # second run without --force must refuse (FILL region holds project work)
    result2 = runner.invoke(trace_group, args)
    assert result2.exit_code != 0 and "force" in result2.output.lower()
    result3 = runner.invoke(trace_group, args + ["--force"])
    assert result3.exit_code == 0
