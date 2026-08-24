"""PLC Core: Shared utilities, models, and configuration for PLC tools.

This package provides the foundation for all PLC tool packages including:

- Configuration loading and management
- Shared data models (PLCAddress, DataType, IOCategory)
- CLI framework with plugin discovery
- Reporting utilities (Severity, Finding, Report)

Example
-------
>>> from plc_core.config import find_config_file, load_config
>>> from plc_core.models import PLCAddress, DataType, IOCategory
>>> from plc_core.reporting import Severity, Finding
"""

__version__ = "0.4.0"

# Re-export commonly used items
from plc_core.config import (
    BaseConfig,
    PathsConfig,
    find_config_file,
    load_yaml,
)
from plc_core.models import (
    DataType,
    IOCategory,
    PLCAddress,
)
from plc_core.reporting import (
    Finding,
    Report,
    ReportSection,
    Severity,
)

__all__ = [
    "__version__",
    # Config
    "BaseConfig",
    "PathsConfig",
    "find_config_file",
    "load_yaml",
    # Models
    "PLCAddress",
    "DataType",
    "IOCategory",
    # Reporting
    "Severity",
    "Finding",
    "Report",
    "ReportSection",
]
