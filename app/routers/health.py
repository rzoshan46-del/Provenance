"""Health check router.
Provides a simple endpoint to verify service status and database connectivity.
"""

from fastapi import APIRouter
from app.db import get_database_status

router = APIRouter()

@router.get("/health")
async def health_check():
    return get_database_status()
