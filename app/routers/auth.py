"""Authentication routes for CritX backend.
Provides Google OAuth login flow and demo persona switching.
"""

import os
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER
from pydantic import BaseModel, Field, field_validator
import hashlib
import secrets
from app.config import google_auth_enabled, get_base_url, is_production
from app.deps import current_user
from app.db import query_one, execute

router = APIRouter()


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern="^(student|expert|sponsor)$")

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("Invalid email address")
        return value


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("Invalid email address")
        return value


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 240_000)
    return f"pbkdf2_sha256$240000${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, digest = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("ascii"), int(rounds)
        ).hex()
        return secrets.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False


@router.post("/api/auth/register", status_code=201)
def register(data: RegisterIn):
    email = str(data.email).strip().lower()
    existing = query_one("SELECT id FROM users WHERE lower(email) = ?", (email,))
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user_id = execute(
        """
        INSERT INTO users (
            name, email, password_hash, role, verification_level,
            institution, is_minor, guardian_consent, conflict_orgs, skills, bio
        ) VALUES (?, ?, ?, ?, 0, '', 0, 0, '[]', '[]', '')
        """,
        (data.name.strip(), email, hash_password(data.password), data.role),
    )
    return {"id": user_id, "name": data.name.strip(), "email": email, "role": data.role}


@router.post("/api/auth/login")
def login(request: Request, data: LoginIn):
    email = str(data.email).strip().lower()
    user = query_one("SELECT * FROM users WHERE lower(email) = ?", (email,))
    password_hash = user["password_hash"] if user and "password_hash" in user.keys() else None
    if not user or not password_hash or not verify_password(data.password, password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    import datetime
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    epoch = user["session_epoch"] if "session_epoch" in user.keys() and user["session_epoch"] is not None else 0
    if hasattr(request, "session"):
        request.session["user_id"] = user["id"]
        request.session["session_epoch"] = epoch
        request.session["auth_at"] = now_iso
    response = __import__("fastapi").responses.JSONResponse(
        content={
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
        }
    )
    response.set_cookie(key="session_epoch", value=str(epoch), path="/")
    response.delete_cookie(key="persona_id", path="/")
    return response


@router.get("/api/auth/me")
def auth_me(user=Depends(current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}


@router.post("/api/auth/logout")
def api_logout(request: Request):
    if hasattr(request, "session"):
        request.session.clear()
    from fastapi.responses import JSONResponse
    response = JSONResponse({"ok": True})
    response.delete_cookie(key="session_user_id", path="/")
    response.delete_cookie(key="persona_id", path="/")
    return response

@router.get("/logout")
async def logout(request: Request):
    if hasattr(request, "session"):
        request.session.clear()
    response = RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
    response.delete_cookie(key="session_user_id", path="/")
    response.delete_cookie(key="persona_id", path="/")
    return response
