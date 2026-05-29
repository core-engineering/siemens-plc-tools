"""Markdown template generation for PDF reports.

This module generates markdown content with YAML frontmatter
suitable for pandoc/eisvogel PDF conversion.
"""

from datetime import date

from plc_code.analyzer.quality.models import ProjectAnalysisResult
from plc_code.exporter.models import BrandingConfig
from plc_code.testing.models import ProjectTestResult


class ReportMarkdownGenerator:
    """Generates markdown report content for PDF export.

    Parameters
    ----------
    branding : BrandingConfig
        Branding configuration.

    Examples
    --------
    >>> branding = BrandingConfig(company_name="ACME Corp")
    >>> generator = ReportMarkdownGenerator(branding)
    >>> content = generator.generate_report(analysis_result, test_result)
    """

    def __init__(self, branding: BrandingConfig) -> None:
        """Initialize the generator.

        Parameters
        ----------
        branding : BrandingConfig
            Branding configuration.
        """
        self.branding = branding
        self._lines: list[str] = []

    def generate_report(
        self,
        analysis_result: ProjectAnalysisResult | None = None,
        test_result: ProjectTestResult | None = None,
        report_date: date | None = None,
        include_toc: bool = True,
    ) -> str:
        """Generate complete markdown report with frontmatter.

        Parameters
        ----------
        analysis_result : ProjectAnalysisResult | None
            Quality analysis results.
        test_result : ProjectTestResult | None
            Unit test results.
        report_date : date | None
            Report date.
        include_toc : bool
            Whether to include table of contents.

        Returns
        -------
        str
            Complete markdown document.
        """
        self._lines = []
        report_date = report_date or date.today()

        # YAML frontmatter for eisvogel
        self._add_frontmatter(report_date, include_toc)

        # Executive summary section
        self._add_executive_summary(analysis_result, test_result)

        # Quality analysis section
        if analysis_result is not None:
            self._add_quality_section(analysis_result)

        # Test results section
        if test_result is not None:
            self._add_test_section(test_result)

        return "\n".join(self._lines)

    def _add_frontmatter(self, report_date: date, include_toc: bool) -> None:
        """Add YAML frontmatter for eisvogel template.

        Parameters
        ----------
        report_date : date
            Report generation date.
        include_toc : bool
            Whether to include table of contents.
        """
        self._lines.append("---")
        self._lines.append(f'title: "{self.branding.project_title}"')

        if self.branding.subtitle:
            self._lines.append(f'subtitle: "{self.branding.subtitle}"')

        if self.branding.author:
            self._lines.append(f'author: "{self.branding.author}"')

        self._lines.append(f'date: "{report_date.strftime("%Y-%m-%d")}"')

        # Table of contents
        self._lines.append(f"toc: {str(include_toc).lower()}")
        self._lines.append("toc-own-page: false")

        # Titlepage configuration
        self._lines.append("titlepage: true")

        if self.branding.titlepage_background:
            # Custom template with background image
            self._lines.append('titlepage-color: "FFFFFF"')
            self._lines.append('titlepage-text-color: "FFFFFF"')
            self._lines.append('titlepage-rule-color: "435488"')
            self._lines.append("titlepage-rule-height: 0")
            self._lines.append(f'titlepage-background: "{self.branding.titlepage_background}"')
        else:
            # Default eisvogel styling (blue titlepage)
            self._lines.append('titlepage-color: "0d47a1"')
            self._lines.append('titlepage-text-color: "FFFFFF"')
            self._lines.append('titlepage-rule-color: "FFFFFF"')
            self._lines.append("titlepage-rule-height: 2")

            # Logo on title page (only without background)
            if self.branding.logo_path and self.branding.logo_path.exists():
                self._lines.append(f'titlepage-logo: "{self.branding.logo_path}"')
                self._lines.append("logo-width: 100")

        # Header/footer configuration
        # Note: custom template uses logo in header via \SmallLogo command
        # so we don't set header-left when using custom template
        if not self.branding.titlepage_background:
            self._lines.append(f'header-left: "{self.branding.company_name}"')
        self._lines.append(f'header-center: "{self.branding.project_title}"')

        # Footer with confidentiality notice
        self._lines.append(f'footer-center: "{self.branding.footer_text}"')

        # Document settings
        self._lines.append("papersize: a4")
        self._lines.append("geometry: margin=2.5cm")
        self._lines.append("fontsize: 11pt")

        # Code listings support
        self._lines.append("listings: true")

        self._lines.append("---")
        self._lines.append("")

    def _add_executive_summary(
        self,
        analysis_result: ProjectAnalysisResult | None,
        test_result: ProjectTestResult | None,
    ) -> None:
        """Add executive summary section.

        Parameters
        ----------
        analysis_result : ProjectAnalysisResult | None
            Quality analysis results.
        test_result : ProjectTestResult | None
            Unit test results.
        """
        self._lines.append("# Executive Summary")
        self._lines.append("")

        # Overall status
        quality_passed = analysis_result.passed if analysis_result else True
        tests_passed = test_result.overall_success if test_result else True
        overall_passed = quality_passed and tests_passed

        status = "PASSED" if overall_passed else "FAILED"
        self._lines.append(f"**Overall Status:** {status}")
        self._lines.append("")

        # Summary table
        self._lines.append("| Category | Status | Details |")
        self._lines.append("|----------|--------|---------|")

        if analysis_result:
            qa_status = "PASS" if analysis_result.passed else "FAIL"
            qa_details = (
                f"{analysis_result.total_errors} errors, " f"{analysis_result.total_warnings} warnings"
            )
            self._lines.append(f"| Code Quality | {qa_status} | {qa_details} |")

        if test_result:
            test_status = "PASS" if test_result.overall_success else "FAIL"
            if test_result.total_tests > 0:
                test_details = (
                    f"{test_result.total_passed}/{test_result.total_tests} passed "
                    f"({test_result.pass_rate:.1f}%)"
                )
            else:
                test_details = "No tests executed"
            self._lines.append(f"| Unit Tests | {test_status} | {test_details} |")

        self._lines.append("")

    def _add_quality_section(self, result: ProjectAnalysisResult) -> None:
        """Add code quality analysis section.

        Parameters
        ----------
        result : ProjectAnalysisResult
            Quality analysis results.
        """
        self._lines.append("# Code Quality Analysis")
        self._lines.append("")

        # Key metrics
        self._lines.append("## Key Metrics")
        self._lines.append("")
        self._lines.append("| Metric | Value |")
        self._lines.append("|--------|-------|")
        self._lines.append(f"| Total Blocks Analyzed | {len(result.block_results)} |")
        self._lines.append(f"| Blocks Passed | {result.blocks_passed} |")

        if result.block_results:
            pass_rate = result.blocks_passed / len(result.block_results) * 100
        else:
            pass_rate = 0.0
        self._lines.append(f"| Pass Rate | {pass_rate:.1f}% |")
        self._lines.append(f"| Total Errors | {result.total_errors} |")
        self._lines.append(f"| Total Warnings | {result.total_warnings} |")
        self._lines.append(f"| Total Info | {result.total_info} |")
        self._lines.append("")

        # Violations by rule (top 10)
        violations_by_rule = result.get_violations_by_rule()
        if violations_by_rule:
            self._lines.append("## Top Violations by Rule")
            self._lines.append("")
            self._lines.append("| Rule Code | Count |")
            self._lines.append("|-----------|-------|")

            sorted_rules = sorted(violations_by_rule.items(), key=lambda x: -x[1])[:10]
            for rule_code, count in sorted_rules:
                self._lines.append(f"| {rule_code} | {count} |")
            self._lines.append("")

        # Blocks with errors (summary only - no individual violations)
        blocks_with_errors = [r for r in result.block_results if r.error_count > 0]
        if blocks_with_errors:
            self._lines.append("## Blocks Requiring Attention")
            self._lines.append("")
            self._lines.append("| Block | Type | Errors | Warnings |")
            self._lines.append("|-------|------|--------|----------|")

            for block in sorted(blocks_with_errors, key=lambda b: -b.error_count)[:20]:
                self._lines.append(
                    f"| {block.block_name} | {block.block_type} | "
                    f"{block.error_count} | {block.warning_count} |"
                )
            self._lines.append("")

    def _add_test_section(self, result: ProjectTestResult) -> None:
        """Add test results section.

        Parameters
        ----------
        result : ProjectTestResult
            Unit test results.
        """
        self._lines.append("# Unit Test Results")
        self._lines.append("")

        # Key metrics
        self._lines.append("## Key Metrics")
        self._lines.append("")
        self._lines.append("| Metric | Value |")
        self._lines.append("|--------|-------|")
        self._lines.append(f"| Total Blocks | {result.total_blocks} |")
        self._lines.append(f"| Blocks with Tests | {result.blocks_tested} |")
        self._lines.append(f"| Test Coverage | {result.coverage_percent:.1f}% |")
        self._lines.append(f"| Total Tests | {result.total_tests} |")
        self._lines.append(f"| Tests Passed | {result.total_passed} |")
        self._lines.append(f"| Tests Failed | {result.total_failed} |")

        if result.total_tests > 0:
            self._lines.append(f"| Pass Rate | {result.pass_rate:.1f}% |")
        self._lines.append("")

        # Failed blocks summary
        failed_blocks = result.get_failed_blocks()
        if failed_blocks:
            self._lines.append("## Failed Test Summary")
            self._lines.append("")
            self._lines.append("| Block | Total Tests | Passed | Failed |")
            self._lines.append("|-------|-------------|--------|--------|")

            for block in sorted(failed_blocks, key=lambda b: -b.failed):
                self._lines.append(
                    f"| {block.block_name} | {block.total} | " f"{block.passed} | {block.failed} |"
                )
            self._lines.append("")

        # Coverage summary by status
        self._lines.append("## Test Coverage by Status")
        self._lines.append("")

        tested = result.blocks_tested
        untested = result.blocks_untested
        total = result.total_blocks

        if total > 0:
            self._lines.append(f"- **Tested:** {tested} blocks ({tested / total * 100:.1f}%)")
            self._lines.append(f"- **Untested:** {untested} blocks ({untested / total * 100:.1f}%)")
        else:
            self._lines.append("- No blocks to analyze")
        self._lines.append("")
