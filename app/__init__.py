"""Provenance application package.
Provides a FastAPI factory to configure common middleware.
"""

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from .config import get_session_secret, is_production


def create_app(lifespan: callable | None = None) -> FastAPI:
    """Factory to create the FastAPI application with session middleware.
    Accepts an optional ``lifespan`` asynccontextmanager to preserve startup logic.
    """
    kwargs = {}
    if lifespan is not None:
        kwargs["lifespan"] = lifespan
    app = FastAPI(
        title="CritX",
        description="Collaborative Research Ecosystem",
        **kwargs,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=get_session_secret(),
        same_site="lax",
        https_only=is_production(),
    )
    return app
