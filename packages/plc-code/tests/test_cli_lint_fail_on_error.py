"""`code.quality.fail_on_error` must actually reach the exit code.

The key was parsed into `QualityConfig`, documented in `CLAUDE.md`, written into
the generated `plc.yaml` template, and set to `false` by the bundled example
project with the comment "Report findings without failing the example" — while
`lint` ended in an unconditional ``SystemExit(0 if result.passed else 1)`` and
read the key nowhere. The configuration surface promised something the tool did
not do.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from plc_code.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


#: A block with no "Block info header" REGION, which trips D001 at ERROR severity.
#: Every shipped fixture is clean enough to pass, so the gate cannot be exercised
#: with one — a project that produces only warnings exits 0 either way and the test
#: would prove nothing.
_BLOCK_WITHOUT_HEADER = """{
    S7_Optimized := "TRUE"
}
FUNCTION_BLOCK "NoHeader"
    VAR_INPUT
        a : Bool;
    END_VAR
    VAR_OUTPUT
        b : Bool;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            #b := #a;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


def _project(tmp_path: Path, *, fail_on_error: bool) -> Path:
    """Build a project whose block produces a quality error.

    Returns
    -------
    Path
        The project root, holding a `plc.yaml` and one source directory.
    """
    root = tmp_path / "proj"
    source = root / "program-blocks"
    source.mkdir(parents=True)
    (source / "NoHeader.s7dcl").write_text(_BLOCK_WITHOUT_HEADER, encoding="utf-8")
    (root / "plc.yaml").write_text(
        "project:\n"
        '  name: "Gate Test"\n'
        '  code: "GT"\n'
        "code:\n"
        "  paths:\n"
        "    source: program-blocks\n"
        "  quality:\n"
        "    enabled: true\n"
        f"    fail_on_error: {str(fail_on_error).lower()}\n",
        encoding="utf-8",
    )
    return root


class TestFailOnErrorReachesTheExitCode:
    def test_true_still_fails(self, runner: CliRunner, tmp_path: Path, monkeypatch) -> None:
        root = _project(tmp_path, fail_on_error=True)
        monkeypatch.chdir(root)
        result = runner.invoke(cli, ["lint"])
        assert result.exit_code == 1, result.output

    def test_false_exits_zero(self, runner: CliRunner, tmp_path: Path, monkeypatch) -> None:
        root = _project(tmp_path, fail_on_error=False)
        monkeypatch.chdir(root)
        result = runner.invoke(cli, ["lint"])
        assert result.exit_code == 0, result.output

    def test_findings_are_still_reported_when_the_gate_is_off(
        self, runner: CliRunner, tmp_path: Path, monkeypatch
    ) -> None:
        """Turning the gate off must not silence the report."""
        root = _project(tmp_path, fail_on_error=False)
        monkeypatch.chdir(root)
        result = runner.invoke(cli, ["lint"])
        assert "Analyzing" in result.output

    def test_an_explicit_path_keeps_the_strict_default(
        self, runner: CliRunner, tmp_path: Path, monkeypatch
    ) -> None:
        """`lint <path>` never loads plc.yaml, so it cannot be softened by one.

        Same rule as `safety_path_pattern`: the explicit-path route reads no
        configuration at all, and this key must not be the exception.
        """
        root = _project(tmp_path, fail_on_error=False)
        monkeypatch.chdir(root)
        result = runner.invoke(cli, ["lint", str(root / "program-blocks")])
        assert result.exit_code == 1, result.output
