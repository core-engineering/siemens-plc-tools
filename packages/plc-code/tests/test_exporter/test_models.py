"""Tests for exporter configuration models."""

from datetime import date
from pathlib import Path

from plc_code.exporter.models import (
    BrandingConfig,
    PDFExportConfig,
    PDFExportResult,
)


class TestBrandingConfig:
    """Tests for BrandingConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default branding configuration."""
        config = BrandingConfig()
        assert config.company_name == ""
        assert config.project_title == "PLC Code Analysis Report"
        assert config.logo_path is None
        assert config.subtitle == ""
        assert config.author == ""

    def test_custom_values(self) -> None:
        """Test custom branding configuration."""
        config = BrandingConfig(
            company_name="ACME Corp",
            project_title="Custom Report",
            logo_path=Path("logo.png"),
            subtitle="Quarterly Analysis",
            author="John Doe",
        )
        assert config.company_name == "ACME Corp"
        assert config.project_title == "Custom Report"
        assert config.logo_path == Path("logo.png")
        assert config.subtitle == "Quarterly Analysis"
        assert config.author == "John Doe"


class TestPDFExportConfig:
    """Tests for PDFExportConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default export configuration."""
        config = PDFExportConfig()
        assert config.output_path == Path("report.pdf")
        assert config.include_quality is True
        assert config.include_tests is True
        assert config.include_toc is True
        assert config.report_date is None
        assert config.pandoc_path == "pandoc"
        assert config.eisvogel_template is None

    def test_default_branding(self) -> None:
        """Test default branding is created."""
        config = PDFExportConfig()
        assert config.branding.company_name == ""

    def test_custom_branding(self) -> None:
        """Test export config with custom branding."""
        branding = BrandingConfig(company_name="Test Corp")
        config = PDFExportConfig(branding=branding)
        assert config.branding.company_name == "Test Corp"

    def test_custom_output_path(self) -> None:
        """Test custom output path."""
        config = PDFExportConfig(output_path=Path("/tmp/custom.pdf"))
        assert config.output_path == Path("/tmp/custom.pdf")

    def test_disable_sections(self) -> None:
        """Test disabling quality and tests sections."""
        config = PDFExportConfig(
            include_quality=False,
            include_tests=False,
        )
        assert config.include_quality is False
        assert config.include_tests is False

    def test_custom_report_date(self) -> None:
        """Test custom report date."""
        test_date = date(2025, 6, 15)
        config = PDFExportConfig(report_date=test_date)
        assert config.report_date == test_date

    def test_custom_template(self) -> None:
        """Test custom eisvogel template path."""
        config = PDFExportConfig(eisvogel_template=Path("custom.latex"))
        assert config.eisvogel_template == Path("custom.latex")


class TestPDFExportResult:
    """Tests for PDFExportResult dataclass."""

    def test_default_success(self) -> None:
        """Test default result is success."""
        result = PDFExportResult()
        assert result.success is True
        assert result.output_path is None
        assert result.error is None
        assert result.warnings == []
        assert result.markdown_content == ""

    def test_success_with_output(self) -> None:
        """Test successful result with output path."""
        result = PDFExportResult(
            success=True,
            output_path=Path("report.pdf"),
        )
        assert result.success is True
        assert result.output_path == Path("report.pdf")

    def test_failure_with_error(self) -> None:
        """Test failed result with error message."""
        result = PDFExportResult(
            success=False,
            error="pandoc not found",
        )
        assert result.success is False
        assert result.error == "pandoc not found"

    def test_warnings(self) -> None:
        """Test result with warnings."""
        result = PDFExportResult(
            success=True,
            warnings=["No tests found", "Logo not found"],
        )
        assert len(result.warnings) == 2
        assert "No tests found" in result.warnings

    def test_markdown_content(self) -> None:
        """Test result with markdown content."""
        markdown = "# Report\n\nContent here"
        result = PDFExportResult(
            success=True,
            markdown_content=markdown,
        )
        assert result.markdown_content == markdown
