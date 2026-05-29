"""Shared data models for PLC tools.

This module provides common data models used across PLC tool packages.

Example
-------
>>> from plc_core.models import PLCAddress, DataType, IOCategory
>>> addr = PLCAddress.from_s7_format("%I1.0")
>>> print(addr.to_iol_format())
E 1.0
"""

from plc_core.models.address import PLCAddress
from plc_core.models.types import DataType, IOCategory

__all__ = [
    "PLCAddress",
    "DataType",
    "IOCategory",
]
