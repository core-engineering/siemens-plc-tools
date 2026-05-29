"""Documentation project management module.

This module provides high-level orchestration for generating documentation
from TIA Portal exports, including project discovery, batch processing,
and output organization.
"""

from plc_code.project.config import (
    OutputConfig,
    ProjectConfig,
)
from plc_code.project.discovery import (
    BlockFile,
    discover_blocks,
)
from plc_code.project.pipeline import (
    DocumentationPipeline,
    ProcessingResult,
    generate_project_documentation,
)

__all__ = [
    "BlockFile",
    "DocumentationPipeline",
    "OutputConfig",
    "ProcessingResult",
    "ProjectConfig",
    "discover_blocks",
    "generate_project_documentation",
]
