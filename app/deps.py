import sqlite3
from typing import Callable, Optional
from fastapi import Depends, HTTPException, Request
from app.config import get_auth_mode
from app.db import query_one


def current_user(request: Request) -> Optional[sqlite3.Row]:
    """Read the active authenticated user from the session or the demo persona cookie."""
    user_id = None

    if request.cookies.get("session_user_id"):
        try:
            user_id = int(request.cookies.get("session_user_id"))
        except (ValueError, TypeError):
            user_id = None

    if user_id is None and get_auth_mode() == "demo":
        persona_id = request.cookies.get("persona_id")
        if not persona_id:
            return None
        try:
            user_id = int(persona_id)
        except (ValueError, TypeError):
            return None

    if user_id is None:
        return None

    return query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def require_role(*roles: str) -> Callable:
    """FastAPI dependency to enforce access control based on user role."""
    def role_checker(user: Optional[sqlite3.Row] = Depends(current_user)) -> sqlite3.Row:
        if not user or user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Forbidden: Insufficient privileges")
        return user

    return role_checker
