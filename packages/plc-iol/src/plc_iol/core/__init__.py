"""Core module - models, configuration, and database.

This module re-exports shared types from plc_core for convenience.
"""

# Import shared types from plc_core
from plc_core.models import DataType, IOCategory, PLCAddress

# Import local models
from plc_iol.core.config import ProjectConfig, load_config
from plc_iol.core.database import DatabaseManager
from plc_iol.core.models import IODatabase, IOPoint
from plc_iol.core.naming import NamingConvention, validate_mnemonic

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
    "NamingConvention",
    "validate_mnemonic",
]
