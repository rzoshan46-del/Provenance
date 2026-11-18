"""Health check router.
Provides a simple endpoint to verify service status and database connectivity.
"""

from fastapi import APIRouter
from app.db import query_one

router = APIRouter()

@router.get("/health")
async def health_check():
    table_row = query_one("SELECT count(*) as count FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    user_row = query_one("SELECT count(*) as count FROM users")
    tables = table_row["count"] if table_row else 0
    users = user_row["count"] if user_row else 0
    return {"status": "ok", "tables": tables, "users": users}
