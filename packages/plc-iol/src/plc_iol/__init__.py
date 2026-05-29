"""PLC IOL - I/O List management for PLC projects.

This package provides tools for managing PLC TAGS and IOL documents.
"""

# Import shared types from plc_core
from plc_core.models import DataType, IOCategory, PLCAddress

# Import local components
from plc_iol.core.config import ProjectConfig, load_config
from plc_iol.core.database import DatabaseManager
from plc_iol.core.models import IODatabase, IOPoint

__version__ = "0.3.0"

__all__ = [
    # Shared types (from plc_core)
    "IOCategory",
    "DataType",
    "PLCAddress",
    # Local models
    "IOPoint",
    "IODatabase",
    "ProjectConfig",
    "load_config",
    "DatabaseManager",
]
