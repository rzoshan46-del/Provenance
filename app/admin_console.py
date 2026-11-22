"""
app/admin_console.py — a real /admin dashboard (replaces the placeholder page).

Admin-only. Shows: project review counts and queue, users by role, ledger health and
recent activity, credentials issued/revoked, AI gateway usage, and deployment checks.
It never shows a confidential brief, an email address or a secret.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request

import app.ledger as ledger
from app.config import (
    get_auth_mode,
    get_base_url,
    get_database_url,
    get_session_secret,
    is_production,
)
from app.db import query_all, query_one
from app.deps import current_user


def _count(sql: str, params: tuple = ()) -> int:
    try:
        row = query_one(sql, params)
        return dict(row)["n"] if row else 0
    except Exception:
        return 0


def deployment_checks() -> List[Dict[str, Any]]:
    base = get_base_url()
    db = get_database_url()
    prod = is_production()
    persistent_db = db.startswith("/") or db.startswith("postgres")
    return [
        {
            "label": "SESSION_SECRET is not the default value",
            "ok": get_session_secret() != "change-me-in-production",
            "detail": "set a long random value in your hosting variables",
        },
        {
            "label": "APP_BASE_URL points to the public address",
            "ok": "127.0.0.1" not in base and "localhost" not in base,
            "detail": "QR codes and links use this address",
        },
        {
            "label": "Database file is on a persistent path",
            "ok": (not prod) or persistent_db,
            "detail": "use a volume (for example /data/provenance.db) so redeploys keep data",
        },
        {
            "label": "Production mode",
            "ok": prod,
            "detail": "APP_ENV=production" if prod else "APP_ENV is not production",
        },
        {
            "label": "Demo mode is off",
            "ok": not ledger.demo_mode(),
            "detail": "demo mode lets anyone switch role and reset data (fine for a live demo, not for real users)",
        },
        {
            "label": "Sign-in is real (not demo personas)",
            "ok": get_auth_mode() == "google",
            "detail": f"AUTH_MODE={get_auth_mode()}",
        },
    ]


def build_router(templates) -> APIRouter:
    router = APIRouter()

    @router.get("/admin", include_in_schema=False)
    def admin_console(request: Request, user: Any = Depends(current_user)):

        if not user:
            raise HTTPException(status_code=403, detail="Forbidden: administrator access required")
        if user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Forbidden: administrator access required")
        from app import reviews

        all_users = query_all("SELECT * FROM users ORDER BY id ASC")
        users_by_role = [
            dict(r)
            for r in query_all(
                "SELECT role, COUNT(*) AS n FROM users GROUP BY role ORDER BY role"
            )
        ]
        chain = ledger.verify()
        recent = [
            dict(r)
            for r in query_all(
                "SELECT id, action, timestamp, project_id FROM ledger_entries ORDER BY id DESC LIMIT 8"
            )
        ]
        rows = reviews._queue_rows()
        ai_by_route = [
            dict(r)
            for r in query_all(
                "SELECT model_route, COUNT(*) AS n FROM ai_calls GROUP BY model_route"
            )
        ]
        ctx = {
            "user": user,
            "all_users": all_users,
            "title": "Admin Console",
            "review_counts": reviews.counts(),
            "pending": [r for r in rows if r["state"] == "pending"][:5],
            "users_by_role": users_by_role,
            "chain": chain,
            "ledger_count": _count("SELECT COUNT(*) AS n FROM ledger_entries"),
            "recent": recent,
            "credentials_issued": _count("SELECT COUNT(*) AS n FROM credentials"),
            "credentials_revoked": _count(
                "SELECT COUNT(*) AS n FROM credential_revocations"
            ),
            "ai_total": sum(r["n"] for r in ai_by_route),
            "ai_by_route": ai_by_route,
            "checks": deployment_checks(),
        }
        return templates.TemplateResponse(request, "admin_console.html", ctx)

    return router
