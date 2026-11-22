"""Provenance application package.
Provides a FastAPI factory to configure common middleware.
"""

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from .config import get_session_secret, is_production, docs_enabled


from typing import Callable

OPENAPI_TAGS = [
    {"name": "Auth", "description": "Authentication and session management"},
    {"name": "Projects", "description": "Project management and memberships"},
    {"name": "Charters", "description": "Project charters and governance"},
    {"name": "Milestones", "description": "Project milestones and deliverables"},
    {"name": "Contributions", "description": "Research contributions and proofs"},
    {"name": "Escrow", "description": "Escrow contracts and milestone payouts"},
    {"name": "Workspace", "description": "Interactive collaborative workspace"},
    {"name": "Credits", "description": "Credit balances and transactions"},
    {"name": "Profile", "description": "User profiles and activity"},
    {"name": "Verify", "description": "Verification and credential checks"},
    {"name": "Admin", "description": "Administrative actions and console"},
    {"name": "System", "description": "System health and status endpoints"},
]

def create_app(lifespan: Callable | None = None) -> FastAPI:
    """Factory to create the FastAPI application with session middleware.
    Accepts an optional ``lifespan`` asynccontextmanager to preserve startup logic.
    """
    kwargs = {}
    if lifespan is not None:
        kwargs["lifespan"] = lifespan
    enabled = docs_enabled()
    app = FastAPI(
        title="Provenance API",
        description="Provenance research collaboration platform API.\nManage projects, contributions, milestones, and verifiable credentials.",
        version="1.0.0",
        openapi_tags=OPENAPI_TAGS if enabled else None,
        docs_url="/docs" if enabled else None,
        redoc_url="/redoc" if enabled else None,
        openapi_url="/openapi.json" if enabled else None,
        **kwargs,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=get_session_secret(),
        same_site="lax",
        https_only=is_production(),
    )
    return app
