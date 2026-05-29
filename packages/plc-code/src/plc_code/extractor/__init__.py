"""Documentation extraction module.

This module provides tools to extract documentation metadata from parsed
SCL blocks, including header information, descriptions, and variable interfaces.
"""

from plc_code.extractor.header import (
    ExtractedHeader,
    HeaderExtractor,
    extract_header,
    extract_header_info,
)
from plc_code.extractor.interface import (
    ExtractedInterface,
    InterfaceExtractor,
    InterfaceSection,
    InterfaceVariable,
    UDTField,
    extract_interface,
)

__all__ = [
    "ExtractedHeader",
    "HeaderExtractor",
    "extract_header",
    "extract_header_info",
    "ExtractedInterface",
    "InterfaceExtractor",
    "InterfaceSection",
    "InterfaceVariable",
    "UDTField",
    "extract_interface",
]
