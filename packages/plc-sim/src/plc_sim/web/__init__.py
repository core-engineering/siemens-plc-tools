"""Web interface for OPC UA simulation.

Provides FastAPI routes and Vue.js interface for live PLC interaction.
"""

from plc_sim.web.routes import sim_router
from plc_sim.web.services import SimService, get_sim_service

__all__ = [
    "sim_router",
    "SimService",
    "get_sim_service",
]
