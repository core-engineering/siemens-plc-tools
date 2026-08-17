"""`plc code trace -f json` must emit a parseable document.

The command wrote its status line, its per-file parse warnings and, on failure,
a full traceback to the same stdout its JSON payload goes to. Any project with
one unreadable block therefore produced output that `json.load` rejected at
character 0 — silently, because the command still exited 0.

`lint` and `transpile --check` had the same defect and fixed it the same way, by
sending diagnostics to a stderr `Console` whenever the format is JSON. These
tests pin that behaviour for `trace` so the third instance does not come back.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from plc_code.cli import cli

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project_with_a_bad_block(tmp_path: Path) -> Path:
    """A directory holding one analysable block and one the parser cannot read.

    The unreadable block is what triggers the warning that used to corrupt the
    payload; without it the bug is invisible. The good block must actually yield
    output dependencies, or the command short-circuits before emitting anything
    and the tests pass on an empty stdout — `SignalDebounce` produces none.
    """
    directory = tmp_path / "blocks"
    directory.mkdir()
    (directory / "Good.s7dcl").write_text(
        (FIXTURES / "MotorStarter.s7dcl").read_text(encoding="utf-8-sig"),
        encoding="utf-8",
    )
    (directory / "Bad.s7dcl").write_text("FUNCTION_BLOCK \nthis is not valid SCL at all\n", encoding="utf-8")
    return directory


class TestTraceJsonIsParseable:
    def test_stdout_is_valid_json(self, runner: CliRunner, project_with_a_bad_block: Path) -> None:
        result = runner.invoke(cli, ["trace", "-f", "json", str(project_with_a_bad_block)])
        json.loads(result.stdout)

    def test_stdout_starts_at_the_payload(self, runner: CliRunner, project_with_a_bad_block: Path) -> None:
        """No status line ahead of the document."""
        result = runner.invoke(cli, ["trace", "-f", "json", str(project_with_a_bad_block)])
        assert result.stdout.lstrip().startswith("{")

    def test_the_status_line_is_not_on_stdout(
        self, runner: CliRunner, project_with_a_bad_block: Path
    ) -> None:
        assert (
            "Analyzing"
            not in runner.invoke(cli, ["trace", "-f", "json", str(project_with_a_bad_block)]).stdout
        )

    def test_the_parse_warning_is_not_on_stdout(
        self, runner: CliRunner, project_with_a_bad_block: Path
    ) -> None:
        """The warning must still be reported — just not into the payload."""
        assert (
            "Warning" not in runner.invoke(cli, ["trace", "-f", "json", str(project_with_a_bad_block)]).stdout
        )


class TestTraceTextIsUnchanged:
    def test_text_format_still_prints_diagnostics_to_stdout(
        self, runner: CliRunner, project_with_a_bad_block: Path
    ) -> None:
        """Only JSON mode reroutes; the human-facing default keeps one stream."""
        result = runner.invoke(cli, ["trace", str(project_with_a_bad_block)])
        assert "Analyzing" in result.stdout
