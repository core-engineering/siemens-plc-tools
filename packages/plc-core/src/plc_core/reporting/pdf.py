"""PDF export utilities using Pandoc.

This module provides utilities for exporting reports to PDF format
using Pandoc as the rendering engine.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plc_core.reporting.models import Report


class PdfExporter:
    """Exporter for generating PDF reports using Pandoc.

    Example
    -------
    >>> exporter = PdfExporter()
    >>> exporter.export(report, Path("report.pdf"))
    """

    def __init__(
        self,
        pandoc_path: str = "pandoc",
        pdf_engine: str = "xelatex",
        template: Path | None = None,
    ) -> None:
        """Initialize the exporter.

        Parameters
        ----------
        pandoc_path : str
            Path to pandoc executable.
        pdf_engine : str
            PDF engine to use (xelatex, pdflatex, etc.).
        template : Path | None
            Custom LaTeX template file.
        """
        self.pandoc_path = pandoc_path
        self.pdf_engine = pdf_engine
        self.template = template

    def is_available(self) -> bool:
        """Check if Pandoc is available.

        Returns
        -------
        bool
            True if Pandoc is installed and accessible.
        """
        try:
            result = subprocess.run(
                [self.pandoc_path, "--version"],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def export(
        self,
        report: Report,
        output_path: Path,
        markdown_content: str | None = None,
    ) -> bool:
        """Export a report to PDF.

        Parameters
        ----------
        report : Report
            Report to export.
        output_path : Path
            Path for output PDF file.
        markdown_content : str | None
            Pre-rendered Markdown content. If None, renders from report.

        Returns
        -------
        bool
            True if export succeeded.

        Raises
        ------
        RuntimeError
            If Pandoc is not available.
        """
        if not self.is_available():
            raise RuntimeError(
                f"Pandoc not found at '{self.pandoc_path}'. " "Install Pandoc to enable PDF export."
            )

        # Render markdown if not provided
        if markdown_content is None:
            from plc_core.reporting.markdown import render_report

            markdown_content = render_report(report)

        # Write to temp file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".md",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(markdown_content)
            temp_path = Path(f.name)

        try:
            # Build pandoc command
            cmd = [
                self.pandoc_path,
                str(temp_path),
                "-o",
                str(output_path),
                f"--pdf-engine={self.pdf_engine}",
                "--toc",
                f"--metadata=title:{report.title}",
            ]

            if self.template:
                cmd.extend(["--template", str(self.template)])

            # Run pandoc
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(f"Pandoc failed: {result.stderr}")

            return True

        finally:
            # Clean up temp file
            temp_path.unlink(missing_ok=True)

    def export_markdown(self, markdown_content: str, output_path: Path) -> bool:
        """Export pre-rendered Markdown to PDF.

        Parameters
        ----------
        markdown_content : str
            Markdown content to export.
        output_path : Path
            Path for output PDF file.

        Returns
        -------
        bool
            True if export succeeded.
        """
        from plc_core.reporting.models import Report

        # Create minimal report for metadata
        dummy_report = Report(title="Report")
        return self.export(dummy_report, output_path, markdown_content)
