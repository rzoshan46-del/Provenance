"""FastAPI dependencies for authentication and role verification."""
import sqlite3
import time
import secrets
from collections import defaultdict
from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request

from app.config import get_auth_mode, demo_mode_enabled, is_production
from app.db import query_one

_rate_limit_records = defaultdict(list)


def rate_limit(max_requests: int = 60, window_seconds: int = 60):
    async def limiter(request: Request):
        client_ip = request.client.host if request.client else "unknown"
        user_id = request.session.get("user_id") if hasattr(request, "session") else None
        key = f"{client_ip}:{user_id or 'anon'}"
        now = time.time()
        reqs = [t for t in _rate_limit_records[key] if now - t < window_seconds]
        if len(reqs) >= max_requests:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Please wait a moment.")
        reqs.append(now)
        _rate_limit_records[key] = reqs
        return True

    return limiter


def get_csrf_token(request: Request) -> str:
    token = None
    try:
        if hasattr(request, "session"):
            token = request.session.get("csrf_token")
            if not token:
                token = secrets.token_hex(16)
                request.session["csrf_token"] = token
    except Exception:
        pass
    if not token:
        token = request.cookies.get("csrf_token")
    return token or secrets.token_hex(16)


async def csrf_protect(request: Request):
    """Enforce CSRF check on state-mutating requests."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True

    expected = None
    try:
        if hasattr(request, "session"):
            expected = request.session.get("csrf_token")
    except Exception:
        pass
    if not expected:
        expected = request.cookies.get("csrf_token")

    # If an expected CSRF token is present in the session/cookie, verify the submitted token
    if expected:
        header_token = request.headers.get("X-CSRF-Token")
        form_token = None
        try:
            content_type = request.headers.get("content-type", "")
            if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
                form = await request.form()
                form_token = form.get("csrf_token")
        except Exception:
            pass

        submitted = header_token or form_token
        if not submitted or submitted != expected:
            raise HTTPException(status_code=403, detail="CSRF token mismatch or missing.")

    return True


def current_user(request: Request) -> Optional[sqlite3.Row]:
    """Read the active authenticated user from the signed server session or demo persona."""
    user_id = None
    try:
        user_id = request.session.get("user_id")
    except AssertionError:
        user_id = None

    if user_id is None:
        session_cookie = request.cookies.get("session_user_id")
        if session_cookie:
            try:
                user_id = int(session_cookie)
            except (ValueError, TypeError):
                user_id = None

    # Demo persona switching is only permitted in development demo mode
    if user_id is None and get_auth_mode() == "demo" and demo_mode_enabled() and not is_production():
        persona_id = request.cookies.get("persona_id")
        if persona_id:
            try:
                user_id = int(persona_id)
            except (ValueError, TypeError):
                user_id = None

    if user_id is None:
        return None

    user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not user:
        return None

    # Stale session check after signout-all
    if "session_epoch" in user.keys() and user["session_epoch"] is not None:
        user_epoch = user["session_epoch"]
        if user_epoch > 0:
            sess_epoch = None
            try:
                if hasattr(request, "session"):
                    sess_epoch = request.session.get("session_epoch")
            except Exception:
                pass
            if sess_epoch is None:
                cookie_epoch = request.cookies.get("session_epoch")
                if cookie_epoch is not None:
                    try:
                        sess_epoch = int(cookie_epoch)
                    except Exception:
                        sess_epoch = None

            if sess_epoch is None or sess_epoch < user_epoch:
                return None

    return user


def require_role(*roles: str) -> Callable:
    """FastAPI dependency to enforce access control based on user role."""

    def role_checker(
        user: Optional[sqlite3.Row] = Depends(current_user),
    ) -> sqlite3.Row:
        if not user:
            raise HTTPException(
                status_code=401, detail="Not authenticated"
            )
        if user["role"] not in roles:
            raise HTTPException(
                status_code=403, detail="Forbidden: Insufficient privileges"
            )
        return user

    return role_checker
