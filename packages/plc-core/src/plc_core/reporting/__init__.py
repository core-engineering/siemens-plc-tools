"""Reporting framework for PLC tools.

This module provides common data structures and utilities for generating
reports across PLC tool packages.

Example
-------
>>> from plc_core.reporting import Severity, Finding, Report
>>> finding = Finding(
...     title="Variable naming",
...     severity=Severity.WARNING,
...     message="Variable name does not follow convention",
...     location="MyBlock:15",
... )
"""

from plc_core.reporting.markdown import MarkdownRenderer
from plc_core.reporting.models import Finding, Report, ReportSection, Severity
from plc_core.reporting.pdf import PdfExporter

__all__ = [
    "Severity",
    "Finding",
    "Report",
    "ReportSection",
    "MarkdownRenderer",
    "PdfExporter",
]
