"""API routes for the web interface."""

from .analysis import router as analysis_router
from .blocks import router as blocks_router
from .config import router as config_router
from .tags import router as tags_router
from .xref import router as xref_router

__all__ = ["blocks_router", "analysis_router", "config_router", "tags_router", "xref_router"]
