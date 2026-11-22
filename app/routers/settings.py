"""settings.py module."""
import json
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import app.profiles as profiles
from app.db import execute, query_all
from app.deps import csrf_protect, current_user, rate_limit

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

import app.credits as _credits_mod
import app.ledger as _ledger_mod
templates.env.globals["user_credits"] = _credits_mod.total
templates.env.globals["demo_mode"] = _ledger_mod.demo_mode
templates.env.globals["get_unread_notification_count"] = profiles.get_unread_notification_count
templates.env.filters["from_json"] = lambda s: json.loads(s) if s else []


@router.get("/settings/profile")
async def settings_profile_get(
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    if not user:
        return RedirectResponse(url="/login?next=/settings/profile", status_code=303)

    prof = profiles.get_or_create_profile(user["id"])
    completeness = profiles.get_profile_completeness(prof)
    ai_stats = profiles.get_ai_transparency_stats(user["id"])

    # User contributions for pinned selector
    user_conts = query_all(
        "SELECT id, artefact_title, ai_declaration, impact_weight, created_at FROM contributions WHERE author_id = ? ORDER BY id DESC",
        (user["id"],),
    )
    pinned_ids = []
    try:
        pinned_ids = json.loads(prof.get("pinned_contributions") or "[]")
    except Exception:
        pass

    skills_list = []
    try:
        skills_list = json.loads(prof.get("skills") or "[]")
    except Exception:
        pass

    initials = profiles.get_initials(prof.get("display_name") or user["name"])
    csrf_token = request.session.get("csrf_token") if hasattr(request, "session") else ""

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            {
                "user": dict(user),
                "profile": prof,
                "completeness": completeness,
                "ai_stats": ai_stats,
            }
        )

    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "tab": "profile",
            "user": user,
            "all_users": all_users,
            "profile": prof,
            "completeness": completeness,
            "ai_stats": ai_stats,
            "user_conts": user_conts,
            "pinned_ids": pinned_ids,
            "skills_str": ", ".join(skills_list),
            "initials": initials,
            "csrf_token": csrf_token,
        },
    )


@router.post("/settings/profile", dependencies=[Depends(rate_limit(30, 60))])
async def settings_profile_post(
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    display_name: str = Form(""),
    handle: str = Form(""),
    headline: str = Form(""),
    bio: str = Form(""),
    location: str = Form(""),
    skills: str = Form(""),
    github_url: str = Form(""),
    linkedin_url: str = Form(""),
    portfolio_url: str = Form(""),
    instagram_url: str = Form(""),
    x_url: str = Form(""),
    youtube_url: str = Form(""),
    scholar_url: str = Form(""),
    orcid_url: str = Form(""),
    pinned_1: Optional[str] = Form(None),
    pinned_2: Optional[str] = Form(None),
    pinned_3: Optional[str] = Form(None),
    is_public: Optional[str] = Form(None),
    show_institution: Optional[str] = Form(None),
    show_credentials: Optional[str] = Form(None),
):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    await csrf_protect(request)

    # Handle update if provided and changed
    handle_clean = handle.strip().lower()
    prof = profiles.get_or_create_profile(user["id"])
    auth_at = request.session.get("auth_at") if hasattr(request, "session") else None

    if handle_clean and handle_clean != (prof.get("handle") or "").lower():
        try:
            profiles.update_handle(user["id"], handle_clean, auth_at=auth_at)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Pinned contributions (max 3)
    pins = [p for p in (pinned_1, pinned_2, pinned_3) if p and str(p).isdigit()]
    pinned_json = json.dumps([int(p) for p in pins[:3]])

    try:
        profiles.update_profile(
            user_id=user["id"],
            name=user["name"],
            headline=headline,
            bio=bio,
            institution=user["institution"] or "",
            skills_raw=skills,
            github_url=github_url,
            linkedin_url=linkedin_url,
            portfolio_url=portfolio_url,
            is_public=bool(is_public),
            show_institution=bool(show_institution),
            show_credentials=bool(show_credentials),
            display_name=display_name,
            location=location,
            instagram_url=instagram_url,
            x_url=x_url,
            youtube_url=youtube_url,
            scholar_url=scholar_url,
            orcid_url=orcid_url,
            pinned_contributions=pinned_json,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"status": "ok", "message": "Profile updated successfully"})

    return RedirectResponse(
        url="/settings/profile?msg=Profile+updated+successfully!", status_code=303
    )


@router.get("/settings/account")
async def settings_account_get(
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    if not user:
        return RedirectResponse(url="/login?next=/settings/account", status_code=303)

    prof = profiles.get_or_create_profile(user["id"])
    completeness = profiles.get_profile_completeness(prof)
    initials = profiles.get_initials(user["name"])
    csrf_token = request.session.get("csrf_token") if hasattr(request, "session") else ""

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"user": dict(user), "profile": prof})

    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "tab": "account",
            "user": user,
            "all_users": all_users,
            "profile": prof,
            "completeness": completeness,
            "initials": initials,
            "csrf_token": csrf_token,
        },
    )


@router.post("/settings/account", dependencies=[Depends(rate_limit(30, 60))])
async def settings_account_post(
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    name: str = Form(...),
    institution: str = Form(""),
):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    await csrf_protect(request)
    execute(
        "UPDATE users SET name = ?, institution = ? WHERE id = ?",
        (name.strip(), institution.strip(), user["id"]),
    )
    profiles.record_account_event(user["id"], "account_update")

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"status": "ok", "message": "Account updated"})
    return RedirectResponse(
        url="/settings/account?msg=Account+settings+saved!", status_code=303
    )


@router.get("/settings/privacy")
async def settings_privacy_get(
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    if not user:
        return RedirectResponse(url="/login?next=/settings/privacy", status_code=303)

    prof = profiles.get_or_create_profile(user["id"])
    completeness = profiles.get_profile_completeness(prof)
    initials = profiles.get_initials(user["name"])
    csrf_token = request.session.get("csrf_token") if hasattr(request, "session") else ""

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"profile": prof})

    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "tab": "privacy",
            "user": user,
            "all_users": all_users,
            "profile": prof,
            "completeness": completeness,
            "initials": initials,
            "csrf_token": csrf_token,
        },
    )


@router.post("/settings/privacy", dependencies=[Depends(rate_limit(30, 60))])
async def settings_privacy_post(
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    is_public: Optional[str] = Form(None),
    show_institution: Optional[str] = Form(None),
    show_credentials: Optional[str] = Form(None),
):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    await csrf_protect(request)
    execute(
        """
        UPDATE user_profiles SET
            is_public = ?,
            show_institution = ?,
            show_credentials = ?
        WHERE user_id = ?
        """,
        (
            1 if is_public else 0,
            1 if show_institution else 0,
            1 if show_credentials else 0,
            user["id"],
        ),
    )
    profiles.record_account_event(user["id"], "privacy_update")

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"status": "ok", "message": "Privacy settings updated"})
    return RedirectResponse(
        url="/settings/privacy?msg=Privacy+settings+updated!", status_code=303
    )


@router.get("/settings/security")
async def settings_security_get(
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    if not user:
        return RedirectResponse(url="/login?next=/settings/security", status_code=303)

    prof = profiles.get_or_create_profile(user["id"])
    completeness = profiles.get_profile_completeness(prof)
    events = query_all(
        "SELECT event, created_at FROM account_events WHERE user_id = ? ORDER BY id DESC LIMIT 20",
        (user["id"],),
    )
    initials = profiles.get_initials(user["name"])
    csrf_token = request.session.get("csrf_token") if hasattr(request, "session") else ""

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            {
                "session_epoch": user["session_epoch"] if "session_epoch" in user.keys() else 0,
                "events": [dict(e) for e in events],
            }
        )

    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "tab": "security",
            "user": user,
            "all_users": all_users,
            "profile": prof,
            "completeness": completeness,
            "events": events,
            "initials": initials,
            "csrf_token": csrf_token,
        },
    )


@router.post("/settings/security/signout-all", dependencies=[Depends(rate_limit(10, 60))])
async def settings_signout_all(
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    await csrf_protect(request)
    execute(
        "UPDATE users SET session_epoch = session_epoch + 1 WHERE id = ?",
        (user["id"],),
    )
    profiles.record_account_event(user["id"], "signout_all")

    if hasattr(request, "session"):
        request.session.clear()

    response = RedirectResponse(
        url="/login?msg=Signed+out+of+all+devices+successfully.", status_code=303
    )
    response.delete_cookie(key="session_user_id", path="/")
    response.delete_cookie(key="persona_id", path="/")
    response.delete_cookie(key="session_epoch", path="/")
    return response


@router.get("/settings/notifications")
async def settings_notifications_get(
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    if not user:
        return RedirectResponse(url="/login?next=/settings/notifications", status_code=303)

    prof = profiles.get_or_create_profile(user["id"])
    completeness = profiles.get_profile_completeness(prof)
    notes = profiles.get_user_notifications(user["id"])
    initials = profiles.get_initials(user["name"])
    csrf_token = request.session.get("csrf_token") if hasattr(request, "session") else ""

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"notifications": notes})

    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "tab": "notifications",
            "user": user,
            "all_users": all_users,
            "profile": prof,
            "completeness": completeness,
            "notifications": notes,
            "initials": initials,
            "csrf_token": csrf_token,
        },
    )


@router.post("/settings/notifications/read", dependencies=[Depends(rate_limit(30, 60))])
async def settings_notifications_read(
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    await csrf_protect(request)
    profiles.mark_notifications_read(user["id"])
    return JSONResponse({"status": "ok"})


@router.get("/settings/data")
async def settings_data_get(
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    if not user:
        return RedirectResponse(url="/login?next=/settings/data", status_code=303)

    prof = profiles.get_or_create_profile(user["id"])
    completeness = profiles.get_profile_completeness(prof)
    initials = profiles.get_initials(user["name"])
    csrf_token = request.session.get("csrf_token") if hasattr(request, "session") else ""

    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "tab": "data",
            "user": user,
            "all_users": all_users,
            "profile": prof,
            "completeness": completeness,
            "initials": initials,
            "csrf_token": csrf_token,
        },
    )


@router.get("/settings/data/export", dependencies=[Depends(rate_limit(10, 60))])
async def settings_data_export(
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    data = profiles.export_user_data(user["id"])
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="critx_export_user_{user["id"]}.json"'},
    )


@router.post("/settings/account/delete", dependencies=[Depends(rate_limit(5, 60))])
async def settings_account_delete(
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    confirm_handle: str = Form(...),
):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    await csrf_protect(request)
    auth_at = request.session.get("auth_at") if hasattr(request, "session") else None

    try:
        profiles.delete_account(user["id"], confirm_handle, auth_at=auth_at)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    if hasattr(request, "session"):
        request.session.clear()

    response = RedirectResponse(url="/?msg=Account+deleted+successfully", status_code=303)
    response.delete_cookie(key="session_user_id", path="/")
    response.delete_cookie(key="persona_id", path="/")
    response.delete_cookie(key="session_epoch", path="/")
    return response
