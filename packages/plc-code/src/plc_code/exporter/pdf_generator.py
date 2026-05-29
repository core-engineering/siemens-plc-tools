"""PDF report generation using pandoc and eisvogel.

This module provides the PDFGenerator class that creates PDF reports
from quality analysis and test results using pandoc with the eisvogel
LaTeX template.
"""

import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from plc_code.analyzer.quality.models import ProjectAnalysisResult
from plc_code.exporter.models import PDFExportConfig, PDFExportResult
from plc_code.exporter.templates import ReportMarkdownGenerator
from plc_code.testing.models import ProjectTestResult


class PDFGenerator:
    """Generates PDF reports from analysis and test results.

    Parameters
    ----------
    config : PDFExportConfig
        Export configuration.

    Examples
    --------
    >>> config = PDFExportConfig(
    ...     branding=BrandingConfig(company_name="ACME Corp"),
    ...     output_path=Path("report.pdf"),
    ... )
    >>> generator = PDFGenerator(config)
    >>> result = generator.generate(analysis_result, test_result)
    >>> if result.success:
    ...     print(f"PDF saved to {result.output_path}")
    """

    def __init__(self, config: PDFExportConfig) -> None:
        """Initialize the PDF generator.

        Parameters
        ----------
        config : PDFExportConfig
            Export configuration.
        """
        self.config = config
        self._markdown_generator = ReportMarkdownGenerator(config.branding)

    def generate(
        self,
        analysis_result: ProjectAnalysisResult | None = None,
        test_result: ProjectTestResult | None = None,
    ) -> PDFExportResult:
        """Generate PDF report from analysis and test results.

        Parameters
        ----------
        analysis_result : ProjectAnalysisResult | None
            Quality analysis results.
        test_result : ProjectTestResult | None
            Unit test results.

        Returns
        -------
        PDFExportResult
            Result of the export operation.
        """
        warnings: list[str] = []

        # Validate inputs
        if not self.config.include_quality and not self.config.include_tests:
            return PDFExportResult(
                success=False,
                error="At least one of include_quality or include_tests must be True",
            )

        if self.config.include_quality and analysis_result is None:
            warnings.append("Quality analysis requested but no results provided")
        if self.config.include_tests and test_result is None:
            warnings.append("Test results requested but no results provided")

        # Verify pandoc is available
        if not self._check_pandoc():
            return PDFExportResult(
                success=False,
                error=f"pandoc not found at '{self.config.pandoc_path}'. "
                "Please install pandoc: https://pandoc.org/installing.html",
                warnings=warnings,
            )

        # Generate markdown content
        markdown_content = self._markdown_generator.generate_report(
            analysis_result=analysis_result if self.config.include_quality else None,
            test_result=test_result if self.config.include_tests else None,
            report_date=self.config.report_date or date.today(),
            include_toc=self.config.include_toc,
        )

        # Run pandoc
        try:
            return self._run_pandoc(markdown_content, warnings)
        except Exception as e:
            return PDFExportResult(
                success=False,
                error=f"PDF generation failed: {e}",
                warnings=warnings,
                markdown_content=markdown_content,
            )

    def generate_markdown_only(
        self,
        analysis_result: ProjectAnalysisResult | None = None,
        test_result: ProjectTestResult | None = None,
    ) -> PDFExportResult:
        """Generate only the markdown content without PDF conversion.

        Useful for debugging or when pandoc is not available.

        Parameters
        ----------
        analysis_result : ProjectAnalysisResult | None
            Quality analysis results.
        test_result : ProjectTestResult | None
            Unit test results.

        Returns
        -------
        PDFExportResult
            Result with markdown_content populated.
        """
        # Generate markdown content
        markdown_content = self._markdown_generator.generate_report(
            analysis_result=analysis_result if self.config.include_quality else None,
            test_result=test_result if self.config.include_tests else None,
            report_date=self.config.report_date or date.today(),
            include_toc=self.config.include_toc,
        )

        return PDFExportResult(
            success=True,
            markdown_content=markdown_content,
        )

    def _check_pandoc(self) -> bool:
        """Check if pandoc is available.

        Returns
        -------
        bool
            True if pandoc is available.
        """
        try:
            result = subprocess.run(
                [self.config.pandoc_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def _run_pandoc(
        self,
        markdown_content: str,
        warnings: list[str],
    ) -> PDFExportResult:
        """Run pandoc to convert markdown to PDF.

        Parameters
        ----------
        markdown_content : str
            Markdown content with YAML frontmatter.
        warnings : list[str]
            Warnings list to append to.

        Returns
        -------
        PDFExportResult
            Result of the operation.
        """
        # Ensure output directory exists
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)

        # Create temp directory for working files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            md_file = temp_path / "report.md"

            # Copy template assets if template_dir is provided
            if self.config.template_dir and self.config.template_dir.exists():
                self._copy_template_assets(temp_path, warnings)

            # Copy logo if provided (for header)
            if self.config.branding.logo_path and self.config.branding.logo_path.exists():
                # Copy to Images/ subdirectory to match template expectations
                images_dir = temp_path / "Images"
                images_dir.mkdir(exist_ok=True)
                logo_dest = images_dir / self.config.branding.logo_path.name
                shutil.copy(self.config.branding.logo_path, logo_dest)
                # Update markdown to use local path
                markdown_content = markdown_content.replace(
                    str(self.config.branding.logo_path),
                    f"Images/{logo_dest.name}",
                )

            # Copy titlepage background if provided
            if (
                self.config.branding.titlepage_background
                and self.config.branding.titlepage_background.exists()
            ):
                images_dir = temp_path / "Images"
                images_dir.mkdir(exist_ok=True)
                bg_dest = images_dir / self.config.branding.titlepage_background.name
                shutil.copy(self.config.branding.titlepage_background, bg_dest)
                # Update markdown to use local path
                markdown_content = markdown_content.replace(
                    str(self.config.branding.titlepage_background),
                    f"Images/{bg_dest.name}",
                )

            # Write markdown file
            md_file.write_text(markdown_content, encoding="utf-8")

            # Build pandoc command
            cmd = self._build_pandoc_command(md_file, temp_path)

            # Run pandoc
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=temp_path,
                timeout=120,  # 2 minute timeout
            )

            if result.returncode != 0:
                return PDFExportResult(
                    success=False,
                    error=f"pandoc failed: {result.stderr}",
                    warnings=warnings,
                    markdown_content=markdown_content,
                )

            # Check if PDF was created
            if not self.config.output_path.exists():
                return PDFExportResult(
                    success=False,
                    error="PDF file was not created",
                    warnings=warnings,
                    markdown_content=markdown_content,
                )

            return PDFExportResult(
                success=True,
                output_path=self.config.output_path,
                warnings=warnings,
                markdown_content=markdown_content,
            )

    def _copy_template_assets(self, temp_path: Path, warnings: list[str]) -> None:
        """Copy template assets from template_dir to temp directory.

        Parameters
        ----------
        temp_path : Path
            Temporary working directory.
        warnings : list[str]
            Warnings list to append to.
        """
        template_dir = self.config.template_dir
        if not template_dir:
            return

        # Copy Images directory
        images_src = template_dir / "Images"
        if images_src.exists() and images_src.is_dir():
            images_dest = temp_path / "Images"
            shutil.copytree(images_src, images_dest, dirs_exist_ok=True)
        else:
            warnings.append(f"Images directory not found in {template_dir}")

        # Copy Templates directory (for custom template)
        templates_src = template_dir / "Templates"
        if templates_src.exists() and templates_src.is_dir():
            templates_dest = temp_path / "Templates"
            shutil.copytree(templates_src, templates_dest, dirs_exist_ok=True)

    def _build_pandoc_command(self, md_file: Path, temp_path: Path) -> list[str]:
        """Build the pandoc command line.

        Parameters
        ----------
        md_file : Path
            Path to the markdown file.
        temp_path : Path
            Temporary working directory (for locating template assets).

        Returns
        -------
        list[str]
            Command line arguments.
        """
        cmd = [
            self.config.pandoc_path,
            str(md_file),
            "-o",
            str(self.config.output_path.absolute()),
            "--from",
            "markdown",
            "--pdf-engine",
            "xelatex",
        ]

        # Add eisvogel template
        # Priority: 1) explicit eisvogel_template, 2) template from template_dir, 3) system default
        if self.config.eisvogel_template:
            cmd.extend(["--template", str(self.config.eisvogel_template)])
        elif self.config.template_dir:
            # Look for template in Templates/ subdirectory
            custom_template = temp_path / "Templates" / "template.tex"
            if custom_template.exists():
                cmd.extend(["--template", str(custom_template)])
            else:
                # Fallback to system eisvogel
                cmd.extend(["--template", "eisvogel"])
        else:
            # Use default eisvogel template (must be installed)
            cmd.extend(["--template", "eisvogel"])

        # Table of contents
        if self.config.include_toc:
            cmd.append("--toc")
            cmd.extend(["--toc-depth", "2"])

        # Enable listings for code blocks
        cmd.append("--listings")

        return cmd
