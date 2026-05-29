"""Tests for testing module reporter."""

from pathlib import Path

from plc_code.testing.models import (
    BlockTestResult,
    ProjectTestResult,
    TestCaseResult,
)
from plc_code.testing.reporter import TestReporter


class TestTestReporterBadge:
    """Tests for badge generation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.reporter = TestReporter()

    def test_badge_no_tests(self) -> None:
        """Test badge for block with no tests."""
        result = BlockTestResult(block_name="NoTests", test_file=None)
        badge = self.reporter.generate_block_badge(result)
        assert "No tests" in badge
        assert ":white_circle:" in badge

    def test_badge_all_passed(self) -> None:
        """Test badge for block with all tests passing."""
        result = BlockTestResult(
            block_name="AllPass",
            test_file=Path("test.py"),
            test_results=[
                TestCaseResult(name="test_a", outcome="passed"),
                TestCaseResult(name="test_b", outcome="passed"),
            ],
        )
        badge = self.reporter.generate_block_badge(result)
        assert ":white_check_mark:" in badge
        assert "2/2 passed" in badge

    def test_badge_some_failed(self) -> None:
        """Test badge for block with failures."""
        result = BlockTestResult(
            block_name="SomeFail",
            test_file=Path("test.py"),
            test_results=[
                TestCaseResult(name="test_a", outcome="passed"),
                TestCaseResult(name="test_b", outcome="failed"),
            ],
        )
        badge = self.reporter.generate_block_badge(result)
        assert ":x:" in badge
        assert "1/2 passed" in badge
        assert "1 failed" in badge


class TestTestReporterBlockSection:
    """Tests for block section generation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.reporter = TestReporter()

    def test_section_empty_for_no_tests(self) -> None:
        """Test section is empty for block without tests."""
        result = BlockTestResult(block_name="NoTests", test_file=None)
        section = self.reporter.generate_block_section(result)
        assert section == ""

    def test_section_includes_test_file(self) -> None:
        """Test section includes test file path."""
        result = BlockTestResult(
            block_name="Block",
            test_file=Path("tests/test_block.py"),
            test_results=[TestCaseResult(name="test_a", outcome="passed")],
        )
        section = self.reporter.generate_block_section(result)
        assert "test_block.py" in section

    def test_section_includes_failed_tests(self) -> None:
        """Test section includes failed test details."""
        result = BlockTestResult(
            block_name="Block",
            test_file=Path("test.py"),
            test_results=[
                TestCaseResult(
                    name="test_failure",
                    outcome="failed",
                    failure_message="assertion error",
                )
            ],
        )
        section = self.reporter.generate_block_section(result)
        assert "Failed Tests" in section
        assert "test_failure" in section
        assert "assertion error" in section

    def test_section_includes_summary_table(self) -> None:
        """Test section includes summary metrics table."""
        result = BlockTestResult(
            block_name="Block",
            test_file=Path("test.py"),
            test_results=[
                TestCaseResult(name="test_a", outcome="passed"),
                TestCaseResult(name="test_b", outcome="failed"),
                TestCaseResult(name="test_c", outcome="skipped"),
            ],
        )
        section = self.reporter.generate_block_section(result)
        assert "| Passed | Failed | Skipped | Total |" in section


class TestTestReporterSummaryPage:
    """Tests for summary page generation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.reporter = TestReporter()

    def test_summary_no_tests(self) -> None:
        """Test summary page for project with no tests."""
        result = ProjectTestResult(block_results=[])
        summary = self.reporter.generate_summary_page(result)
        assert "No Tests Found" in summary

    def test_summary_all_passed(self) -> None:
        """Test summary page when all tests pass."""
        result = ProjectTestResult(
            block_results=[
                BlockTestResult(
                    block_name="Block1",
                    test_file=Path("test.py"),
                    test_results=[TestCaseResult(name="test", outcome="passed")],
                )
            ]
        )
        summary = self.reporter.generate_summary_page(result)
        assert "All Tests Passed" in summary

    def test_summary_with_failures(self) -> None:
        """Test summary page includes failure indicator."""
        result = ProjectTestResult(
            block_results=[
                BlockTestResult(
                    block_name="Block1",
                    test_file=Path("test.py"),
                    test_results=[TestCaseResult(name="test", outcome="failed")],
                )
            ]
        )
        summary = self.reporter.generate_summary_page(result)
        assert "Tests Failed" in summary

    def test_summary_includes_overview_table(self) -> None:
        """Test summary includes overview metrics."""
        result = ProjectTestResult(
            block_results=[
                BlockTestResult(
                    block_name="Tested",
                    test_file=Path("test.py"),
                    test_results=[TestCaseResult(name="test", outcome="passed")],
                ),
                BlockTestResult(block_name="Untested", test_file=None),
            ]
        )
        summary = self.reporter.generate_summary_page(result)
        assert "Blocks with tests" in summary
        assert "Blocks without tests" in summary
        assert "Test coverage" in summary

    def test_summary_includes_block_links(self) -> None:
        """Test summary includes links to block docs."""
        result = ProjectTestResult(
            block_results=[
                BlockTestResult(
                    block_name="MyBlock",
                    test_file=Path("test.py"),
                    test_results=[TestCaseResult(name="test", outcome="passed")],
                )
            ]
        )
        block_paths = {"MyBlock": "../blocks/MyBlock.md"}
        summary = self.reporter.generate_summary_page(result, block_paths)
        assert "[MyBlock](../blocks/MyBlock.md)" in summary

    def test_summary_untested_blocks_section(self) -> None:
        """Test summary includes untested blocks list."""
        result = ProjectTestResult(
            block_results=[BlockTestResult(block_name="UntestedBlock", test_file=None)]
        )
        summary = self.reporter.generate_summary_page(result)
        assert "Untested Blocks" in summary
        assert "UntestedBlock" in summary

    def test_summary_failed_tests_section(self) -> None:
        """Test summary includes failed tests details."""
        result = ProjectTestResult(
            block_results=[
                BlockTestResult(
                    block_name="FailedBlock",
                    test_file=Path("test.py"),
                    test_results=[
                        TestCaseResult(
                            name="test_fail",
                            outcome="failed",
                            failure_message="Error occurred",
                        )
                    ],
                )
            ]
        )
        summary = self.reporter.generate_summary_page(result)
        assert "Failed Tests" in summary
        assert "test_fail" in summary


class TestTestReporterCoveragePage:
    """Tests for coverage page generation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.reporter = TestReporter()

    def test_coverage_basic(self) -> None:
        """Test basic coverage page generation."""
        result = ProjectTestResult(
            block_results=[
                BlockTestResult(
                    block_name="Tested",
                    test_file=Path("test.py"),
                    test_results=[TestCaseResult(name="test", outcome="passed")],
                ),
                BlockTestResult(block_name="Untested", test_file=None),
            ]
        )
        coverage = self.reporter.generate_coverage_page(result)
        assert "Test Coverage" in coverage
        assert "50.0%" in coverage

    def test_coverage_with_categories(self) -> None:
        """Test coverage page with category breakdown."""
        result = ProjectTestResult(
            block_results=[
                BlockTestResult(
                    block_name="Block1",
                    test_file=Path("test.py"),
                    test_results=[TestCaseResult(name="test", outcome="passed")],
                ),
                BlockTestResult(block_name="Block2", test_file=None),
            ]
        )
        categories = {
            "Category1": ["Block1"],
            "Category2": ["Block2"],
        }
        coverage = self.reporter.generate_coverage_page(result, categories)
        assert "Coverage by Category" in coverage
        assert "Category1" in coverage
        assert "Category2" in coverage

    def test_coverage_visual_bar(self) -> None:
        """Test coverage page includes visual bar."""
        result = ProjectTestResult(block_results=[])
        coverage = self.reporter.generate_coverage_page(result)
        # Should have filled (█) and empty (░) characters
        assert "█" in coverage or "░" in coverage
