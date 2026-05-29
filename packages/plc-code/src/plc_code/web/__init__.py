"""Unified PLC Analysis Server.

This module provides a FastAPI-based web application that serves:
- A landing page with navigation at /
- MkDocs documentation at /docs/ (when available)
- The I/O Tag Dependency Explorer at /explorer/
- REST API at /api/

Example usage:
    # Start the server programmatically
    from plc_code.web import create_app
    import uvicorn

    app = create_app(
        source_path=Path("/path/to/plc-program"),
        docs_site_path=Path("/path/to/site"),
    )
    uvicorn.run(app, host="0.0.0.0", port=8080)

    # Or use the CLI command
    $ plc code web --port 8080
"""

from .app import app, create_app
from .services import AnalysisService, get_service, set_source_path

__all__ = [
    "app",
    "create_app",
    "AnalysisService",
    "get_service",
    "set_source_path",
]
