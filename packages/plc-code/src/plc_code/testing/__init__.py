"""Unit test execution and reporting for SCL blocks.

This module provides functionality for:
- Discovering test files by naming convention
- Executing pytest and collecting results
- Generating test documentation and badges

Exports
-------
TestCaseResult
    Result of a single test function.
BlockTestResult
    Test results for a single block.
ProjectTestResult
    Aggregated test results for all blocks.
TestRunner
    Executes tests and collects results.
TestReporter
    Generates markdown documentation for test results.
discover_test_file
    Find test file for a block by naming convention.
build_test_registry
    Map block names to their test files.
"""

from plc_code.testing.discovery import build_test_registry, discover_test_file
from plc_code.testing.models import (
    BlockTestResult,
    ProjectTestResult,
    TestCaseResult,
)
from plc_code.testing.reporter import TestReporter
from plc_code.testing.runner import TestRunner

__all__ = [
    "TestCaseResult",
    "BlockTestResult",
    "ProjectTestResult",
    "TestRunner",
    "TestReporter",
    "discover_test_file",
    "build_test_registry",
]
