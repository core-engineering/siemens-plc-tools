"""Tests for the ``plc code transpile`` command.

Two modes:

- bare: print the generated Python. This is the debugging move that found the
  July batch of transpiler defects — being able to read what the block actually
  became.
- ``--check``: report blocks whose generated Python will not load or will raise
  NameError, and exit non-zero so a downstream project can gate on it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from plc_code.cli import cli

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Declares PROC_READY in VAR CONSTANT, then reads it once without the '#'
# prefix — the generated Python leaves a module global nothing defines.
BLOCK_WITH_DEFECT = FIXTURES / "PumpControl.s7dcl"
CLEAN_BLOCK = FIXTURES / "SignalDebounce.s7dcl"

_UNSUPPORTED_SCL = """
FUNCTION_BLOCK "RepeatUser"
    VAR_INPUT
        a : Int;
    END_VAR
    VAR_OUTPUT
        b : Int;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            REPEAT
                #b := #b + 1;
            UNTIL #b > 5
            END_REPEAT;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def unsupported_block(tmp_path: Path) -> Path:
    path = tmp_path / "RepeatUser.s7dcl"
    path.write_text(_UNSUPPORTED_SCL, encoding="utf-8")
    return path


class TestCommandIsRegistered:
    def test_listed_in_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "transpile" in result.output

    def test_has_check_flag(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["transpile", "--help"])
        assert result.exit_code == 0
        assert "--check" in result.output


class TestEmitMode:
    """Bare ``transpile`` prints the generated Python."""

    def test_prints_generated_python(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["transpile", str(CLEAN_BLOCK)])
        assert result.exit_code == 0
        assert "class " in result.output
        assert "def execute" in result.output

    def test_emit_mode_succeeds_on_a_defective_block(self, runner: CliRunner) -> None:
        """Emitting is for reading the output, not judging it."""
        result = runner.invoke(cli, ["transpile", str(BLOCK_WITH_DEFECT)])
        assert result.exit_code == 0

    def test_missing_path_is_an_error(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(cli, ["transpile", str(tmp_path / "nope.s7dcl")])
        assert result.exit_code != 0


class TestCheckMode:
    """``--check`` reports and gates."""

    def test_clean_block_passes(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["transpile", "--check", str(CLEAN_BLOCK)])
        assert result.exit_code == 0

    def test_defective_block_exits_non_zero(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["transpile", "--check", str(BLOCK_WITH_DEFECT)])
        assert result.exit_code == 1

    def test_defective_block_names_the_symbol(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["transpile", "--check", str(BLOCK_WITH_DEFECT)])
        assert "PROC_READY" in result.output

    def test_unsupported_construct_is_reported(self, runner: CliRunner, unsupported_block: Path) -> None:
        result = runner.invoke(cli, ["transpile", "--check", str(unsupported_block)])
        assert result.exit_code == 1
        assert "RepeatUser" in result.output

    def test_directory_scan_reports_per_block(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["transpile", "--check", str(FIXTURES)])
        assert result.exit_code == 1
        assert "PumpControl" in result.output

    def test_check_does_not_print_generated_python(self, runner: CliRunner) -> None:
        """The report is the output; the code would drown it."""
        result = runner.invoke(cli, ["transpile", "--check", str(CLEAN_BLOCK)])
        assert "def execute" not in result.output


class TestJsonOutput:
    def test_clean_block_json_shape(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["transpile", "--check", "-f", "json", str(CLEAN_BLOCK)])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["blocks_checked"] == 1
        assert payload["diagnostics"] == []

    def test_defective_block_json_carries_the_finding(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["transpile", "--check", "-f", "json", str(BLOCK_WITH_DEFECT)])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["blocks_checked"] == 1
        assert len(payload["diagnostics"]) >= 1
        finding = payload["diagnostics"][0]
        assert finding["code"] == "UNDEFINED_NAME"
        assert finding["severity"] == "warning"
        assert finding["block"] == "PumpControl"
        assert "PROC_READY" in finding["message"]
        assert finding["line"] > 0
        assert finding["source"].endswith("PumpControl.s7dcl")

    def test_json_is_the_only_thing_on_stdout(self, runner: CliRunner) -> None:
        """Parseable without stripping a banner."""
        result = runner.invoke(cli, ["transpile", "--check", "-f", "json", str(CLEAN_BLOCK)])
        json.loads(result.output)
