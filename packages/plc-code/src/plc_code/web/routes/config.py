"""Configuration API routes."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from ..schemas import ConfigResponse, ConfigUpdate
from ..services import get_service

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=ConfigResponse)
async def get_config(request: Request) -> ConfigResponse:
    """Get current project configuration.

    Returns
    -------
    ConfigResponse
        Current configuration including source path.
    """
    service = get_service()
    docs_available = getattr(request.app.state, "docs_available", False)

    # Try to load from plc.yaml if no source path set
    if not service.source_path:
        try:
            from plc_code.core.config import load_config

            config = load_config()
            service.set_source_path(config.source_path)
            return ConfigResponse(
                name=config.name,
                code=config.code,
                source_path=str(config.source_path),
                has_config=True,
                docs_available=docs_available,
            )
        except FileNotFoundError:
            return ConfigResponse(has_config=False, docs_available=docs_available)

    return ConfigResponse(
        source_path=str(service.source_path),
        has_config=True,
        docs_available=docs_available,
    )


@router.post("", response_model=ConfigResponse)
async def set_config(config: ConfigUpdate, request: Request) -> ConfigResponse:
    """Set project configuration.

    Parameters
    ----------
    config : ConfigUpdate
        New configuration values.

    Returns
    -------
    ConfigResponse
        Updated configuration.
    """
    path = Path(config.source_path)

    if not path.exists():
        raise HTTPException(status_code=400, detail=f"Path does not exist: {config.source_path}")

    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {config.source_path}")

    service = get_service()
    service.set_source_path(path)
    docs_available = getattr(request.app.state, "docs_available", False)

    return ConfigResponse(
        source_path=str(path),
        has_config=True,
        docs_available=docs_available,
    )
