"""`plc code layout` output formats and error paths."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from s7dcl_helpers import write_s7dcl
from test_layout_api import MOTOR, OPT, STD

from plc_code.cli import cli

PROBE_BODY = (
    "DATA_BLOCK Probe\n    VAR\n        flag : Bool;\n        m : _.typeMotor;\n    END_VAR\nEND_DATA_BLOCK\n"
)


def _db(tmp_path: Path) -> Path:
    write_s7dcl(tmp_path / "types", "typeMotor.s7dcl", MOTOR)
    return write_s7dcl(tmp_path, "Probe.s7dcl", STD + PROBE_BODY)


def test_table_output(tmp_path: Path) -> None:
    db = _db(tmp_path)
    result = CliRunner().invoke(cli, ["layout", str(db), "--types", str(tmp_path / "types")])
    assert result.exit_code == 0, result.output
    assert (
        "m.speed" in result.output
        and "2.0" in result.output
        and "m.running" in result.output
        and "6.0" in result.output
    )
    assert "total 8" in result.output


def test_json_output(tmp_path: Path) -> None:
    db = _db(tmp_path)
    result = CliRunner().invoke(
        cli, ["layout", str(db), "--types", str(tmp_path / "types"), "--format", "json"]
    )
    payload = json.loads(result.output)
    assert payload["block"] == "Probe" and payload["total_size"] == 8 and payload["optimized"] is False
    leaf = [m for m in payload["members"] if m["path"] == "m.running"][0]
    assert (leaf["byte_offset"], leaf["bit_offset"], leaf["is_leaf"]) == (6, 0, True)


def test_csv_output(tmp_path: Path) -> None:
    db = _db(tmp_path)
    result = CliRunner().invoke(
        cli, ["layout", str(db), "--types", str(tmp_path / "types"), "--format", "csv"]
    )
    lines = result.output.strip().splitlines()
    assert lines[0] == "path,data_type,byte_offset,bit_offset,size_bytes,size_bits,is_leaf"
    assert "m.speed,Real,2,0,4,32,True" in lines


def test_optimized_refused_then_forced(tmp_path: Path) -> None:
    db = write_s7dcl(
        tmp_path,
        "Opt.s7dcl",
        OPT + "DATA_BLOCK Opt\n    VAR\n        a : Int;\n    END_VAR\nEND_DATA_BLOCK\n",
    )
    refused = CliRunner().invoke(cli, ["layout", str(db)])
    assert refused.exit_code == 1 and "optimized" in refused.output
    forced = CliRunner().invoke(cli, ["layout", str(db), "--force"])
    assert forced.exit_code == 0 and "not guaranteed" in forced.output


def test_unknown_type_is_a_clean_error(tmp_path: Path) -> None:
    db = write_s7dcl(
        tmp_path,
        "Probe.s7dcl",
        STD + "DATA_BLOCK Probe\n    VAR\n        g : _.typeGhost;\n    END_VAR\nEND_DATA_BLOCK\n",
    )
    result = CliRunner().invoke(cli, ["layout", str(db)])
    assert result.exit_code == 1 and "typeGhost" in result.output


def test_instance_db_unknown_type_gets_a_dedicated_hint(tmp_path: Path) -> None:
    db = write_s7dcl(
        tmp_path, "ProbeInstance.s7dcl", STD + "DATA_BLOCK ProbeInstance : Probe\nEND_DATA_BLOCK\n"
    )
    result = CliRunner().invoke(cli, ["layout", str(db)])
    assert result.exit_code == 1
    normalized = " ".join(result.output.split())
    assert "'Probe' is not a user data type: an instance DB has no standard layout from source" in normalized


def test_registry_problems_are_warned_and_do_not_block(tmp_path: Path) -> None:
    write_s7dcl(tmp_path / "types", "typeMotor.s7dcl", MOTOR)
    broken = '{\n    S7_Version := "0.1"\n}\nNOT_A_BLOCK_KEYWORD Weird\n'
    write_s7dcl(tmp_path / "types", "Broken.s7dcl", broken)
    db = write_s7dcl(tmp_path, "Probe.s7dcl", STD + PROBE_BODY)
    result = CliRunner().invoke(cli, ["layout", str(db), "--types", str(tmp_path / "types")])
    assert result.exit_code == 0, result.output
    assert "Warning: skipped" in result.output
    assert "Broken.s7dcl" in result.output


def test_table_output_escapes_rich_markup(tmp_path: Path) -> None:
    body = "DATA_BLOCK Zoo\n    VAR\n        x : Array[0..1] of Int;\n    END_VAR\nEND_DATA_BLOCK\n"
    db = write_s7dcl(tmp_path, "Zoo.s7dcl", STD + body)
    result = CliRunner().invoke(cli, ["layout", str(db)])
    assert result.exit_code == 0, result.output
    assert "x[0]" in result.output
    assert "x[1]" in result.output
