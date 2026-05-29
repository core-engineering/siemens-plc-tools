"""Tests for markdown template generation."""

from datetime import date
from pathlib import Path

from plc_code.analyzer.quality.models import (
    BlockAnalysisResult,
    ProjectAnalysisResult,
    Severity,
    Violation,
)
from plc_code.exporter.models import BrandingConfig
from plc_code.exporter.templates import ReportMarkdownGenerator
from plc_code.testing.models import (
    BlockTestResult,
    ProjectTestResult,
    TestCaseResult,
)


class TestReportMarkdownGenerator:
    """Tests for ReportMarkdownGenerator class."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.branding = BrandingConfig(
            company_name="Test Corp",
            project_title="Test Report",
        )
        self.generator = ReportMarkdownGenerator(self.branding)

    def test_init(self) -> None:
        """Test generator initialization."""
        assert self.generator.branding == self.branding
        assert self.generator._lines == []

    def test_generate_empty_report(self) -> None:
        """Test generating report with no data."""
        content = self.generator.generate_report()
        assert "---" in content  # YAML frontmatter
        assert "Executive Summary" in content

    def test_generate_with_date(self) -> None:
        """Test report with custom date."""
        test_date = date(2025, 1, 15)
        content = self.generator.generate_report(report_date=test_date)
        assert "2025-01-15" in content


class TestFrontmatter:
    """Tests for YAML frontmatter generation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.branding = BrandingConfig(
            company_name="Test Corp",
            project_title="Test Report",
            subtitle="Q1 2025",
            author="John Doe",
        )
        self.generator = ReportMarkdownGenerator(self.branding)

    def test_frontmatter_basic(self) -> None:
        """Test basic frontmatter fields."""
        content = self.generator.generate_report(report_date=date(2025, 1, 15))
        assert 'title: "Test Report"' in content
        assert 'subtitle: "Q1 2025"' in content
        assert 'author: "John Doe"' in content
        assert 'date: "2025-01-15"' in content

    def test_frontmatter_eisvogel_options(self) -> None:
        """Test eisvogel-specific frontmatter options."""
        content = self.generator.generate_report()
        assert "titlepage: true" in content
        assert 'titlepage-color: "0d47a1"' in content
        assert 'titlepage-text-color: "FFFFFF"' in content
        assert "titlepage-rule-height: 2" in content

    def test_frontmatter_toc(self) -> None:
        """Test table of contents options."""
        content = self.generator.generate_report(include_toc=True)
        assert "toc: true" in content
        assert "toc-own-page: false" in content

    def test_frontmatter_no_toc(self) -> None:
        """Test report without table of contents."""
        content = self.generator.generate_report(include_toc=False)
        assert "toc: false" in content

    def test_frontmatter_header_footer(self) -> None:
        """Test header and footer configuration."""
        content = self.generator.generate_report()
        assert 'header-left: "Test Corp"' in content
        assert 'header-center: "Test Report"' in content
        assert "footer-center:" in content

    def test_frontmatter_document_settings(self) -> None:
        """Test document settings."""
        content = self.generator.generate_report()
        assert "papersize: a4" in content
        assert "geometry: margin=2.5cm" in content
        assert "fontsize: 11pt" in content
        assert "listings: true" in content


class TestExecutiveSummary:
    """Tests for executive summary section."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.branding = BrandingConfig()
        self.generator = ReportMarkdownGenerator(self.branding)

    def test_summary_header(self) -> None:
        """Test executive summary header."""
        content = self.generator.generate_report()
        assert "# Executive Summary" in content

    def test_summary_passed_status(self) -> None:
        """Test passed status when all results pass."""
        analysis = ProjectAnalysisResult(block_results=[])
        test = ProjectTestResult(block_results=[])
        content = self.generator.generate_report(
            analysis_result=analysis,
            test_result=test,
        )
        assert "**Overall Status:** PASSED" in content

    def test_summary_failed_quality(self) -> None:
        """Test failed status when quality fails."""
        analysis = ProjectAnalysisResult(
            block_results=[
                BlockAnalysisResult(
                    block_name="TestBlock",
                    block_type="FUNCTION_BLOCK",
                    source_file=Path("test.s7dcl"),
                    violations=[
                        Violation(
                            rule_code="N001",
                            message="Test error",
                            severity=Severity.ERROR,
                        )
                    ],
                )
            ]
        )
        content = self.generator.generate_report(analysis_result=analysis)
        assert "**Overall Status:** FAILED" in content

    def test_summary_table(self) -> None:
        """Test summary table structure."""
        analysis = ProjectAnalysisResult(block_results=[])
        content = self.generator.generate_report(analysis_result=analysis)
        assert "| Category | Status | Details |" in content
        assert "| Code Quality |" in content


class TestQualitySection:
    """Tests for code quality analysis section."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.branding = BrandingConfig()
        self.generator = ReportMarkdownGenerator(self.branding)

    def test_quality_section_header(self) -> None:
        """Test quality section header."""
        analysis = ProjectAnalysisResult(block_results=[])
        content = self.generator.generate_report(analysis_result=analysis)
        assert "# Code Quality Analysis" in content

    def test_quality_key_metrics(self) -> None:
        """Test key metrics table."""
        analysis = ProjectAnalysisResult(
            block_results=[
                BlockAnalysisResult(
                    block_name="Block1",
                    block_type="FUNCTION_BLOCK",
                    source_file=Path("block1.s7dcl"),
                ),
                BlockAnalysisResult(
                    block_name="Block2",
                    block_type="FUNCTION",
                    source_file=Path("block2.s7dcl"),
                ),
            ]
        )
        content = self.generator.generate_report(analysis_result=analysis)
        assert "## Key Metrics" in content
        assert "| Total Blocks Analyzed | 2 |" in content
        assert "| Blocks Passed | 2 |" in content
        assert "| Pass Rate | 100.0% |" in content

    def test_quality_violations_by_rule(self) -> None:
        """Test violations by rule table."""
        analysis = ProjectAnalysisResult(
            block_results=[
                BlockAnalysisResult(
                    block_name="Block1",
                    block_type="FUNCTION_BLOCK",
                    source_file=Path("block1.s7dcl"),
                    violations=[
                        Violation("N001", "Error 1", Severity.ERROR),
                        Violation("N001", "Error 2", Severity.ERROR),
                        Violation("D001", "Warning 1", Severity.WARNING),
                    ],
                )
            ]
        )
        content = self.generator.generate_report(analysis_result=analysis)
        assert "## Top Violations by Rule" in content
        assert "| N001 | 2 |" in content
        assert "| D001 | 1 |" in content

    def test_quality_blocks_with_errors(self) -> None:
        """Test blocks requiring attention table."""
        analysis = ProjectAnalysisResult(
            block_results=[
                BlockAnalysisResult(
                    block_name="BadBlock",
                    block_type="FUNCTION_BLOCK",
                    source_file=Path("bad.s7dcl"),
                    violations=[
                        Violation("N001", "Error", Severity.ERROR),
                        Violation("D001", "Warning", Severity.WARNING),
                    ],
                )
            ]
        )
        content = self.generator.generate_report(analysis_result=analysis)
        assert "## Blocks Requiring Attention" in content
        assert "| BadBlock | FUNCTION_BLOCK | 1 | 1 |" in content


class TestTestSection:
    """Tests for unit test results section."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.branding = BrandingConfig()
        self.generator = ReportMarkdownGenerator(self.branding)

    def test_test_section_header(self) -> None:
        """Test test section header."""
        test = ProjectTestResult(block_results=[])
        content = self.generator.generate_report(test_result=test)
        assert "# Unit Test Results" in content

    def test_test_key_metrics(self) -> None:
        """Test key metrics for tests."""
        test = ProjectTestResult(
            block_results=[
                BlockTestResult(
                    block_name="Block1",
                    test_file=Path("test_block1.py"),
                    test_results=[
                        TestCaseResult("test_a", "passed"),
                        TestCaseResult("test_b", "passed"),
                    ],
                ),
                BlockTestResult(
                    block_name="Block2",
                    test_file=None,
                ),
            ]
        )
        content = self.generator.generate_report(test_result=test)
        assert "## Key Metrics" in content
        assert "| Total Blocks | 2 |" in content
        assert "| Blocks with Tests | 1 |" in content
        assert "| Test Coverage | 50.0% |" in content
        assert "| Total Tests | 2 |" in content
        assert "| Tests Passed | 2 |" in content

    def test_test_failed_summary(self) -> None:
        """Test failed test summary table."""
        test = ProjectTestResult(
            block_results=[
                BlockTestResult(
                    block_name="FailingBlock",
                    test_file=Path("test_failing.py"),
                    test_results=[
                        TestCaseResult("test_a", "passed"),
                        TestCaseResult("test_b", "failed"),
                    ],
                )
            ]
        )
        content = self.generator.generate_report(test_result=test)
        assert "## Failed Test Summary" in content
        assert "| FailingBlock | 2 | 1 | 1 |" in content

    def test_test_coverage_status(self) -> None:
        """Test coverage by status section."""
        test = ProjectTestResult(
            block_results=[
                BlockTestResult(
                    block_name="Tested",
                    test_file=Path("test.py"),
                    test_results=[TestCaseResult("test_a", "passed")],  # Need results
                ),
                BlockTestResult(block_name="Untested", test_file=None),
            ]
        )
        content = self.generator.generate_report(test_result=test)
        assert "## Test Coverage by Status" in content
        assert "**Tested:** 1 blocks (50.0%)" in content
        assert "**Untested:** 1 blocks (50.0%)" in content


class TestNoSections:
    """Tests for reports with sections excluded."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.branding = BrandingConfig()
        self.generator = ReportMarkdownGenerator(self.branding)

    def test_no_quality_section(self) -> None:
        """Test report without quality section."""
        test = ProjectTestResult(block_results=[])
        content = self.generator.generate_report(
            analysis_result=None,
            test_result=test,
        )
        assert "# Code Quality Analysis" not in content
        assert "# Unit Test Results" in content

    def test_no_test_section(self) -> None:
        """Test report without test section."""
        analysis = ProjectAnalysisResult(block_results=[])
        content = self.generator.generate_report(
            analysis_result=analysis,
            test_result=None,
        )
        assert "# Code Quality Analysis" in content
        assert "# Unit Test Results" not in content

    def test_both_sections(self) -> None:
        """Test report with both sections."""
        analysis = ProjectAnalysisResult(block_results=[])
        test = ProjectTestResult(block_results=[])
        content = self.generator.generate_report(
            analysis_result=analysis,
            test_result=test,
        )
        assert "# Code Quality Analysis" in content
        assert "# Unit Test Results" in content
