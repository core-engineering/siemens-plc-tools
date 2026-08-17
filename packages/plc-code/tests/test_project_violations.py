"""Project-level findings must count, or the gate cannot see them.

`ProjectAnalysisResult` derived every aggregate from `block_results`, so a
finding that belongs to the project rather than to one block had nowhere to
live. `fail_on_error` reads `passed`, so a safety error that does not reach
`total_errors` is a finding nobody gates on.
"""

from __future__ import annotations

from pathlib import Path

from plc_code.analyzer.quality.models import (
    BlockAnalysisResult,
    ProjectAnalysisResult,
    Severity,
    Violation,
)


def _violation(code: str, severity: Severity) -> Violation:
    return Violation(rule_code=code, message="x", severity=severity)


class TestProjectViolationsCount:
    def test_a_project_error_makes_the_result_fail(self) -> None:
        """The test that proves the gate works. Fails before this task."""
        result = ProjectAnalysisResult(project_violations=[_violation("F001", Severity.ERROR)])
        assert result.total_errors == 1
        assert result.passed is False

    def test_a_project_warning_is_counted(self) -> None:
        result = ProjectAnalysisResult(project_violations=[_violation("F003", Severity.WARNING)])
        assert result.total_warnings == 1
        assert result.passed is True

    def test_project_and_block_errors_add_up(self) -> None:
        block = BlockAnalysisResult(block_name="B", block_type="FUNCTION_BLOCK", source_file=Path("B.s7dcl"))
        block.violations.append(_violation("N001", Severity.ERROR))
        result = ProjectAnalysisResult(
            block_results=[block],
            project_violations=[_violation("F001", Severity.ERROR)],
        )
        assert result.total_errors == 2

    def test_rule_counts_include_project_violations(self) -> None:
        result = ProjectAnalysisResult(
            project_violations=[
                _violation("F001", Severity.ERROR),
                _violation("F001", Severity.ERROR),
                _violation("F003", Severity.WARNING),
            ]
        )
        assert result.get_violations_by_rule() == {"F001": 2, "F003": 1}

    def test_block_counts_are_unaffected(self) -> None:
        """blocks_with_errors and blocks_passed count blocks, not findings."""
        result = ProjectAnalysisResult(project_violations=[_violation("F001", Severity.ERROR)])
        assert result.blocks_with_errors == 0
        assert result.blocks_passed == 0

    def test_default_is_empty(self) -> None:
        assert ProjectAnalysisResult().project_violations == []


class TestBackwardCompatibility:
    def test_analyze_blocks_without_sources_runs_no_project_checks(self) -> None:
        """The two existing call sites pass no paths and must be unaffected."""
        from pathlib import Path

        from plc_code.analyzer.quality.runner import AnalysisRunner
        from plc_code.parser import parse_scl_file

        fixtures = Path(__file__).resolve().parent / "fixtures"
        blocks = [
            b for p in sorted(fixtures.glob("*.s7dcl")) if (b := parse_scl_file(p)) is not None and b.name
        ]
        result = AnalysisRunner().analyze_blocks(blocks)
        assert result.project_violations == []
