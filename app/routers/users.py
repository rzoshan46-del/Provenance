"""User‑related API routes.
Provides endpoints to fetch the current user's profile and to update profile fields.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from app.deps import current_user
from app.db import query_one, execute
from typing import Optional

router = APIRouter()

@router.get("/me")
async def get_my_profile(request: Request, user: Optional[dict] = Depends(current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # Load profile (creates if missing)
    from app.profiles import get_or_create_profile
    profile = get_or_create_profile(user["id"])
    return JSONResponse(content=profile)

@router.post("/profile")
async def update_profile(request: Request, data: dict, user: Optional[dict] = Depends(current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # Allowed fields
    allowed = {"public_profile", "show_institution", "show_credentials", "role"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields provided")
    set_clause = ", ".join([f"{k} = ?" for k in updates])
    params = list(updates.values()) + [user["id"]]
    execute(f"UPDATE profiles SET {set_clause} WHERE user_id = ?", tuple(params))
    # Return updated profile
    from app.profiles import get_profile
    prof = get_profile(user["id"])
    return JSONResponse(content=prof)
