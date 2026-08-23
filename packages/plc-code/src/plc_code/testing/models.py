"""Data models for test execution and results.

This module defines the data structures used to represent test results,
including individual test cases, block-level results, and project-wide statistics.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TestCaseResult:
    """Result of a single test function.

    Attributes
    ----------
    name : str
        Test function name (e.g., "test_no_alarm_to_alarm_on_trigger").
    outcome : str
        Test outcome: "passed", "failed", "skipped", or "error".
    duration : float
        Test execution time in seconds.
    failure_message : str
        Error message for failed tests.
    class_name : str
        Test class name, if applicable.
    """

    __test__ = False  # a result/config model, not a pytest test class

    name: str
    outcome: str
    duration: float = 0.0
    failure_message: str = ""
    class_name: str = ""

    @property
    def passed(self) -> bool:
        """Returns True if test passed."""
        return self.outcome == "passed"

    @property
    def failed(self) -> bool:
        """Returns True if test failed."""
        return self.outcome in ("failed", "error")


@dataclass
class BlockTestResult:
    """Test results for a single block.

    Attributes
    ----------
    block_name : str
        Name of the SCL block (e.g., "MotorStarter").
    test_file : Path | None
        Path to the test file, or None if no tests exist.
    test_results : list[TestCaseResult]
        Results for each test case.
    execution_time : float
        Total execution time for all tests in seconds.
    """

    block_name: str
    test_file: Path | None = None
    test_results: list[TestCaseResult] = field(default_factory=list)
    execution_time: float = 0.0

    @property
    def total(self) -> int:
        """Total number of tests."""
        return len(self.test_results)

    @property
    def passed(self) -> int:
        """Number of passed tests."""
        return sum(1 for t in self.test_results if t.outcome == "passed")

    @property
    def failed(self) -> int:
        """Number of failed tests."""
        return sum(1 for t in self.test_results if t.outcome in ("failed", "error"))

    @property
    def skipped(self) -> int:
        """Number of skipped tests."""
        return sum(1 for t in self.test_results if t.outcome == "skipped")

    @property
    def has_tests(self) -> bool:
        """Returns True if block has associated tests."""
        return self.test_file is not None and self.total > 0

    @property
    def success(self) -> bool:
        """Returns True if all tests passed (and there are tests)."""
        return self.has_tests and self.failed == 0

    @property
    def failed_tests(self) -> list[TestCaseResult]:
        """Get list of failed test cases."""
        return [t for t in self.test_results if t.failed]


@dataclass
class ProjectTestResult:
    """Aggregated test results for all blocks.

    Attributes
    ----------
    block_results : list[BlockTestResult]
        Results for all analyzed blocks.
    """

    block_results: list[BlockTestResult] = field(default_factory=list)

    @property
    def total_blocks(self) -> int:
        """Total number of blocks in the project."""
        return len(self.block_results)

    @property
    def blocks_tested(self) -> int:
        """Number of blocks with tests."""
        return sum(1 for r in self.block_results if r.has_tests)

    @property
    def blocks_untested(self) -> int:
        """Number of blocks without tests."""
        return sum(1 for r in self.block_results if not r.has_tests)

    @property
    def blocks_passed(self) -> int:
        """Number of blocks where all tests passed."""
        return sum(1 for r in self.block_results if r.success)

    @property
    def blocks_failed(self) -> int:
        """Number of blocks with failing tests."""
        return sum(1 for r in self.block_results if r.has_tests and not r.success)

    @property
    def total_tests(self) -> int:
        """Total number of tests across all blocks."""
        return sum(r.total for r in self.block_results)

    @property
    def total_passed(self) -> int:
        """Total number of passed tests."""
        return sum(r.passed for r in self.block_results)

    @property
    def total_failed(self) -> int:
        """Total number of failed tests."""
        return sum(r.failed for r in self.block_results)

    @property
    def total_skipped(self) -> int:
        """Total number of skipped tests."""
        return sum(r.skipped for r in self.block_results)

    @property
    def overall_success(self) -> bool:
        """Returns True if all tests passed across all blocks."""
        return self.total_failed == 0

    @property
    def coverage_percent(self) -> float:
        """Test coverage as percentage of blocks with tests."""
        if self.total_blocks == 0:
            return 0.0
        return (self.blocks_tested / self.total_blocks) * 100

    @property
    def pass_rate(self) -> float:
        """Pass rate as percentage of tests that passed."""
        if self.total_tests == 0:
            return 0.0
        return (self.total_passed / self.total_tests) * 100

    def get_tested_blocks(self) -> list[BlockTestResult]:
        """Get blocks that have tests.

        Returns
        -------
        list[BlockTestResult]
            Blocks with associated test files.
        """
        return [r for r in self.block_results if r.has_tests]

    def get_untested_blocks(self) -> list[BlockTestResult]:
        """Get blocks without tests.

        Returns
        -------
        list[BlockTestResult]
            Blocks without associated test files.
        """
        return [r for r in self.block_results if not r.has_tests]

    def get_failed_blocks(self) -> list[BlockTestResult]:
        """Get blocks with failing tests.

        Returns
        -------
        list[BlockTestResult]
            Blocks where at least one test failed.
        """
        return [r for r in self.block_results if r.has_tests and not r.success]
