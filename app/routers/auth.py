"""Authentication routes for CritX backend.
Provides Google OAuth login flow and demo persona switching.
"""

import os
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER
from app.config import google_auth_enabled, get_base_url
from app.deps import current_user
from app.db import query_one, execute

router = APIRouter()

# Google OAuth is already configured globally as `oauth` in main.py.
# These endpoints only coordinate the flow.

@router.get("/auth/google/login")
async def google_login(request: Request):
    if not google_auth_enabled():
        raise HTTPException(status_code=503, detail="Google OAuth not configured.")
    # Ensure redirect URI matches host
    base = get_base_url()
    redirect_uri = f"{base}/auth/google/callback"
    return await request.app.state.oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/auth/google/callback")
async def google_callback(request: Request):
    if not google_auth_enabled():
        raise HTTPException(status_code=503, detail="Google OAuth not configured.")
    try:
        token = await request.app.state.oauth.google.authorize_access_token(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    userinfo = token.get("userinfo") or await request.app.state.oauth.google.userinfo(token=token)
    email = (userinfo.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Google account did not return an email.")
    # Find or create user
    user = query_one("SELECT * FROM users WHERE lower(email) = ?", (email,))
    if not user:
        name = userinfo.get("name") or email.split("@")[0]
        user_id = execute(
            """
            INSERT INTO users (name, email, role, verification_level, institution, skills, conflict_orgs)
            VALUES (?, ?, 'student', 1, 'Google Authenticated', '[\"python\",\"research\"]', '[]')
            """,
            (name, email),
        )
        user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    # Set session cookie
    response = RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)
    response.set_cookie(key="session_user_id", value=str(user["id"]), path="/", httponly=True, samesite="lax")
    # Clear persona cookie if any
    response.delete_cookie(key="persona_id", path="/")
    return response

@router.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
    response.delete_cookie(key="session_user_id", path="/")
    response.delete_cookie(key="persona_id", path="/")
    return response
