"""Configuration models for PDF export.

This module defines configuration dataclasses for controlling
PDF generation behavior and branding options.
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class BrandingConfig:
    """Branding configuration for PDF reports.

    Attributes
    ----------
    company_name : str
        Company name for header/footer.
    project_title : str
        Project title for title page.
    logo_path : Path | None
        Path to company logo image (PNG/JPG/PDF) for header.
    subtitle : str
        Optional subtitle for title page.
    author : str
        Report author name.
    titlepage_background : Path | None
        Path to title page background image (PDF recommended).
    footer_text : str
        Custom footer center text (confidentiality notice).
    """

    company_name: str = ""
    project_title: str = "PLC Code Analysis Report"
    logo_path: Path | None = None
    subtitle: str = ""
    author: str = ""
    titlepage_background: Path | None = None
    footer_text: str = "All rights reserved."


@dataclass
class PDFExportConfig:
    """Configuration for PDF export.

    Attributes
    ----------
    output_path : Path
        Output path for the PDF file.
    branding : BrandingConfig
        Branding options.
    include_quality : bool
        Include quality analysis section.
    include_tests : bool
        Include test results section.
    include_toc : bool
        Include table of contents.
    report_date : date | None
        Report date (defaults to today).
    pandoc_path : str
        Path to pandoc executable.
    eisvogel_template : Path | None
        Path to eisvogel template (uses default if None).
    template_dir : Path | None
        Directory containing template assets (Images/, Templates/).
        If provided, uses a custom template from this directory.
    """

    output_path: Path = field(default_factory=lambda: Path("report.pdf"))
    branding: BrandingConfig = field(default_factory=BrandingConfig)
    include_quality: bool = True
    include_tests: bool = True
    include_toc: bool = True
    report_date: date | None = None
    pandoc_path: str = "pandoc"
    eisvogel_template: Path | None = None
    template_dir: Path | None = None


@dataclass
class PDFExportResult:
    """Result of PDF export operation.

    Attributes
    ----------
    success : bool
        Whether export succeeded.
    output_path : Path | None
        Path to generated PDF.
    error : str | None
        Error message if failed.
    warnings : list[str]
        Non-fatal warnings.
    markdown_content : str
        Generated markdown content (for debugging or intermediate output).
    """

    success: bool = True
    output_path: Path | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    markdown_content: str = ""
