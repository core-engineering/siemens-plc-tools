"""Tests for testing module data models."""

from pathlib import Path

from plc_code.testing.models import (
    BlockTestResult,
    ProjectTestResult,
    TestCaseResult,
)


class TestTestCaseResult:
    """Tests for TestCaseResult dataclass."""

    def test_passed_outcome(self) -> None:
        """Test passed property for passing test."""
        result = TestCaseResult(name="test_foo", outcome="passed", duration=0.1)
        assert result.passed is True
        assert result.failed is False

    def test_failed_outcome(self) -> None:
        """Test failed property for failing test."""
        result = TestCaseResult(
            name="test_bar",
            outcome="failed",
            duration=0.2,
            failure_message="assertion error",
        )
        assert result.passed is False
        assert result.failed is True

    def test_error_outcome(self) -> None:
        """Test error outcome is treated as failed."""
        result = TestCaseResult(name="test_baz", outcome="error", duration=0.0)
        assert result.passed is False
        assert result.failed is True

    def test_skipped_outcome(self) -> None:
        """Test skipped outcome is neither passed nor failed."""
        result = TestCaseResult(name="test_skip", outcome="skipped")
        assert result.passed is False
        assert result.failed is False


class TestBlockTestResult:
    """Tests for BlockTestResult dataclass."""

    def test_block_without_tests(self) -> None:
        """Test block with no test file."""
        result = BlockTestResult(block_name="MyBlock", test_file=None)
        assert result.has_tests is False
        assert result.total == 0
        assert result.passed == 0
        assert result.failed == 0
        assert result.success is False

    def test_block_with_all_passing_tests(self) -> None:
        """Test block with all tests passing."""
        result = BlockTestResult(
            block_name="MyBlock",
            test_file=Path("tests/test_myblock.py"),
            test_results=[
                TestCaseResult(name="test_a", outcome="passed"),
                TestCaseResult(name="test_b", outcome="passed"),
                TestCaseResult(name="test_c", outcome="passed"),
            ],
        )
        assert result.has_tests is True
        assert result.total == 3
        assert result.passed == 3
        assert result.failed == 0
        assert result.skipped == 0
        assert result.success is True
        assert result.failed_tests == []

    def test_block_with_failures(self) -> None:
        """Test block with some failing tests."""
        result = BlockTestResult(
            block_name="MyBlock",
            test_file=Path("tests/test_myblock.py"),
            test_results=[
                TestCaseResult(name="test_a", outcome="passed"),
                TestCaseResult(name="test_b", outcome="failed", failure_message="Error"),
                TestCaseResult(name="test_c", outcome="skipped"),
            ],
        )
        assert result.total == 3
        assert result.passed == 1
        assert result.failed == 1
        assert result.skipped == 1
        assert result.success is False
        assert len(result.failed_tests) == 1
        assert result.failed_tests[0].name == "test_b"

    def test_block_with_empty_test_list(self) -> None:
        """Test block with test file but no tests."""
        result = BlockTestResult(
            block_name="MyBlock",
            test_file=Path("tests/test_myblock.py"),
            test_results=[],
        )
        assert result.has_tests is False
        assert result.success is False


class TestProjectTestResult:
    """Tests for ProjectTestResult dataclass."""

    def test_empty_project(self) -> None:
        """Test project with no blocks."""
        result = ProjectTestResult(block_results=[])
        assert result.total_blocks == 0
        assert result.blocks_tested == 0
        assert result.blocks_untested == 0
        assert result.total_tests == 0
        assert result.coverage_percent == 0.0
        assert result.pass_rate == 0.0
        assert result.overall_success is True

    def test_project_with_tested_and_untested_blocks(self) -> None:
        """Test project with mix of tested and untested blocks."""
        result = ProjectTestResult(
            block_results=[
                BlockTestResult(
                    block_name="TestedBlock",
                    test_file=Path("tests/test_tested.py"),
                    test_results=[
                        TestCaseResult(name="test_a", outcome="passed"),
                        TestCaseResult(name="test_b", outcome="passed"),
                    ],
                ),
                BlockTestResult(
                    block_name="UntestedBlock",
                    test_file=None,
                ),
            ]
        )
        assert result.total_blocks == 2
        assert result.blocks_tested == 1
        assert result.blocks_untested == 1
        assert result.total_tests == 2
        assert result.total_passed == 2
        assert result.total_failed == 0
        assert result.coverage_percent == 50.0
        assert result.pass_rate == 100.0
        assert result.overall_success is True

    def test_project_with_failed_tests(self) -> None:
        """Test project with some failing tests."""
        result = ProjectTestResult(
            block_results=[
                BlockTestResult(
                    block_name="Block1",
                    test_file=Path("tests/test_1.py"),
                    test_results=[
                        TestCaseResult(name="test_a", outcome="passed"),
                        TestCaseResult(name="test_b", outcome="failed"),
                    ],
                ),
                BlockTestResult(
                    block_name="Block2",
                    test_file=Path("tests/test_2.py"),
                    test_results=[
                        TestCaseResult(name="test_c", outcome="passed"),
                    ],
                ),
            ]
        )
        assert result.total_tests == 3
        assert result.total_passed == 2
        assert result.total_failed == 1
        assert result.blocks_passed == 1
        assert result.blocks_failed == 1
        assert result.overall_success is False
        assert result.pass_rate == (2 / 3) * 100

    def test_get_tested_blocks(self) -> None:
        """Test get_tested_blocks method."""
        tested = BlockTestResult(
            block_name="Tested",
            test_file=Path("test.py"),
            test_results=[TestCaseResult(name="test", outcome="passed")],
        )
        untested = BlockTestResult(block_name="Untested", test_file=None)

        result = ProjectTestResult(block_results=[tested, untested])
        tested_blocks = result.get_tested_blocks()

        assert len(tested_blocks) == 1
        assert tested_blocks[0].block_name == "Tested"

    def test_get_untested_blocks(self) -> None:
        """Test get_untested_blocks method."""
        tested = BlockTestResult(
            block_name="Tested",
            test_file=Path("test.py"),
            test_results=[TestCaseResult(name="test", outcome="passed")],
        )
        untested = BlockTestResult(block_name="Untested", test_file=None)

        result = ProjectTestResult(block_results=[tested, untested])
        untested_blocks = result.get_untested_blocks()

        assert len(untested_blocks) == 1
        assert untested_blocks[0].block_name == "Untested"

    def test_get_failed_blocks(self) -> None:
        """Test get_failed_blocks method."""
        passed = BlockTestResult(
            block_name="Passed",
            test_file=Path("test.py"),
            test_results=[TestCaseResult(name="test", outcome="passed")],
        )
        failed = BlockTestResult(
            block_name="Failed",
            test_file=Path("test.py"),
            test_results=[TestCaseResult(name="test", outcome="failed")],
        )

        result = ProjectTestResult(block_results=[passed, failed])
        failed_blocks = result.get_failed_blocks()

        assert len(failed_blocks) == 1
        assert failed_blocks[0].block_name == "Failed"
