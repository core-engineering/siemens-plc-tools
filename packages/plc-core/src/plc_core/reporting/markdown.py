"""Markdown rendering for reports.

This module provides utilities for rendering reports as Markdown.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plc_core.reporting.models import Finding, Report, ReportSection, Severity


class MarkdownRenderer:
    """Renderer for generating Markdown reports.

    Example
    -------
    >>> renderer = MarkdownRenderer()
    >>> markdown = renderer.render(report)
    """

    def __init__(self, include_toc: bool = True, max_heading_level: int = 6) -> None:
        """Initialize the renderer.

        Parameters
        ----------
        include_toc : bool
            Whether to include table of contents.
        max_heading_level : int
            Maximum heading level to use (1-6).
        """
        self.include_toc = include_toc
        self.max_heading_level = max_heading_level

    def render(self, report: Report) -> str:
        """Render a report as Markdown.

        Parameters
        ----------
        report : Report
            Report to render.

        Returns
        -------
        str
            Markdown content.
        """
        lines: list[str] = []

        # Title
        lines.append(f"# {report.title}")
        lines.append("")

        # Description
        if report.description:
            lines.append(report.description)
            lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- **Errors:** {report.total_errors}")
        lines.append(f"- **Warnings:** {report.total_warnings}")
        lines.append(f"- **Info:** {report.total_info}")
        lines.append(f"- **Status:** {'✓ Passed' if report.passed else '✗ Failed'}")
        lines.append("")

        # Sections
        for section in report.sections:
            lines.extend(self._render_section(section, level=2))

        return "\n".join(lines)

    def _render_section(self, section: ReportSection, level: int = 2) -> list[str]:
        """Render a report section.

        Parameters
        ----------
        section : ReportSection
            Section to render.
        level : int
            Heading level (2-6).

        Returns
        -------
        list[str]
            Markdown lines.
        """
        lines: list[str] = []
        heading_level = min(level, self.max_heading_level)
        heading = "#" * heading_level

        lines.append(f"{heading} {section.title}")
        lines.append("")

        if section.content:
            lines.append(section.content)
            lines.append("")

        # Findings table
        if section.findings:
            lines.extend(self._render_findings_table(section.findings))
            lines.append("")

        # Subsections
        for subsection in section.subsections:
            lines.extend(self._render_section(subsection, level + 1))

        return lines

    def _render_findings_table(self, findings: list[Finding]) -> list[str]:
        """Render findings as a Markdown table.

        Parameters
        ----------
        findings : list[Finding]
            Findings to render.

        Returns
        -------
        list[str]
            Markdown table lines.
        """
        lines: list[str] = []

        lines.append("| Severity | Code | Title | Location | Message |")
        lines.append("|----------|------|-------|----------|---------|")

        for finding in findings:
            severity_icon = self._severity_icon(finding.severity)
            code = finding.rule_code or "-"
            location = finding.location or "-"
            # Escape pipe characters in message
            message = finding.message.replace("|", "\\|")
            lines.append(f"| {severity_icon} | {code} | {finding.title} | {location} | {message} |")

        return lines

    def _severity_icon(self, severity: Severity) -> str:
        """Get icon for severity level.

        Parameters
        ----------
        severity : Severity
            Severity level.

        Returns
        -------
        str
            Icon string.
        """
        from plc_core.reporting.models import Severity

        icons = {
            Severity.ERROR: "🔴 Error",
            Severity.WARNING: "🟡 Warning",
            Severity.INFO: "🔵 Info",
        }
        return icons.get(severity, "⚪ Unknown")


def render_report(report: Report, **kwargs: object) -> str:
    """Convenience function to render a report as Markdown.

    Parameters
    ----------
    report : Report
        Report to render.
    **kwargs : object
        Additional arguments passed to MarkdownRenderer.

    Returns
    -------
    str
        Markdown content.
    """
    renderer = MarkdownRenderer(**kwargs)  # type: ignore[arg-type]
    return renderer.render(report)
