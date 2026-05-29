"""Data models for code quality analysis.

This module defines the data structures used to represent analysis results,
including violations, severity levels, and aggregated statistics.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Severity(Enum):
    """Severity level for violations.

    Attributes
    ----------
    ERROR : str
        Must fix - blocks code quality gates. Exit code 1.
    WARNING : str
        Should fix - potential issues but doesn't block.
    INFO : str
        Informational - style suggestions and minor improvements.
    """

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class RuleCategory(Enum):
    """Categories of quality rules.

    Attributes
    ----------
    NAMING : str
        Naming convention rules (N prefix).
    COMPLEXITY : str
        Code complexity rules (C prefix).
    DOCUMENTATION : str
        Documentation completeness rules (D prefix).
    BEST_PRACTICES : str
        Best practices rules (B prefix).
    STRUCTURE : str
        Code structure rules (S prefix).
    """

    NAMING = "N"
    COMPLEXITY = "C"
    DOCUMENTATION = "D"
    BEST_PRACTICES = "B"
    STRUCTURE = "S"


@dataclass
class Violation:
    """A single rule violation.

    Attributes
    ----------
    rule_code : str
        Unique rule identifier (e.g., "N001").
    message : str
        Human-readable description of the violation.
    severity : Severity
        Severity level.
    line_number : int
        Line number where violation occurs (0 if not applicable).
    column : int
        Column number (0 if not applicable).
    context : str
        Additional context (e.g., the identifier that violates naming).
    suggestion : str
        Suggested fix or correction.
    """

    rule_code: str
    message: str
    severity: Severity
    line_number: int = 0
    column: int = 0
    context: str = ""
    suggestion: str = ""


@dataclass
class RuleInfo:
    """Metadata about a rule.

    Attributes
    ----------
    code : str
        Unique identifier (e.g., "N001").
    name : str
        Short name (e.g., "variable-naming").
    description : str
        Full description of what the rule checks.
    severity : Severity
        Default severity level.
    category : RuleCategory
        Rule category.
    rationale : str
        Why this rule exists.
    examples_bad : list[str]
        Examples of code that violates this rule.
    examples_good : list[str]
        Examples of compliant code.
    """

    code: str
    name: str
    description: str
    severity: Severity
    category: RuleCategory
    rationale: str = ""
    examples_bad: list[str] = field(default_factory=list)
    examples_good: list[str] = field(default_factory=list)


@dataclass
class BlockAnalysisResult:
    """Analysis result for a single block.

    Attributes
    ----------
    block_name : str
        Name of the analyzed block.
    block_type : str
        Type of block (FUNCTION_BLOCK, FUNCTION, TYPE).
    source_file : Path
        Path to the source file.
    violations : list[Violation]
        All violations found.
    metrics : dict[str, int | float]
        Computed metrics (complexity, LOC, etc.).
    """

    block_name: str
    block_type: str
    source_file: Path
    violations: list[Violation] = field(default_factory=list)
    metrics: dict[str, int | float] = field(default_factory=dict)

    @property
    def error_count(self) -> int:
        """Count of error-level violations."""
        return sum(1 for v in self.violations if v.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        """Count of warning-level violations."""
        return sum(1 for v in self.violations if v.severity == Severity.WARNING)

    @property
    def info_count(self) -> int:
        """Count of info-level violations."""
        return sum(1 for v in self.violations if v.severity == Severity.INFO)

    @property
    def passed(self) -> bool:
        """Returns True if no errors."""
        return self.error_count == 0


@dataclass
class ProjectAnalysisResult:
    """Analysis result for entire project.

    Attributes
    ----------
    block_results : list[BlockAnalysisResult]
        Results for all analyzed blocks.
    """

    block_results: list[BlockAnalysisResult] = field(default_factory=list)

    @property
    def total_errors(self) -> int:
        """Total error count across all blocks."""
        return sum(r.error_count for r in self.block_results)

    @property
    def total_warnings(self) -> int:
        """Total warning count across all blocks."""
        return sum(r.warning_count for r in self.block_results)

    @property
    def total_info(self) -> int:
        """Total info count across all blocks."""
        return sum(r.info_count for r in self.block_results)

    @property
    def blocks_with_errors(self) -> int:
        """Count of blocks with at least one error."""
        return sum(1 for r in self.block_results if r.error_count > 0)

    @property
    def blocks_passed(self) -> int:
        """Count of blocks with no errors."""
        return sum(1 for r in self.block_results if r.passed)

    @property
    def passed(self) -> bool:
        """Returns True if no errors in any block."""
        return self.total_errors == 0

    def get_violations_by_rule(self) -> dict[str, int]:
        """Get violation counts grouped by rule code.

        Returns
        -------
        dict[str, int]
            Mapping from rule code to violation count.
        """
        counts: dict[str, int] = {}
        for result in self.block_results:
            for violation in result.violations:
                counts[violation.rule_code] = counts.get(violation.rule_code, 0) + 1
        return counts

    def get_violations_by_severity(self) -> dict[Severity, int]:
        """Get violation counts grouped by severity.

        Returns
        -------
        dict[Severity, int]
            Mapping from severity to violation count.
        """
        counts: dict[Severity, int] = {
            Severity.ERROR: self.total_errors,
            Severity.WARNING: self.total_warnings,
            Severity.INFO: self.total_info,
        }
        return counts
