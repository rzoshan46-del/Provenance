import sqlite3
from typing import Callable, Optional
from fastapi import Depends, HTTPException, Request
from app.db import query_one


def current_user(request: Request) -> Optional[sqlite3.Row]:
    """Read persona_id cookie and return the matching user row or None."""
    persona_id = request.cookies.get("persona_id")
    if not persona_id:
        return None
    try:
        user_id = int(persona_id)
    except (ValueError, TypeError):
        return None
    return query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def require_role(*roles: str) -> Callable:
    """FastAPI dependency to enforce access control based on user role."""
    def role_checker(user: Optional[sqlite3.Row] = Depends(current_user)) -> sqlite3.Row:
        if not user or user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Forbidden: Insufficient privileges")
        return user

    return role_checker
