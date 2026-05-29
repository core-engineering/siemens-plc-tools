"""Data models for reporting.

This module defines the data structures used to represent analysis findings,
report sections, and complete reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(Enum):
    """Severity level for findings.

    Attributes
    ----------
    ERROR : str
        Must fix - blocks quality gates. Exit code 1.
    WARNING : str
        Should fix - potential issues but doesn't block.
    INFO : str
        Informational - style suggestions and minor improvements.
    """

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def symbol(self) -> str:
        """Get symbol representation for CLI output."""
        symbols = {
            Severity.ERROR: "✗",
            Severity.WARNING: "⚠",
            Severity.INFO: "ℹ",
        }
        return symbols.get(self, "•")

    @property
    def color(self) -> str:
        """Get color name for Rich formatting."""
        colors = {
            Severity.ERROR: "red",
            Severity.WARNING: "yellow",
            Severity.INFO: "blue",
        }
        return colors.get(self, "white")


@dataclass
class Finding:
    """A single analysis finding or violation.

    Attributes
    ----------
    title : str
        Short title describing the finding.
    severity : Severity
        Severity level.
    message : str
        Detailed description of the finding.
    location : str
        Location where finding occurs (e.g., "file:line" or "Block:15").
    rule_code : str
        Unique rule identifier (e.g., "N001").
    suggestion : str
        Suggested fix or correction.
    context : str
        Additional context (e.g., the identifier that violates naming).
    """

    title: str
    severity: Severity
    message: str
    location: str = ""
    rule_code: str = ""
    suggestion: str = ""
    context: str = ""


@dataclass
class ReportSection:
    """A section within a report.

    Attributes
    ----------
    title : str
        Section title.
    content : str
        Section content (markdown formatted).
    findings : list[Finding]
        Findings in this section.
    subsections : list[ReportSection]
        Nested subsections.
    """

    title: str
    content: str = ""
    findings: list[Finding] = field(default_factory=list)
    subsections: list[ReportSection] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        """Count of error-level findings in this section and subsections."""
        count = sum(1 for f in self.findings if f.severity == Severity.ERROR)
        for sub in self.subsections:
            count += sub.error_count
        return count

    @property
    def warning_count(self) -> int:
        """Count of warning-level findings in this section and subsections."""
        count = sum(1 for f in self.findings if f.severity == Severity.WARNING)
        for sub in self.subsections:
            count += sub.warning_count
        return count

    @property
    def info_count(self) -> int:
        """Count of info-level findings in this section and subsections."""
        count = sum(1 for f in self.findings if f.severity == Severity.INFO)
        for sub in self.subsections:
            count += sub.info_count
        return count


@dataclass
class Report:
    """A complete analysis report.

    Attributes
    ----------
    title : str
        Report title.
    description : str
        Report description.
    sections : list[ReportSection]
        Report sections.
    metadata : dict
        Additional metadata (version, date, etc.).
    """

    title: str
    description: str = ""
    sections: list[ReportSection] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def total_errors(self) -> int:
        """Total error count across all sections."""
        return sum(s.error_count for s in self.sections)

    @property
    def total_warnings(self) -> int:
        """Total warning count across all sections."""
        return sum(s.warning_count for s in self.sections)

    @property
    def total_info(self) -> int:
        """Total info count across all sections."""
        return sum(s.info_count for s in self.sections)

    @property
    def passed(self) -> bool:
        """Returns True if no errors in the report."""
        return self.total_errors == 0

    def get_all_findings(self) -> list[Finding]:
        """Get all findings from all sections.

        Returns
        -------
        list[Finding]
            All findings in the report.
        """
        findings = []
        for section in self.sections:
            findings.extend(self._collect_findings(section))
        return findings

    def _collect_findings(self, section: ReportSection) -> list[Finding]:
        """Recursively collect findings from a section.

        Parameters
        ----------
        section : ReportSection
            Section to collect from.

        Returns
        -------
        list[Finding]
            All findings in section and subsections.
        """
        findings = list(section.findings)
        for sub in section.subsections:
            findings.extend(self._collect_findings(sub))
        return findings

    def to_summary(self) -> dict:
        """Generate report summary statistics.

        Returns
        -------
        dict
            Summary statistics.
        """
        return {
            "title": self.title,
            "total_findings": len(self.get_all_findings()),
            "errors": self.total_errors,
            "warnings": self.total_warnings,
            "info": self.total_info,
            "passed": self.passed,
            "sections": len(self.sections),
            "metadata": self.metadata,
        }
