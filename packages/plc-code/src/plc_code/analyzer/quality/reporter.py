"""Reporters for analysis results.

This module provides reporters that format analysis results for
different output targets including CLI and Markdown documentation.
"""

from plc_code.analyzer.quality.models import (
    BlockAnalysisResult,
    ProjectAnalysisResult,
    Severity,
    Violation,
)
from plc_code.analyzer.quality.rules import ALL_RULES

# Rule name lookup for anchor generation
_RULE_NAMES: dict[str, str] = {}


def _get_rule_name(code: str) -> str:
    """Get rule name for a given rule code."""
    global _RULE_NAMES
    if not _RULE_NAMES:
        for rule_class in ALL_RULES:
            rule = rule_class()
            _RULE_NAMES[rule.info.code] = rule.info.name
    return _RULE_NAMES.get(code, "")


class CLIReporter:
    """Reports analysis results to terminal with optional colors.

    Examples
    --------
    >>> reporter = CLIReporter()
    >>> print(reporter.report(result))
    """

    # ANSI color codes
    COLORS = {
        Severity.ERROR: "\033[91m",  # Red
        Severity.WARNING: "\033[93m",  # Yellow
        Severity.INFO: "\033[94m",  # Blue
    }
    BOLD = "\033[1m"
    RESET = "\033[0m"
    GREEN = "\033[92m"

    def report(self, result: ProjectAnalysisResult, use_color: bool = True) -> str:
        """Generate CLI report for analysis results.

        Parameters
        ----------
        result : ProjectAnalysisResult
            Analysis results to report.
        use_color : bool, optional
            Whether to use ANSI colors (default: True).

        Returns
        -------
        str
            Formatted report string.
        """
        lines: list[str] = []

        # Report each block with violations
        for block_result in result.block_results:
            if block_result.violations:
                lines.append(self._format_block_header(block_result, use_color))
                # Sort violations by severity (errors first) then by rule code
                sorted_violations = sorted(
                    block_result.violations,
                    key=lambda v: (
                        (0 if v.severity == Severity.ERROR else (1 if v.severity == Severity.WARNING else 2)),
                        v.rule_code,
                    ),
                )
                for violation in sorted_violations:
                    lines.append(self._format_violation(violation, use_color))
                lines.append("")

        # Summary
        lines.append(self._format_summary(result, use_color))

        return "\n".join(lines)

    def _format_block_header(self, result: BlockAnalysisResult, use_color: bool) -> str:
        """Format block header line."""
        path = str(result.source_file) if result.source_file else "(unknown)"
        header = f"{result.block_name} ({result.block_type}) - {path}"
        if use_color:
            return f"{self.BOLD}{header}{self.RESET}"
        return header

    def _format_violation(self, violation: Violation, use_color: bool) -> str:
        """Format single violation line."""
        severity = violation.severity.value.upper()
        color = self.COLORS.get(violation.severity, "")

        # Format: "  [N001] warning: Variable 'x' should use camelCase"
        if use_color:
            line = f"  {color}[{violation.rule_code}] {severity}{self.RESET}: {violation.message}"
        else:
            line = f"  [{violation.rule_code}] {severity}: {violation.message}"

        # Add suggestion if present
        if violation.suggestion:
            line += f"\n    -> {violation.suggestion}"

        return line

    def _format_summary(self, result: ProjectAnalysisResult, use_color: bool) -> str:
        """Format summary section."""
        lines = []

        total_blocks = len(result.block_results)
        blocks_passed = result.blocks_passed
        blocks_failed = total_blocks - blocks_passed

        # Overall status
        if result.passed:
            if use_color:
                status = f"{self.GREEN}PASSED{self.RESET}"
            else:
                status = "PASSED"
        else:
            if use_color:
                status = f"{self.COLORS[Severity.ERROR]}FAILED{self.RESET}"
            else:
                status = "FAILED"

        lines.append(f"Analysis {status}")
        lines.append(f"  Blocks analyzed: {total_blocks}")
        lines.append(f"  Blocks passed: {blocks_passed}")
        lines.append(f"  Blocks with errors: {blocks_failed}")
        lines.append("")

        # Violation counts by severity
        lines.append("Violations:")
        if use_color:
            lines.append(f"  {self.COLORS[Severity.ERROR]}Errors: {result.total_errors}{self.RESET}")
            lines.append(f"  {self.COLORS[Severity.WARNING]}Warnings: {result.total_warnings}{self.RESET}")
            lines.append(f"  {self.COLORS[Severity.INFO]}Info: {result.total_info}{self.RESET}")
        else:
            lines.append(f"  Errors: {result.total_errors}")
            lines.append(f"  Warnings: {result.total_warnings}")
            lines.append(f"  Info: {result.total_info}")

        return "\n".join(lines)


class MarkdownReporter:
    """Generates Markdown reports for documentation integration.

    Examples
    --------
    >>> reporter = MarkdownReporter()
    >>> rules_md = reporter.generate_rules_documentation()
    >>> summary_md = reporter.generate_summary(result)
    """

    def generate_rules_documentation(self) -> str:
        """Generate rules.md content documenting all rules.

        Returns
        -------
        str
            Markdown content for rules documentation.
        """
        lines = [
            "# Code Quality Rules",
            "",
            "This document describes all quality rules enforced by the SCL linter.",
            "",
        ]

        # Group rules by category
        rules_by_category: dict[str, list[tuple[str, str, str, str, str]]] = {}
        for rule_class in ALL_RULES:
            rule = rule_class()
            info = rule.info
            category = info.category.value
            if category not in rules_by_category:
                rules_by_category[category] = []
            rules_by_category[category].append(
                (info.code, info.name, info.description, info.severity.value, info.rationale)
            )

        category_names = {
            "N": "Naming Conventions",
            "C": "Complexity",
            "D": "Documentation",
            "B": "Best Practices",
            "S": "Structure",
        }

        # Generate section for each category
        for category_code, category_name in category_names.items():
            if category_code in rules_by_category:
                lines.append(f"## {category_name} Rules ({category_code})")
                lines.append("")
                lines.append("| Code | Name | Description | Severity |")
                lines.append("|------|------|-------------|----------|")

                for code, name, desc, severity, _rationale in sorted(rules_by_category[category_code]):
                    lines.append(f"| {code} | {name} | {desc} | {severity} |")

                lines.append("")

                # Detailed descriptions
                lines.append("### Details")
                lines.append("")
                for code, name, desc, severity, rationale in sorted(rules_by_category[category_code]):
                    lines.append(f"#### {code}: {name}")
                    lines.append("")
                    lines.append(f"**Severity:** {severity}")
                    lines.append("")
                    lines.append(desc)
                    lines.append("")
                    if rationale:
                        lines.append(f"**Rationale:** {rationale}")
                        lines.append("")

        return "\n".join(lines)

    def generate_summary(
        self,
        result: ProjectAnalysisResult,
        block_paths: dict[str, str] | None = None,
    ) -> str:
        """Generate summary.md content with project-wide KPIs.

        Parameters
        ----------
        result : ProjectAnalysisResult
            Analysis results.
        block_paths : dict[str, str] | None, optional
            Mapping of block names to their documentation paths (relative to analysis/).

        Returns
        -------
        str
            Markdown content for summary page.
        """
        block_paths = block_paths or {}

        lines = [
            "# Code Quality Summary",
            "",
        ]

        total_blocks = len(result.block_results)
        blocks_passed = result.blocks_passed

        # Overall status badge with icon
        if result.passed:
            lines.append("## :white_check_mark: PASSED")
        else:
            lines.append("## :x: FAILED")
        lines.append("")

        # KPI table
        lines.append("### Key Metrics")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total Blocks | {total_blocks} |")
        lines.append(f"| Blocks Passed | {blocks_passed} |")
        lines.append(
            f"| Pass Rate | {blocks_passed / total_blocks * 100:.1f}% |"
            if total_blocks > 0
            else "| Pass Rate | N/A |"
        )
        lines.append(f"| Total Errors | {result.total_errors} |")
        lines.append(f"| Total Warnings | {result.total_warnings} |")
        lines.append(f"| Total Info | {result.total_info} |")
        lines.append("")

        # Violations by rule (with links to rule definitions)
        violations_by_rule = result.get_violations_by_rule()
        if violations_by_rule:
            lines.append("## Violations by Rule")
            lines.append("")
            lines.append("| Rule | Name | Count |")
            lines.append("|------|------|-------|")
            for rule_code, count in sorted(violations_by_rule.items(), key=lambda x: -x[1]):
                rule_name = _get_rule_name(rule_code)
                anchor = f"{rule_code.lower()}-{rule_name}".replace("_", "-")
                rule_link = f"[{rule_code}](rules.md#{anchor})"
                # Format rule name for display (replace hyphens with spaces, title case)
                display_name = rule_name.replace("-", " ").title()
                lines.append(f"| {rule_link} | {display_name} | {count} |")
            lines.append("")

        # Blocks with violations (with links to block documentation)
        blocks_with_violations = [r for r in result.block_results if r.violations and r.block_name]
        if blocks_with_violations:
            lines.append("## Blocks with Violations")
            lines.append("")
            lines.append("| Block | Type | Errors | Warnings | Info |")
            lines.append("|-------|------|--------|----------|------|")
            for block_result in sorted(blocks_with_violations, key=lambda r: -r.error_count):
                block_name = block_result.block_name
                # Create link if path is available
                if block_name in block_paths:
                    block_link = f"[{block_name}]({block_paths[block_name]})"
                else:
                    block_link = block_name
                lines.append(
                    f"| {block_link} | {block_result.block_type} | "
                    f"{block_result.error_count} | {block_result.warning_count} | "
                    f"{block_result.info_count} |"
                )
            lines.append("")

        return "\n".join(lines)

    def generate_block_badge(self, result: BlockAnalysisResult) -> str:
        """Generate quality badge for individual block markdown.

        Parameters
        ----------
        result : BlockAnalysisResult
            Analysis result for a single block.

        Returns
        -------
        str
            Markdown badge string with icons.
        """
        if result.passed:
            if result.warning_count == 0 and result.info_count == 0:
                return ":white_check_mark: Passed"
            else:
                parts = []
                if result.warning_count > 0:
                    parts.append(f":warning: {result.warning_count}")
                if result.info_count > 0:
                    parts.append(f":information_source: {result.info_count}")
                return f":white_check_mark: Passed ({', '.join(parts)})"
        else:
            parts = []
            if result.error_count > 0:
                parts.append(f":x: {result.error_count}")
            if result.warning_count > 0:
                parts.append(f":warning: {result.warning_count}")
            return f":x: Failed ({', '.join(parts)})"

    def generate_block_details(self, result: BlockAnalysisResult) -> str:
        """Generate detailed violations section for block markdown.

        Parameters
        ----------
        result : BlockAnalysisResult
            Analysis result for a single block.

        Returns
        -------
        str
            Markdown content for violations details.
        """
        if not result.violations:
            return ""

        lines = [
            "",
            "### Code Quality Issues",
            "",
        ]

        # Group by severity
        errors = [v for v in result.violations if v.severity == Severity.ERROR]
        warnings = [v for v in result.violations if v.severity == Severity.WARNING]
        infos = [v for v in result.violations if v.severity == Severity.INFO]

        if errors:
            lines.append("#### Errors")
            lines.append("")
            for v in errors:
                lines.append(f"- **[{v.rule_code}]** {v.message}")
            lines.append("")

        if warnings:
            lines.append("#### Warnings")
            lines.append("")
            for v in warnings:
                lines.append(f"- **[{v.rule_code}]** {v.message}")
            lines.append("")

        if infos:
            lines.append("#### Info")
            lines.append("")
            for v in infos:
                lines.append(f"- **[{v.rule_code}]** {v.message}")
            lines.append("")

        return "\n".join(lines)


__all__ = ["CLIReporter", "MarkdownReporter"]
