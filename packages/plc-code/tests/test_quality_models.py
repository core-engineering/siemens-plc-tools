"""Tests for quality analysis data models."""

from plc_code.analyzer.quality.models import (
    BlockAnalysisResult,
    ProjectAnalysisResult,
    RuleCategory,
    RuleInfo,
    Severity,
    Violation,
)


class TestSeverity:
    """Tests for Severity enum."""

    def test_severity_values(self) -> None:
        """Test severity enum values."""
        assert Severity.ERROR.value == "error"
        assert Severity.WARNING.value == "warning"
        assert Severity.INFO.value == "info"


class TestRuleCategory:
    """Tests for RuleCategory enum."""

    def test_category_values(self) -> None:
        """Test category enum values."""
        assert RuleCategory.NAMING.value == "N"
        assert RuleCategory.COMPLEXITY.value == "C"
        assert RuleCategory.DOCUMENTATION.value == "D"
        assert RuleCategory.BEST_PRACTICES.value == "B"
        assert RuleCategory.STRUCTURE.value == "S"


class TestViolation:
    """Tests for Violation dataclass."""

    def test_basic_violation(self) -> None:
        """Test creating a basic violation."""
        v = Violation(
            rule_code="N001",
            message="Variable should use camelCase",
            severity=Severity.WARNING,
        )
        assert v.rule_code == "N001"
        assert v.message == "Variable should use camelCase"
        assert v.severity == Severity.WARNING
        assert v.line_number == 0
        assert v.context == ""
        assert v.suggestion == ""

    def test_violation_with_details(self) -> None:
        """Test violation with all fields populated."""
        v = Violation(
            rule_code="D001",
            message="Missing header",
            severity=Severity.ERROR,
            line_number=10,
            column=5,
            context="MyBlock",
            suggestion="Add a header region",
        )
        assert v.line_number == 10
        assert v.column == 5
        assert v.context == "MyBlock"
        assert v.suggestion == "Add a header region"


class TestRuleInfo:
    """Tests for RuleInfo dataclass."""

    def test_basic_rule_info(self) -> None:
        """Test creating basic rule info."""
        info = RuleInfo(
            code="N001",
            name="variable-camel-case",
            description="Variables must use camelCase",
            severity=Severity.WARNING,
            category=RuleCategory.NAMING,
        )
        assert info.code == "N001"
        assert info.name == "variable-camel-case"
        assert info.severity == Severity.WARNING
        assert info.category == RuleCategory.NAMING
        assert info.rationale == ""
        assert info.examples_bad == []
        assert info.examples_good == []


class TestBlockAnalysisResult:
    """Tests for BlockAnalysisResult dataclass."""

    def test_empty_result(self) -> None:
        """Test analysis result with no violations."""
        from pathlib import Path

        result = BlockAnalysisResult(
            block_name="TestBlock",
            block_type="FUNCTION_BLOCK",
            source_file=Path("test.s7dcl"),
        )
        assert result.block_name == "TestBlock"
        assert result.violations == []
        assert result.error_count == 0
        assert result.warning_count == 0
        assert result.info_count == 0
        assert result.passed is True

    def test_result_with_violations(self) -> None:
        """Test result with various violations."""
        from pathlib import Path

        result = BlockAnalysisResult(
            block_name="TestBlock",
            block_type="FUNCTION_BLOCK",
            source_file=Path("test.s7dcl"),
            violations=[
                Violation(rule_code="D001", message="Error", severity=Severity.ERROR),
                Violation(rule_code="N001", message="Warning", severity=Severity.WARNING),
                Violation(rule_code="N002", message="Warning2", severity=Severity.WARNING),
                Violation(rule_code="B001", message="Info", severity=Severity.INFO),
            ],
        )
        assert result.error_count == 1
        assert result.warning_count == 2
        assert result.info_count == 1
        assert result.passed is False  # Has errors

    def test_passed_with_warnings_only(self) -> None:
        """Test that result passes if only warnings/info."""
        from pathlib import Path

        result = BlockAnalysisResult(
            block_name="TestBlock",
            block_type="FUNCTION",
            source_file=Path("test.s7dcl"),
            violations=[
                Violation(rule_code="N001", message="Warning", severity=Severity.WARNING),
                Violation(rule_code="B001", message="Info", severity=Severity.INFO),
            ],
        )
        assert result.passed is True


class TestProjectAnalysisResult:
    """Tests for ProjectAnalysisResult dataclass."""

    def test_empty_project_result(self) -> None:
        """Test empty project analysis result."""
        result = ProjectAnalysisResult()
        assert result.block_results == []
        assert result.total_errors == 0
        assert result.total_warnings == 0
        assert result.total_info == 0
        assert result.passed is True
        assert result.blocks_passed == 0

    def test_project_with_blocks(self) -> None:
        """Test project result with multiple blocks."""
        from pathlib import Path

        block1 = BlockAnalysisResult(
            block_name="Block1",
            block_type="FUNCTION_BLOCK",
            source_file=Path("block1.s7dcl"),
            violations=[
                Violation(rule_code="D001", message="Error", severity=Severity.ERROR),
            ],
        )
        block2 = BlockAnalysisResult(
            block_name="Block2",
            block_type="FUNCTION",
            source_file=Path("block2.s7dcl"),
            violations=[
                Violation(rule_code="N001", message="Warning", severity=Severity.WARNING),
            ],
        )
        block3 = BlockAnalysisResult(
            block_name="Block3",
            block_type="TYPE",
            source_file=Path("block3.s7dcl"),
        )

        result = ProjectAnalysisResult(block_results=[block1, block2, block3])
        assert result.total_errors == 1
        assert result.total_warnings == 1
        assert result.total_info == 0
        assert result.passed is False
        assert result.blocks_passed == 2  # block2 and block3 pass

    def test_violations_by_rule(self) -> None:
        """Test getting violations grouped by rule."""
        from pathlib import Path

        block1 = BlockAnalysisResult(
            block_name="Block1",
            block_type="FUNCTION_BLOCK",
            source_file=Path("block1.s7dcl"),
            violations=[
                Violation(rule_code="N001", message="V1", severity=Severity.WARNING),
                Violation(rule_code="N001", message="V2", severity=Severity.WARNING),
                Violation(rule_code="D001", message="V3", severity=Severity.ERROR),
            ],
        )
        block2 = BlockAnalysisResult(
            block_name="Block2",
            block_type="FUNCTION",
            source_file=Path("block2.s7dcl"),
            violations=[
                Violation(rule_code="N001", message="V4", severity=Severity.WARNING),
            ],
        )

        result = ProjectAnalysisResult(block_results=[block1, block2])
        by_rule = result.get_violations_by_rule()

        assert by_rule["N001"] == 3
        assert by_rule["D001"] == 1
