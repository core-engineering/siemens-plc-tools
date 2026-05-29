"""Tests for plc_core.reporting module."""

from plc_core.reporting import (
    Finding,
    MarkdownRenderer,
    Report,
    ReportSection,
    Severity,
)


class TestSeverity:
    """Tests for Severity enum."""

    def test_values(self) -> None:
        """Test severity values."""
        assert Severity.ERROR.value == "error"
        assert Severity.WARNING.value == "warning"
        assert Severity.INFO.value == "info"

    def test_symbol(self) -> None:
        """Test symbol property."""
        assert Severity.ERROR.symbol == "✗"
        assert Severity.WARNING.symbol == "⚠"
        assert Severity.INFO.symbol == "ℹ"

    def test_color(self) -> None:
        """Test color property."""
        assert Severity.ERROR.color == "red"
        assert Severity.WARNING.color == "yellow"
        assert Severity.INFO.color == "blue"


class TestFinding:
    """Tests for Finding class."""

    def test_create_finding(self) -> None:
        """Test creating a finding."""
        finding = Finding(
            title="Variable naming",
            severity=Severity.WARNING,
            message="Variable name does not follow convention",
            location="MyBlock:15",
            rule_code="N001",
            suggestion="Use camelCase",
        )

        assert finding.title == "Variable naming"
        assert finding.severity == Severity.WARNING
        assert finding.message == "Variable name does not follow convention"
        assert finding.location == "MyBlock:15"
        assert finding.rule_code == "N001"

    def test_finding_defaults(self) -> None:
        """Test finding default values."""
        finding = Finding(
            title="Test",
            severity=Severity.INFO,
            message="Test message",
        )

        assert finding.location == ""
        assert finding.rule_code == ""
        assert finding.suggestion == ""
        assert finding.context == ""


class TestReportSection:
    """Tests for ReportSection class."""

    def test_empty_section(self) -> None:
        """Test empty section counts."""
        section = ReportSection(title="Test")
        assert section.error_count == 0
        assert section.warning_count == 0
        assert section.info_count == 0

    def test_section_with_findings(self) -> None:
        """Test section with findings."""
        section = ReportSection(
            title="Test",
            findings=[
                Finding("E1", Severity.ERROR, "Error 1"),
                Finding("E2", Severity.ERROR, "Error 2"),
                Finding("W1", Severity.WARNING, "Warning 1"),
                Finding("I1", Severity.INFO, "Info 1"),
            ],
        )

        assert section.error_count == 2
        assert section.warning_count == 1
        assert section.info_count == 1

    def test_section_with_subsections(self) -> None:
        """Test section counts include subsections."""
        subsection = ReportSection(
            title="Subsection",
            findings=[Finding("E1", Severity.ERROR, "Error")],
        )
        section = ReportSection(
            title="Section",
            findings=[Finding("W1", Severity.WARNING, "Warning")],
            subsections=[subsection],
        )

        assert section.error_count == 1
        assert section.warning_count == 1


class TestReport:
    """Tests for Report class."""

    def test_empty_report(self) -> None:
        """Test empty report."""
        report = Report(title="Test Report")
        assert report.total_errors == 0
        assert report.total_warnings == 0
        assert report.total_info == 0
        assert report.passed is True

    def test_report_with_sections(self) -> None:
        """Test report with sections."""
        report = Report(
            title="Test Report",
            sections=[
                ReportSection(
                    title="Section 1",
                    findings=[
                        Finding("E1", Severity.ERROR, "Error"),
                        Finding("W1", Severity.WARNING, "Warning"),
                    ],
                ),
                ReportSection(
                    title="Section 2",
                    findings=[Finding("I1", Severity.INFO, "Info")],
                ),
            ],
        )

        assert report.total_errors == 1
        assert report.total_warnings == 1
        assert report.total_info == 1
        assert report.passed is False

    def test_get_all_findings(self) -> None:
        """Test get_all_findings method."""
        report = Report(
            title="Test",
            sections=[
                ReportSection(
                    title="S1",
                    findings=[Finding("F1", Severity.ERROR, "Error")],
                    subsections=[
                        ReportSection(
                            title="S1.1",
                            findings=[Finding("F2", Severity.WARNING, "Warning")],
                        ),
                    ],
                ),
            ],
        )

        findings = report.get_all_findings()
        assert len(findings) == 2
        assert findings[0].title == "F1"
        assert findings[1].title == "F2"

    def test_to_summary(self) -> None:
        """Test to_summary method."""
        report = Report(
            title="Test Report",
            description="Description",
            sections=[
                ReportSection(
                    title="Section 1",
                    findings=[Finding("E1", Severity.ERROR, "Error")],
                ),
            ],
            metadata={"version": "1.0"},
        )

        summary = report.to_summary()
        assert summary["title"] == "Test Report"
        assert summary["total_findings"] == 1
        assert summary["errors"] == 1
        assert summary["passed"] is False
        assert summary["metadata"]["version"] == "1.0"


class TestMarkdownRenderer:
    """Tests for MarkdownRenderer class."""

    def test_render_empty_report(self) -> None:
        """Test rendering empty report."""
        report = Report(title="Test Report")
        renderer = MarkdownRenderer()
        markdown = renderer.render(report)

        assert "# Test Report" in markdown
        assert "**Errors:** 0" in markdown
        assert "**Warnings:** 0" in markdown
        assert "✓ Passed" in markdown

    def test_render_report_with_findings(self) -> None:
        """Test rendering report with findings."""
        report = Report(
            title="Analysis Report",
            description="Code analysis results",
            sections=[
                ReportSection(
                    title="Naming",
                    findings=[
                        Finding(
                            "Variable naming",
                            Severity.ERROR,
                            "Bad name",
                            location="Block:15",
                            rule_code="N001",
                        ),
                    ],
                ),
            ],
        )

        renderer = MarkdownRenderer()
        markdown = renderer.render(report)

        assert "# Analysis Report" in markdown
        assert "Code analysis results" in markdown
        assert "## Naming" in markdown
        assert "| Severity |" in markdown
        assert "N001" in markdown
        assert "Variable naming" in markdown
        assert "✗ Failed" in markdown

    def test_render_nested_sections(self) -> None:
        """Test rendering nested sections."""
        report = Report(
            title="Report",
            sections=[
                ReportSection(
                    title="Level 2",
                    content="Content",
                    subsections=[
                        ReportSection(title="Level 3"),
                    ],
                ),
            ],
        )

        renderer = MarkdownRenderer()
        markdown = renderer.render(report)

        assert "## Level 2" in markdown
        assert "### Level 3" in markdown
        assert "Content" in markdown
