"""Reporters for test results.

This module provides reporters that format test results for
different output targets including Markdown documentation.
"""

from plc_code.testing.models import (
    BlockTestResult,
    ProjectTestResult,
)


class TestReporter:
    """Generates Markdown reports for test result documentation.

    Examples
    --------
    >>> reporter = TestReporter()
    >>> badge = reporter.generate_block_badge(result)
    >>> summary_md = reporter.generate_summary_page(project_result)
    """

    def generate_block_badge(self, result: BlockTestResult) -> str:
        """Generate test badge for individual block markdown.

        Parameters
        ----------
        result : BlockTestResult
            Test result for a single block.

        Returns
        -------
        str
            Markdown badge string with icons and pass/fail count.
        """
        if not result.has_tests:
            return ":white_circle: No tests"

        if result.success:
            return f":white_check_mark: {result.passed}/{result.total} passed"
        else:
            return f":x: {result.passed}/{result.total} passed " f"({result.failed} failed)"

    def generate_block_section(self, result: BlockTestResult) -> str:
        """Generate detailed test results section for block markdown.

        Parameters
        ----------
        result : BlockTestResult
            Test result for a single block.

        Returns
        -------
        str
            Markdown content for test details section.
        """
        if not result.has_tests:
            return ""

        lines = [
            "",
            "## Unit Tests",
            "",
        ]

        # Summary metrics
        lines.append(f"**Test File:** `{result.test_file}`")
        lines.append("")
        lines.append("| Passed | Failed | Skipped | Total |")
        lines.append("|--------|--------|---------|-------|")
        lines.append(f"| {result.passed} | {result.failed} | {result.skipped} | {result.total} |")
        lines.append("")

        # Show failed tests first
        failed_tests = result.failed_tests
        if failed_tests:
            lines.append("### Failed Tests")
            lines.append("")
            for test in failed_tests:
                class_prefix = f"{test.class_name}::" if test.class_name else ""
                lines.append(f"#### :x: `{class_prefix}{test.name}`")
                lines.append("")
                if test.failure_message:
                    # Format failure message as code block
                    lines.append("```")
                    lines.append(test.failure_message.strip())
                    lines.append("```")
                    lines.append("")

        # Collapsible section for all tests
        lines.append("<details>")
        lines.append("<summary>All Test Results</summary>")
        lines.append("")
        lines.append("| Test | Status | Duration |")
        lines.append("|------|--------|----------|")

        for test in result.test_results:
            status_icon = self._get_status_icon(test.outcome)
            class_prefix = f"{test.class_name}::" if test.class_name else ""
            duration = f"{test.duration:.3f}s" if test.duration > 0 else "-"
            lines.append(f"| `{class_prefix}{test.name}` | {status_icon} | {duration} |")

        lines.append("")
        lines.append("</details>")

        return "\n".join(lines)

    def generate_summary_page(
        self,
        result: ProjectTestResult,
        block_paths: dict[str, str] | None = None,
    ) -> str:
        """Generate summary.md content for test documentation.

        Parameters
        ----------
        result : ProjectTestResult
            Aggregated test results.
        block_paths : dict[str, str] | None, optional
            Mapping of block names to their documentation paths (relative to tests/).

        Returns
        -------
        str
            Markdown content for test summary page.
        """
        block_paths = block_paths or {}

        lines = [
            "# Unit Test Summary",
            "",
        ]

        # Overall status badge with icon
        if result.overall_success and result.blocks_tested > 0:
            lines.append("## :white_check_mark: All Tests Passed")
        elif result.blocks_tested == 0:
            lines.append("## :white_circle: No Tests Found")
        else:
            lines.append("## :x: Tests Failed")
        lines.append("")

        # Overview metrics
        lines.append("## Overview")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Blocks with tests | {result.blocks_tested} |")
        lines.append(f"| Blocks without tests | {result.blocks_untested} |")
        lines.append(f"| Test coverage | {result.coverage_percent:.1f}% |")
        lines.append(f"| Total tests | {result.total_tests} |")
        lines.append(f"| Passed | {result.total_passed} |")
        lines.append(f"| Failed | {result.total_failed} |")
        if result.total_skipped > 0:
            lines.append(f"| Skipped | {result.total_skipped} |")
        if result.total_tests > 0:
            lines.append(f"| Pass rate | {result.pass_rate:.1f}% |")
        lines.append("")

        # Tested blocks table
        tested_blocks = result.get_tested_blocks()
        if tested_blocks:
            lines.append("## Tested Blocks")
            lines.append("")
            lines.append("| Block | Tests | Passed | Failed | Status |")
            lines.append("|-------|-------|--------|--------|--------|")

            # Sort by failed count (failures first), then by name
            for block_result in sorted(
                tested_blocks,
                key=lambda r: (-r.failed, r.block_name),
            ):
                block_name = block_result.block_name
                # Create link if path is available
                if block_name in block_paths:
                    block_link = f"[{block_name}]({block_paths[block_name]})"
                else:
                    block_link = block_name

                status = ":white_check_mark:" if block_result.success else ":x:"
                lines.append(
                    f"| {block_link} | {block_result.total} | "
                    f"{block_result.passed} | {block_result.failed} | {status} |"
                )
            lines.append("")

        # Failed tests details
        failed_blocks = result.get_failed_blocks()
        if failed_blocks:
            lines.append("## Failed Tests")
            lines.append("")

            for block_result in sorted(failed_blocks, key=lambda r: r.block_name):
                block_name = block_result.block_name
                if block_name in block_paths:
                    block_link = f"[{block_name}]({block_paths[block_name]})"
                else:
                    block_link = block_name

                lines.append(f"### {block_link}")
                lines.append("")

                for test in block_result.failed_tests:
                    class_prefix = f"{test.class_name}::" if test.class_name else ""
                    lines.append(f"- `{class_prefix}{test.name}`")
                    if test.failure_message:
                        # Show first line of failure message
                        first_line = test.failure_message.split("\n")[0].strip()
                        if first_line:
                            lines.append(f"  - {first_line}")
                lines.append("")

        # Untested blocks list
        untested_blocks = result.get_untested_blocks()
        if untested_blocks:
            lines.append("## Untested Blocks")
            lines.append("")
            lines.append("The following blocks have no associated test files:")
            lines.append("")

            for block_result in sorted(untested_blocks, key=lambda r: r.block_name):
                block_name = block_result.block_name
                if block_name in block_paths:
                    block_link = f"[{block_name}]({block_paths[block_name]})"
                else:
                    block_link = block_name
                lines.append(f"- {block_link}")
            lines.append("")

        return "\n".join(lines)

    def generate_coverage_page(
        self,
        result: ProjectTestResult,
        categories: dict[str, list[str]] | None = None,
    ) -> str:
        """Generate coverage.md content with per-category breakdown.

        Parameters
        ----------
        result : ProjectTestResult
            Aggregated test results.
        categories : dict[str, list[str]] | None, optional
            Mapping of category names to block names.

        Returns
        -------
        str
            Markdown content for coverage page.
        """
        lines = [
            "# Test Coverage",
            "",
        ]

        # Visual coverage bar
        coverage = result.coverage_percent
        filled = int(coverage / 10)
        empty = 10 - filled
        bar = "█" * filled + "░" * empty
        lines.append(f"## Coverage: {coverage:.1f}%")
        lines.append("")
        lines.append(f"`{bar}` {result.blocks_tested}/{result.total_blocks} blocks")
        lines.append("")

        # Per-category breakdown if provided
        if categories:
            lines.append("## Coverage by Category")
            lines.append("")
            lines.append("| Category | Tested | Total | Coverage |")
            lines.append("|----------|--------|-------|----------|")

            # Build lookup for test status
            tested_names = {r.block_name for r in result.block_results if r.has_tests}

            for category, blocks in sorted(categories.items()):
                tested = sum(1 for b in blocks if b in tested_names)
                total = len(blocks)
                pct = (tested / total * 100) if total > 0 else 0
                lines.append(f"| {category} | {tested} | {total} | {pct:.1f}% |")
            lines.append("")

        # Summary stats
        lines.append("## Summary Statistics")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total blocks | {result.total_blocks} |")
        lines.append(f"| Blocks with tests | {result.blocks_tested} |")
        lines.append(f"| Blocks without tests | {result.blocks_untested} |")
        lines.append(f"| Test coverage | {coverage:.1f}% |")
        lines.append("")

        return "\n".join(lines)

    def _get_status_icon(self, outcome: str) -> str:
        """Get status icon for test outcome.

        Parameters
        ----------
        outcome : str
            Test outcome string.

        Returns
        -------
        str
            Markdown icon string.
        """
        icons = {
            "passed": ":white_check_mark:",
            "failed": ":x:",
            "error": ":x:",
            "skipped": ":fast_forward:",
        }
        return icons.get(outcome, ":question:")


__all__ = ["TestReporter"]
