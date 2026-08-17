"""Router registry — imported by the app factory."""

from hermes_panel.routes.codex import router as codex_router
from hermes_panel.routes.model import router as model_router
from hermes_panel.routes.session import router as session_router
from hermes_panel.routes.system import router as system_router
from hermes_panel.routes.zalo import router as zalo_router

all_routers = [
    session_router,
    system_router,
    codex_router,
    zalo_router,
    model_router,
]

__all__ = ["all_routers"]
