"""Test runner for executing pytest and collecting results.

This module provides functionality for running pytest against test files
and parsing the results into structured data models.
"""

import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from plc_code.testing.discovery import discover_test_file
from plc_code.testing.models import BlockTestResult, ProjectTestResult, TestCaseResult


class TestRunner:
    """Executes pytest and collects test results.

    Parameters
    ----------
    test_dirs : list[Path]
        Directories to search for test files.
    timeout : int
        Maximum time in seconds for test execution per file.
    """

    def __init__(
        self,
        test_dirs: list[Path] | None = None,
        timeout: int = 300,
    ) -> None:
        """Initialize the test runner.

        Parameters
        ----------
        test_dirs : list[Path] | None
            Directories to search for test files.
        timeout : int
            Maximum time in seconds for test execution.
        """
        self.test_dirs = test_dirs or [Path("test-cases")]
        self.timeout = timeout

    def run_tests_for_block(
        self,
        block_name: str,
        test_file: Path | None = None,
    ) -> BlockTestResult:
        """Run tests for a single block.

        Parameters
        ----------
        block_name : str
            Name of the SCL block.
        test_file : Path | None
            Path to the test file. If None, discovery is attempted.

        Returns
        -------
        BlockTestResult
            Test results for the block.
        """
        # Discover test file if not provided
        if test_file is None:
            test_file = discover_test_file(block_name, self.test_dirs)

        if test_file is None or not test_file.exists():
            return BlockTestResult(block_name=block_name, test_file=None)

        # Run pytest and collect results
        test_results, execution_time = self._run_pytest(test_file)

        return BlockTestResult(
            block_name=block_name,
            test_file=test_file,
            test_results=test_results,
            execution_time=execution_time,
        )

    def run_tests_for_blocks(
        self,
        block_names: list[str],
        test_registry: dict[str, Path] | None = None,
    ) -> ProjectTestResult:
        """Run tests for multiple blocks.

        Parameters
        ----------
        block_names : list[str]
            Names of all blocks to test.
        test_registry : dict[str, Path] | None
            Pre-built mapping of block names to test files.

        Returns
        -------
        ProjectTestResult
            Aggregated test results.
        """
        block_results: list[BlockTestResult] = []

        for block_name in block_names:
            test_file = test_registry.get(block_name) if test_registry else None
            result = self.run_tests_for_block(block_name, test_file)
            block_results.append(result)

        return ProjectTestResult(block_results=block_results)

    def run_all_tests(
        self,
        test_registry: dict[str, Path],
    ) -> dict[str, BlockTestResult]:
        """Run all tests in the registry.

        Parameters
        ----------
        test_registry : dict[str, Path]
            Mapping of block names to test files.

        Returns
        -------
        dict[str, BlockTestResult]
            Mapping of block names to their test results.
        """
        results: dict[str, BlockTestResult] = {}

        # Group by test file to avoid running the same file multiple times
        file_to_blocks: dict[Path, list[str]] = {}
        for block_name, test_file in test_registry.items():
            if test_file not in file_to_blocks:
                file_to_blocks[test_file] = []
            file_to_blocks[test_file].append(block_name)

        for test_file, block_names in file_to_blocks.items():
            test_results, execution_time = self._run_pytest(test_file)

            # Create result for each block (they share the same test file)
            for block_name in block_names:
                results[block_name] = BlockTestResult(
                    block_name=block_name,
                    test_file=test_file,
                    test_results=test_results,
                    execution_time=execution_time,
                )

        return results

    def _run_pytest(
        self,
        test_file: Path,
    ) -> tuple[list[TestCaseResult], float]:
        """Run pytest on a test file and parse results.

        Parameters
        ----------
        test_file : Path
            Path to the test file.

        Returns
        -------
        tuple[list[TestCaseResult], float]
            Test case results and total execution time.
        """
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
            xml_path = Path(tmp.name)

        try:
            # Run pytest with JUnit XML output
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "pytest",
                    str(test_file),
                    f"--junit-xml={xml_path}",
                    "-v",
                    "--tb=short",
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=test_file.parent.parent,  # Run from project root
            )

            # Parse results regardless of exit code (non-zero means failures)
            if xml_path.exists():
                return self._parse_junit_xml(xml_path)

            # If no XML, return error result
            return [
                TestCaseResult(
                    name="pytest_execution",
                    outcome="error",
                    failure_message=f"pytest failed: {result.stderr}",
                )
            ], 0.0

        except subprocess.TimeoutExpired:
            return [
                TestCaseResult(
                    name="pytest_execution",
                    outcome="error",
                    failure_message=f"Test execution timed out after {self.timeout}s",
                )
            ], float(self.timeout)

        except Exception as e:
            return [
                TestCaseResult(
                    name="pytest_execution",
                    outcome="error",
                    failure_message=str(e),
                )
            ], 0.0

        finally:
            # Clean up temp file
            if xml_path.exists():
                xml_path.unlink()

    def _parse_junit_xml(
        self,
        xml_path: Path,
    ) -> tuple[list[TestCaseResult], float]:
        """Parse JUnit XML output from pytest.

        Parameters
        ----------
        xml_path : Path
            Path to the JUnit XML file.

        Returns
        -------
        tuple[list[TestCaseResult], float]
            Parsed test results and total execution time.
        """
        test_results: list[TestCaseResult] = []
        total_time = 0.0

        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()

            # Get total time from testsuite
            for testsuite in root.iter("testsuite"):
                time_str = testsuite.get("time", "0")
                total_time = float(time_str)

            # Parse each test case
            for testcase in root.iter("testcase"):
                name = testcase.get("name", "unknown")
                classname = testcase.get("classname", "")
                time_str = testcase.get("time", "0")
                duration = float(time_str)

                # Determine outcome
                outcome = "passed"
                failure_message = ""

                # Check for failure
                failure = testcase.find("failure")
                if failure is not None:
                    outcome = "failed"
                    failure_message = failure.get("message", "")
                    if failure.text:
                        failure_message = f"{failure_message}\n{failure.text}".strip()

                # Check for error
                error = testcase.find("error")
                if error is not None:
                    outcome = "error"
                    failure_message = error.get("message", "")
                    if error.text:
                        failure_message = f"{failure_message}\n{error.text}".strip()

                # Check for skip
                skipped = testcase.find("skipped")
                if skipped is not None:
                    outcome = "skipped"
                    failure_message = skipped.get("message", "")

                test_results.append(
                    TestCaseResult(
                        name=name,
                        outcome=outcome,
                        duration=duration,
                        failure_message=failure_message,
                        class_name=classname,
                    )
                )

        except ET.ParseError as e:
            test_results.append(
                TestCaseResult(
                    name="xml_parse",
                    outcome="error",
                    failure_message=f"Failed to parse test results: {e}",
                )
            )

        return test_results, total_time
