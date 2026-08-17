"""`lint` must surface safety findings and gate on them.

A finding reported only to stdout in text mode would be invisible to the
automation most likely to act on it, so `-f json` carries them too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from plc_code.cli import cli


def _fb(name: str, safety: bool, calls: list[str] | None = None) -> str:
    """Build a block in the shape the real corpus uses.

    The attribute pragma block comes BEFORE the ``FUNCTION_BLOCK`` line — that is
    where TIA Portal writes it. A pragma placed after the declaration line reaches
    ``_parse_pragma_or_network``, not ``_parse_block_attributes``, so ``is_safety``
    would silently stay False.
    """
    pragma = '\n    S7_Safety := "True";' if safety else ""
    body = "\n".join(f'            "{c}"();' for c in (calls or [])) or "            #a := FALSE;"
    return f"""{{
    S7_Optimized := "TRUE";{pragma}
}}
FUNCTION_BLOCK "{name}"
    VAR_INPUT
        a : Bool;
    END_VAR
    {{ S7_Language := "SCL" }}
    NETWORK
        REGION Logic
{body}
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def crossing_dir(tmp_path: Path) -> Path:
    """A standard block calling a safety block — one F001."""
    directory = tmp_path / "blocks"
    directory.mkdir()
    (directory / "Caller.s7dcl").write_text(_fb("Caller", safety=False, calls=["FTarget"]), encoding="utf-8")
    (directory / "FTarget.s7dcl").write_text(_fb("FTarget", safety=True), encoding="utf-8")
    return directory


class TestLintReportsSafetyFindings:
    def test_text_output_names_the_code(self, runner: CliRunner, crossing_dir: Path) -> None:
        result = runner.invoke(cli, ["lint", str(crossing_dir)])
        assert "F001" in result.output

    def test_json_carries_project_violations(self, runner: CliRunner, crossing_dir: Path) -> None:
        result = runner.invoke(cli, ["lint", "-f", "json", str(crossing_dir)])
        # Status chatter ("Analyzing N block(s)...") is routed to stderr in JSON
        # mode so it does not corrupt the payload; `result.stdout` is the clean
        # channel, exactly as `test_cli_transpile.py` already relies on for
        # `transpile --check -f json`.
        payload = json.loads(result.stdout)
        codes = [v["rule"] for v in payload["project_violations"]]
        assert "F001" in codes

    def test_exit_code_is_non_zero_on_a_safety_error(self, runner: CliRunner, crossing_dir: Path) -> None:
        result = runner.invoke(cli, ["lint", str(crossing_dir)])
        assert result.exit_code == 1

    def test_clean_project_still_passes(self, runner: CliRunner, tmp_path: Path) -> None:
        directory = tmp_path / "blocks"
        directory.mkdir()
        (directory / "A.s7dcl").write_text(_fb("A", safety=False), encoding="utf-8")
        result = runner.invoke(cli, ["lint", "-f", "json", str(directory)])
        payload = json.loads(result.stdout)
        assert payload["project_violations"] == []
