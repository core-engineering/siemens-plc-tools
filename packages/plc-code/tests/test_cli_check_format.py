"""`plc code check-format` exit codes and output formats."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from s7dcl_helpers import write_s7dcl
from test_formatcheck_checks import FB

from plc_code.cli import cli


def test_clean_workspace_exits_zero(tmp_path: Path) -> None:
    write_s7dcl(tmp_path, "Probe.s7dcl", FB)
    result = CliRunner().invoke(cli, ["check-format", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "1 file" in result.output and "0 errors" in result.output


def test_error_exits_one_and_names_the_code(tmp_path: Path) -> None:
    write_s7dcl(tmp_path, "Probe.s7dcl", FB, bom=False)
    result = CliRunner().invoke(cli, ["check-format", str(tmp_path)])
    assert result.exit_code == 1
    assert "F001" in result.output and "Probe.s7dcl" in result.output


def test_warning_only_exits_zero(tmp_path: Path) -> None:
    write_s7dcl(tmp_path, "Probe.s7dcl", FB.replace('    S7_Optimized := "TRUE";\n', ""))
    result = CliRunner().invoke(cli, ["check-format", str(tmp_path)])
    assert result.exit_code == 0
    assert "F021" in result.output


def test_json_output_is_parseable(tmp_path: Path) -> None:
    write_s7dcl(tmp_path, "Probe.s7dcl", FB, bom=False)
    result = CliRunner().invoke(cli, ["check-format", "--format", "json", str(tmp_path)])
    payload = json.loads(result.output)
    assert payload["files"] == 1 and payload["errors"] == 1 and payload["warnings"] == 0
    assert payload["findings"][0]["code"] == "F001"
    assert payload["findings"][0]["line"] is None


def test_text_output_escapes_rich_markup(tmp_path: Path) -> None:
    write_s7dcl(tmp_path, "Pro[be].s7dcl", FB)
    result = CliRunner().invoke(cli, ["check-format", str(tmp_path)])
    assert result.exit_code == 1
    assert "Pro[be]" in result.output


def test_unexpected_error_is_reported_and_exits_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_s7dcl(tmp_path, "Probe.s7dcl", FB)

    def _boom(path: Path) -> None:
        raise RuntimeError("disk exploded")

    monkeypatch.setattr("plc_code.formatcheck.check_path", _boom)
    result = CliRunner().invoke(cli, ["check-format", str(tmp_path)])
    assert result.exit_code == 1
    assert "disk exploded" in result.output
