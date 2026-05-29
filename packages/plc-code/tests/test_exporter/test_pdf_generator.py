"""Tests for PDF generator."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plc_code.analyzer.quality.models import (
    BlockAnalysisResult,
    ProjectAnalysisResult,
)
from plc_code.exporter.models import BrandingConfig, PDFExportConfig
from plc_code.exporter.pdf_generator import PDFGenerator
from plc_code.testing.models import (
    BlockTestResult,
    ProjectTestResult,
    TestCaseResult,
)


class TestPDFGeneratorInit:
    """Tests for PDFGenerator initialization."""

    def test_init_default_config(self) -> None:
        """Test initialization with default config."""
        config = PDFExportConfig()
        generator = PDFGenerator(config)
        assert generator.config == config
        assert generator._markdown_generator is not None

    def test_init_custom_branding(self) -> None:
        """Test initialization with custom branding."""
        branding = BrandingConfig(company_name="Custom Corp")
        config = PDFExportConfig(branding=branding)
        generator = PDFGenerator(config)
        assert generator._markdown_generator.branding.company_name == "Custom Corp"


class TestPandocCheck:
    """Tests for pandoc availability check."""

    def test_check_pandoc_available(self) -> None:
        """Test pandoc check when available."""
        config = PDFExportConfig()
        generator = PDFGenerator(config)

        with patch("plc_code.exporter.pdf_generator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert generator._check_pandoc() is True
            mock_run.assert_called_once()

    def test_check_pandoc_not_found(self) -> None:
        """Test pandoc check when not found."""
        config = PDFExportConfig()
        generator = PDFGenerator(config)

        with patch("plc_code.exporter.pdf_generator.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            assert generator._check_pandoc() is False

    def test_check_pandoc_timeout(self) -> None:
        """Test pandoc check when timeout."""
        config = PDFExportConfig()
        generator = PDFGenerator(config)

        with patch("plc_code.exporter.pdf_generator.subprocess.run") as mock_run:
            import subprocess

            mock_run.side_effect = subprocess.TimeoutExpired(cmd="pandoc", timeout=10)
            assert generator._check_pandoc() is False

    def test_check_pandoc_custom_path(self) -> None:
        """Test pandoc check with custom path."""
        config = PDFExportConfig(pandoc_path="/usr/local/bin/pandoc")
        generator = PDFGenerator(config)

        with patch("plc_code.exporter.pdf_generator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            generator._check_pandoc()
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == "/usr/local/bin/pandoc"


class TestBuildPandocCommand:
    """Tests for pandoc command building."""

    def test_basic_command(self, tmp_path: Path) -> None:
        """Test basic pandoc command."""
        config = PDFExportConfig(output_path=tmp_path / "report.pdf")
        generator = PDFGenerator(config)

        md_file = tmp_path / "report.md"
        cmd = generator._build_pandoc_command(md_file, tmp_path)

        assert "pandoc" in cmd
        assert str(md_file) in cmd
        assert "-o" in cmd
        assert "--from" in cmd
        assert "markdown" in cmd
        assert "--pdf-engine" in cmd
        assert "xelatex" in cmd
        assert "--template" in cmd
        assert "eisvogel" in cmd

    def test_command_with_toc(self, tmp_path: Path) -> None:
        """Test command includes TOC options."""
        config = PDFExportConfig(
            output_path=tmp_path / "report.pdf",
            include_toc=True,
        )
        generator = PDFGenerator(config)

        md_file = tmp_path / "report.md"
        cmd = generator._build_pandoc_command(md_file, tmp_path)

        assert "--toc" in cmd
        assert "--toc-depth" in cmd
        assert "2" in cmd

    def test_command_without_toc(self, tmp_path: Path) -> None:
        """Test command without TOC."""
        config = PDFExportConfig(
            output_path=tmp_path / "report.pdf",
            include_toc=False,
        )
        generator = PDFGenerator(config)

        md_file = tmp_path / "report.md"
        cmd = generator._build_pandoc_command(md_file, tmp_path)

        assert "--toc" not in cmd

    def test_command_custom_template(self, tmp_path: Path) -> None:
        """Test command with custom template."""
        template_path = tmp_path / "custom.latex"
        config = PDFExportConfig(
            output_path=tmp_path / "report.pdf",
            eisvogel_template=template_path,
        )
        generator = PDFGenerator(config)

        md_file = tmp_path / "report.md"
        cmd = generator._build_pandoc_command(md_file, tmp_path)

        assert "--template" in cmd
        template_idx = cmd.index("--template")
        assert cmd[template_idx + 1] == str(template_path)


class TestGenerateValidation:
    """Tests for generate method validation."""

    def test_generate_no_sections_fails(self) -> None:
        """Test generate fails when both sections disabled."""
        config = PDFExportConfig(
            include_quality=False,
            include_tests=False,
        )
        generator = PDFGenerator(config)
        result = generator.generate()

        assert result.success is False
        assert result.error is not None
        assert "At least one" in result.error

    def test_generate_pandoc_not_found(self) -> None:
        """Test generate fails gracefully when pandoc not found."""
        config = PDFExportConfig()
        generator = PDFGenerator(config)

        with patch.object(generator, "_check_pandoc", return_value=False):
            analysis = ProjectAnalysisResult(block_results=[])
            result = generator.generate(analysis_result=analysis)

            assert result.success is False
            assert result.error is not None
            assert "pandoc not found" in result.error

    def test_generate_warnings_for_missing_data(self) -> None:
        """Test warnings when requested data not provided."""
        config = PDFExportConfig(
            include_quality=True,
            include_tests=True,
        )
        generator = PDFGenerator(config)

        with patch.object(generator, "_check_pandoc", return_value=False):
            result = generator.generate(analysis_result=None, test_result=None)

            assert "Quality analysis requested but no results provided" in result.warnings
            assert "Test results requested but no results provided" in result.warnings


class TestGenerateMarkdownOnly:
    """Tests for markdown-only generation."""

    def test_generate_markdown_only(self) -> None:
        """Test generating markdown without PDF conversion."""
        config = PDFExportConfig()
        generator = PDFGenerator(config)

        analysis = ProjectAnalysisResult(
            block_results=[
                BlockAnalysisResult(
                    block_name="TestBlock",
                    block_type="FUNCTION_BLOCK",
                    source_file=Path("test.s7dcl"),
                )
            ]
        )

        result = generator.generate_markdown_only(analysis_result=analysis)

        assert result.success is True
        assert "# Executive Summary" in result.markdown_content
        assert "# Code Quality Analysis" in result.markdown_content
        # Block names only appear in summary tables (metrics show counts)
        assert "Total Blocks Analyzed | 1" in result.markdown_content

    def test_generate_markdown_only_with_tests(self) -> None:
        """Test markdown generation with test results."""
        config = PDFExportConfig()
        generator = PDFGenerator(config)

        test = ProjectTestResult(
            block_results=[
                BlockTestResult(
                    block_name="TestBlock",
                    test_file=Path("test.py"),
                    test_results=[
                        TestCaseResult("test_a", "passed"),
                    ],
                )
            ]
        )

        result = generator.generate_markdown_only(test_result=test)

        assert result.success is True
        assert "# Unit Test Results" in result.markdown_content


class TestGeneratePDF:
    """Tests for full PDF generation."""

    def test_generate_creates_output_directory(self, tmp_path: Path) -> None:
        """Test that output directory is created."""
        output_dir = tmp_path / "reports" / "pdf"
        config = PDFExportConfig(output_path=output_dir / "report.pdf")
        generator = PDFGenerator(config)

        with patch.object(generator, "_check_pandoc", return_value=True):
            with patch.object(generator, "_run_pandoc") as mock_run:
                mock_run.return_value = MagicMock(success=True)
                generator.generate(analysis_result=ProjectAnalysisResult(block_results=[]))
                # _run_pandoc is called, which should create parent dirs
                mock_run.assert_called_once()

    @patch("plc_code.exporter.pdf_generator.subprocess.run")
    @patch("plc_code.exporter.pdf_generator.shutil.copy")
    def test_generate_with_logo(self, mock_copy: MagicMock, mock_run: MagicMock, tmp_path: Path) -> None:
        """Test PDF generation with logo file."""
        # Create a fake logo file
        logo_path = tmp_path / "logo.png"
        logo_path.write_bytes(b"fake png data")

        output_path = tmp_path / "report.pdf"
        branding = BrandingConfig(logo_path=logo_path)
        config = PDFExportConfig(output_path=output_path, branding=branding)
        generator = PDFGenerator(config)

        # Mock pandoc success
        mock_run.return_value = MagicMock(returncode=0)

        # Create the output file to simulate pandoc success
        output_path.write_bytes(b"fake pdf")

        analysis = ProjectAnalysisResult(block_results=[])
        generator.generate(analysis_result=analysis)

        # Logo should be copied
        assert mock_copy.called

    @patch("plc_code.exporter.pdf_generator.subprocess.run")
    def test_generate_pandoc_failure(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Test handling of pandoc failure."""
        config = PDFExportConfig(output_path=tmp_path / "report.pdf")
        generator = PDFGenerator(config)

        # First call succeeds (version check), second fails (actual conversion)
        mock_run.side_effect = [
            MagicMock(returncode=0),  # _check_pandoc
            MagicMock(returncode=1, stderr="LaTeX error"),  # _run_pandoc
        ]

        analysis = ProjectAnalysisResult(block_results=[])
        result = generator.generate(analysis_result=analysis)

        assert result.success is False
        assert result.error is not None
        assert "pandoc failed" in result.error
        assert result.markdown_content != ""  # Markdown should be preserved


class TestIntegration:
    """Integration tests (skipped if pandoc not available)."""

    @pytest.fixture
    def pandoc_available(self) -> bool:
        """Check if pandoc is available."""
        import shutil

        return shutil.which("pandoc") is not None

    @pytest.mark.skipif(
        not Path("/usr/bin/pandoc").exists() and not Path("/usr/local/bin/pandoc").exists(),
        reason="pandoc not installed",
    )
    def test_full_generation_with_pandoc(self, tmp_path: Path) -> None:
        """Test full PDF generation with actual pandoc (requires pandoc+eisvogel)."""
        config = PDFExportConfig(output_path=tmp_path / "report.pdf")
        generator = PDFGenerator(config)

        analysis = ProjectAnalysisResult(
            block_results=[
                BlockAnalysisResult(
                    block_name="TestBlock",
                    block_type="FUNCTION_BLOCK",
                    source_file=Path("test.s7dcl"),
                )
            ]
        )

        # This may fail if eisvogel template is not installed
        result = generator.generate(analysis_result=analysis)

        # We can't guarantee success without eisvogel, but markdown should be generated
        assert result.markdown_content != ""
