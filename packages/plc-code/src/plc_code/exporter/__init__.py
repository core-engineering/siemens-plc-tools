"""Export functionality for SCL documentation and parameter tables.

This module provides:
- PDF report generation from quality analysis and test results (pandoc + eisvogel)
- Parameter table document generation from TIA Portal XML exports (python-docx)

PDF generation requires:
- pandoc >= 2.19 (https://pandoc.org/installing.html)
- TeX distribution with xelatex (TeX Live recommended)
- eisvogel template (https://github.com/Wandmalfarbe/pandoc-latex-template)

Parameter table generation requires:
- python-docx >= 1.0.0

Examples
--------
>>> from plc_code.exporter import PDFGenerator, PDFExportConfig, BrandingConfig
>>> config = PDFExportConfig(output_path=Path("report.pdf"), branding=BrandingConfig())
>>> result = PDFGenerator(config).generate(analysis_result, test_result)

>>> from plc_code.exporter import generate_params_document, load_params_config
>>> config = load_params_config(Path("plc-program-parameters-export.yaml"))
>>> result = generate_params_document(config)
"""

from plc_code.exporter.models import (
    BrandingConfig,
    PDFExportConfig,
    PDFExportResult,
)
from plc_code.exporter.param_config import ParamsExportConfig, load_params_config
from plc_code.exporter.param_parser import ParameterEntry, build_type_registry, parse_parameter_xml
from plc_code.exporter.params_generator import GenerationResult, generate_params_document
from plc_code.exporter.pdf_generator import PDFGenerator
from plc_code.exporter.templates import ReportMarkdownGenerator

__all__ = [
    "PDFGenerator",
    "PDFExportConfig",
    "BrandingConfig",
    "PDFExportResult",
    "ReportMarkdownGenerator",
    "ParameterEntry",
    "build_type_registry",
    "parse_parameter_xml",
    "ParamsExportConfig",
    "load_params_config",
    "GenerationResult",
    "generate_params_document",
]
