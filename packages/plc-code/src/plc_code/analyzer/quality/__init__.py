"""Code quality analysis module for SCL and LADDER blocks.

This module provides a ruff/black-style code quality analyzer for
TIA Portal V21 SCL exports, enforcing naming conventions, detecting
code complexity issues, and validating documentation completeness.

Examples
--------
>>> from plc_code.analyzer.quality import AnalysisRunner, Severity
>>> from plc_code.parser import parse_scl_file
>>>
>>> # Parse and analyze a single block
>>> block = parse_scl_file(Path("myblock.s7dcl"))
>>> runner = AnalysisRunner()
>>> result = runner.analyze_block(block)
>>>
>>> # Check results
>>> print(f"Errors: {result.error_count}")
>>> print(f"Warnings: {result.warning_count}")
>>> for violation in result.violations:
...     print(f"{violation.rule_code}: {violation.message}")
"""

from plc_code.analyzer.quality.models import (
    BlockAnalysisResult,
    ProjectAnalysisResult,
    RuleCategory,
    RuleInfo,
    Severity,
    Violation,
)
from plc_code.analyzer.quality.reporter import CLIReporter, MarkdownReporter
from plc_code.analyzer.quality.rules import ALL_RULES, Rule, get_all_rules, register_rule
from plc_code.analyzer.quality.runner import AnalysisRunner

__all__ = [
    # Models
    "Severity",
    "RuleCategory",
    "RuleInfo",
    "Violation",
    "BlockAnalysisResult",
    "ProjectAnalysisResult",
    # Rules
    "Rule",
    "ALL_RULES",
    "get_all_rules",
    "register_rule",
    # Runner and reporters
    "AnalysisRunner",
    "CLIReporter",
    "MarkdownReporter",
]
