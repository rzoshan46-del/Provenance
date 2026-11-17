"""
app/reviews.py — Project review queue (admin approves sponsor submissions).

Flow:
    sponsor posts a problem  ->  state "pending"  ->  admin decides:
        approve          -> "approved"          (public: students can see and join)
        request_changes  -> "changes_requested" (sponsor edits and resubmits)
        reject           -> "rejected"          (stays hidden)

Design choices (nothing existing is rewritten):
  * Review state lives in its own table, project_reviews, created on first use.
    A project with NO row counts as "approved". That keeps seeded projects, story mode
    and the existing API/tests working exactly as before.
  * Each row is tied to the project's created_at, so a stale row can never hide a
    different project that later reuses the same id (for example after a demo reset).
  * Not-yet-approved projects are hidden from everyone except the owning sponsor
    and admins: the /projects list is filtered and /projects/<id> and
    /api/projects/<id>/... return 404 for everyone else.
  * Admins review the PUBLIC summary only. The confidential brief is never sent to the
    admin pages; only pass/fail results of automated checks about it are shown.
  * Every step writes a ledger entry (ids and short labels only, never free text).

Settings:
  REQUIRE_PROJECT_REVIEW=1   also send projects created via POST /api/projects to review
                             (the sponsor web form always goes to review).
"""

import hashlib
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

import app.ledger as ledger
from app.ai.gateway import redact, scan_injection
from app.db import execute, get_conn, query_all, query_one
from app.deps import current_user, require_role

DECISIONS = {
    "approve": "approved",
    "reject": "rejected",
    "request_changes": "changes_requested",
}
STATE_LABELS = {
    "pending": "Pending review",
    "approved": "Approved",
    "rejected": "Rejected",
    "changes_requested": "Changes requested",
}

MAX_TITLE = 120
MAX_SUMMARY = 1500
MAX_BRIEF = 10000
MAX_NOTE = 500

_PROJECT_PATH = re.compile(r"^/(?:api/)?projects/(\d+)(?:/|$)")


# ─────────────────────────────────────────────
# Table + state helpers
# ─────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _ensure_table() -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS project_reviews (
            project_id INTEGER PRIMARY KEY,
            project_created_at TEXT NOT NULL,
            state TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            decided_at TEXT,
            reviewer_id INTEGER,
            note TEXT
        )
        """
    )


def _review_row(project_id: int) -> Optional[Any]:
    _ensure_table()
    return query_one(
        """
        SELECT r.* FROM project_reviews r
        JOIN projects p ON p.id = r.project_id AND p.created_at = r.project_created_at
        WHERE r.project_id = ?
        """,
        (project_id,),
    )


def state_of(project_id: int) -> str:
    """'approved' when the project has no (valid) review row."""
    row = _review_row(project_id)
    return row["state"] if row else "approved"


def states_map() -> Dict[int, str]:
    _ensure_table()
    rows = query_all(
        """
        SELECT r.project_id AS pid, r.state AS state
        FROM project_reviews r
        JOIN projects p ON p.id = r.project_id AND p.created_at = r.project_created_at
        """
    )
    return {r["pid"]: r["state"] for r in rows}


def filter_listing(rows: List[Any], user: Optional[Any]) -> List[Any]:
    """Keep approved projects, plus the viewer's own projects."""
    states = states_map()
    uid = user["id"] if user else None
    return [
        r
        for r in rows
        if states.get(r["id"], "approved") == "approved"
        or (uid is not None and r["sponsor_id"] == uid)
    ]


def _project(project_id: int) -> Any:
    p = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


def _require_owner(sponsor: Any, project: Any) -> None:
    if (
        not sponsor
        or sponsor["role"] != "sponsor"
        or project["sponsor_id"] != sponsor["id"]
    ):
        raise HTTPException(
            status_code=403, detail="Forbidden: only the owning sponsor can do this"
        )


def _conditional_update(sql: str, params: tuple) -> int:
    """Run an UPDATE and return the number of rows changed (atomic state transitions)."""
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(sql, params)
            return cur.rowcount
    finally:
        conn.close()


# ─────────────────────────────────────────────
# Actions
# ─────────────────────────────────────────────
def mark_pending(project_id: int, sponsor: Any, source: str = "form") -> None:
    """Put a newly created project into the review queue."""
    project = _project(project_id)
    _ensure_table()
    execute(
        """
        INSERT OR REPLACE INTO project_reviews
            (project_id, project_created_at, state, submitted_at, decided_at, reviewer_id, note)
        VALUES (?, ?, 'pending', ?, NULL, NULL, NULL)
        """,
        (project_id, project["created_at"], _now()),
    )
    ledger.append(
        action="project_submitted_for_review",
        actor_id=sponsor["id"],
        actor_type="human",
        project_id=project_id,
        payload={"project_id": project_id, "source": source},
    )


def mark_pending_api(project_id: int, user: Any) -> None:
    """Used by POST /api/projects: only gates when REQUIRE_PROJECT_REVIEW=1."""
    if os.getenv("REQUIRE_PROJECT_REVIEW", "0").strip() == "1" and user:
        mark_pending(project_id, user, source="api")


def decide(admin: Any, project_id: int, decision: str, note: Optional[str]) -> str:
    if decision not in DECISIONS:
        raise HTTPException(
            status_code=400,
            detail="decision must be one of: " + ", ".join(sorted(DECISIONS)),
        )
    _project(project_id)
    row = _review_row(project_id)
    if not row or row["state"] != "pending":
        raise HTTPException(
            status_code=409, detail="This project is not awaiting review"
        )
    note = (note or "").strip()
    if decision != "approve" and len(note) < 5:
        raise HTTPException(
            status_code=400,
            detail="Please add a note (at least 5 characters) so the sponsor knows what to fix",
        )
    new_state = DECISIONS[decision]
    changed = _conditional_update(
        """
        UPDATE project_reviews
        SET state = ?, decided_at = ?, reviewer_id = ?, note = ?
        WHERE project_id = ? AND state = 'pending'
        """,
        (new_state, _now(), admin["id"], note[:MAX_NOTE] or None, project_id),
    )
    if changed != 1:
        raise HTTPException(
            status_code=409, detail="This project is not awaiting review"
        )
    ledger.append(
        action="project_review_decided",
        actor_id=admin["id"],
        actor_type="human",
        project_id=project_id,
        payload={
            "project_id": project_id,
            "decision": decision,
            "reviewer_id": admin["id"],
        },
    )
    return new_state


def resubmit(sponsor: Any, project_id: int) -> None:
    project = _project(project_id)
    _require_owner(sponsor, project)
    changed = _conditional_update(
        """
        UPDATE project_reviews
        SET state = 'pending', submitted_at = ?, decided_at = NULL, reviewer_id = NULL
        WHERE project_id = ? AND state = 'changes_requested'
        """,
        (_now(), project_id),
    )
    if changed != 1:
        raise HTTPException(
            status_code=409,
            detail="Only projects with requested changes can be resubmitted",
        )
    ledger.append(
        action="project_resubmitted",
        actor_id=sponsor["id"],
        actor_type="human",
        project_id=project_id,
        payload={"project_id": project_id},
    )


def edit_project(
    sponsor: Any,
    project_id: int,
    title: str,
    public_summary: str,
    confidential_brief: str,
    resubmit_after: bool,
) -> None:
    project = _project(project_id)
    _require_owner(sponsor, project)
    state = state_of(project_id)
    if state not in ("pending", "changes_requested"):
        raise HTTPException(
            status_code=409, detail="This project can no longer be edited"
        )

    title = (title or "").strip()
    public_summary = (public_summary or "").strip()
    confidential_brief = (confidential_brief or "").strip() or project[
        "confidential_brief"
    ]
    if not title or not public_summary:
        raise HTTPException(
            status_code=400, detail="Title and public summary are required"
        )
    if len(title) > MAX_TITLE:
        raise HTTPException(
            status_code=400, detail=f"Title must be at most {MAX_TITLE} characters"
        )
    if len(public_summary) > MAX_SUMMARY:
        raise HTTPException(
            status_code=400,
            detail=f"Public summary must be at most {MAX_SUMMARY} characters",
        )
    if len(confidential_brief) > MAX_BRIEF:
        raise HTTPException(
            status_code=400,
            detail=f"Confidential brief must be at most {MAX_BRIEF} characters",
        )

    execute(
        "UPDATE projects SET title = ?, public_summary = ?, confidential_brief = ? WHERE id = ?",
        (title, public_summary, confidential_brief, project_id),
    )
    # Never put the brief text in a ledger payload; its hash is enough.
    ledger.append(
        action="project_edited",
        actor_id=sponsor["id"],
        actor_type="human",
        project_id=project_id,
        payload={
            "project_id": project_id,
            "brief_hash": hashlib.sha256(
                confidential_brief.encode("utf-8")
            ).hexdigest(),
        },
    )
    if resubmit_after and state == "changes_requested":
        resubmit(sponsor, project_id)


# ─────────────────────────────────────────────
# Automated pre-checks shown to the admin (the brief itself is never shown)
# ─────────────────────────────────────────────
def automated_checks(title: str, summary: str, brief: str) -> List[Dict[str, Any]]:
    pii_hits = redact(f"{title}\n{summary}")[1]
    inj = scan_injection(f"{title}\n{summary}\n{brief}")
    leak = len(brief) >= 40 and brief[:80].strip().lower() in summary.lower()
    return [
        {
            "label": "No personal data in the public text",
            "ok": pii_hits == 0,
            "detail": "none found"
            if pii_hits == 0
            else f"{pii_hits} possible item(s) (email or phone)",
        },
        {
            "label": "No prompt-injection patterns",
            "ok": not inj,
            "detail": "none found" if not inj else f"{len(inj)} pattern(s) matched",
        },
        {
            "label": "Public summary is substantive",
            "ok": len(summary) >= 40,
            "detail": f"{len(summary)} characters",
        },
        {
            "label": "Confidential brief is not copied into the public summary",
            "ok": not leak,
            "detail": "no overlap"
            if not leak
            else "the start of the brief appears in the summary",
        },
        {
            "label": "Confidential brief is present",
            "ok": len(brief) >= 40,
            "detail": "brief content stays hidden from admins",
        },
    ]


def _queue_rows() -> List[Dict[str, Any]]:
    """All reviewed projects. The brief is used for checks and then dropped."""
    _ensure_table()
    rows = query_all(
        """
        SELECT r.state, r.submitted_at, r.decided_at, r.note, r.reviewer_id,
               p.id AS project_id, p.title, p.public_summary, p.sensitivity_label,
               p.engagement_model, p.confidential_brief, p.sponsor_id,
               u.name AS sponsor_name
        FROM project_reviews r
        JOIN projects p ON p.id = r.project_id AND p.created_at = r.project_created_at
        JOIN users u ON u.id = p.sponsor_id
        ORDER BY r.submitted_at ASC
        """
    )
    out = []
    for row in rows:
        d = dict(row)
        brief = d.pop("confidential_brief") or ""
        d["checks"] = automated_checks(
            d["title"] or "", d["public_summary"] or "", brief
        )
        d["state_label"] = STATE_LABELS.get(d["state"], d["state"])
        out.append(d)
    return out


def counts() -> Dict[str, int]:
    states = list(states_map().values())
    total = query_one("SELECT COUNT(*) AS n FROM projects")
    total_n = dict(total)["n"] if total else 0
    pending = states.count("pending")
    changes = states.count("changes_requested")
    rejected = states.count("rejected")
    return {
        "total": total_n,
        "pending": pending,
        "changes_requested": changes,
        "rejected": rejected,
        "approved": total_n - pending - changes - rejected,
    }


def _my_rows(sponsor: Any) -> List[Dict[str, Any]]:
    _ensure_table()
    rows = query_all(
        """
        SELECT r.state, r.submitted_at, r.decided_at, r.note,
               p.id AS project_id, p.title, p.public_summary, p.confidential_brief
        FROM project_reviews r
        JOIN projects p ON p.id = r.project_id AND p.created_at = r.project_created_at
        WHERE p.sponsor_id = ?
        ORDER BY r.submitted_at DESC
        """,
        (sponsor["id"],),
    )
    out = []
    for row in rows:
        d = dict(row)
        d["state_label"] = STATE_LABELS.get(d["state"], d["state"])
        out.append(d)
    return out


# ─────────────────────────────────────────────
# Middleware: hide projects that are not approved yet
# ─────────────────────────────────────────────
async def review_gate(request: Request, call_next):
    m = _PROJECT_PATH.match(request.url.path)
    if m:
        pid = int(m.group(1))
        if state_of(pid) != "approved":
            user = current_user(request)
            owner = query_one("SELECT sponsor_id FROM projects WHERE id = ?", (pid,))
            allowed = bool(user) and (
                user["role"] == "admin"
                or (owner is not None and owner["sponsor_id"] == user["id"])
            )
            if not allowed:
                return JSONResponse({"detail": "Project not found"}, status_code=404)
    return await call_next(request)


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
class DecisionIn(BaseModel):
    decision: str
    note: Optional[str] = None


def _redirect(
    msg: Optional[str] = None, error: Optional[str] = None
) -> RedirectResponse:
    params = {}
    if msg:
        params["msg"] = msg
    if error:
        params["error"] = error
    url = "/review" + ("?" + urlencode(params) if params else "")
    return RedirectResponse(url=url, status_code=303)


def build_router(templates) -> APIRouter:
    router = APIRouter()

    @router.get("/review")
    def review_page(
        request: Request,
        user: Optional[Any] = Depends(current_user),
        submitted: Optional[int] = None,
        msg: Optional[str] = None,
        error: Optional[str] = None,
    ):
        if not user or user["role"] not in ("admin", "sponsor"):
            raise HTTPException(
                status_code=403, detail="Forbidden: sponsors and admins only"
            )
        all_users = query_all("SELECT * FROM users ORDER BY id ASC")
        ctx: Dict[str, Any] = {
            "user": user,
            "all_users": all_users,
            "msg": (msg or "")[:200],
            "error": (error or "")[:300],
            "submitted": submitted,
            "counts": counts(),
        }
        if user["role"] == "admin":
            rows = _queue_rows()
            ctx["pending"] = [r for r in rows if r["state"] == "pending"]
            ctx["waiting"] = [r for r in rows if r["state"] == "changes_requested"]
            ctx["decided"] = sorted(
                [r for r in rows if r["state"] in ("approved", "rejected")],
                key=lambda r: r["decided_at"] or "",
                reverse=True,
            )[:10]
        else:
            ctx["mine"] = _my_rows(user)
        return templates.TemplateResponse(request, "review.html", ctx)

    @router.post("/review/{project_id}/decision")
    def review_decision_form(
        project_id: int,
        decision: str = Form(""),
        note: str = Form(""),
        admin: Any = Depends(require_role("admin")),
    ):
        try:
            state = decide(admin, project_id, decision, note)
        except HTTPException as exc:
            return _redirect(error=str(exc.detail))
        return _redirect(msg=f"Project #{project_id}: {STATE_LABELS[state].lower()}")

    @router.post("/review/{project_id}/edit")
    def review_edit_form(
        project_id: int,
        title: str = Form(""),
        public_summary: str = Form(""),
        confidential_brief: str = Form(""),
        resubmit_after: str = Form(""),
        sponsor: Any = Depends(require_role("sponsor")),
    ):
        try:
            edit_project(
                sponsor,
                project_id,
                title,
                public_summary,
                confidential_brief,
                bool(resubmit_after),
            )
        except HTTPException as exc:
            if exc.status_code == 403:
                raise
            return _redirect(error=str(exc.detail))
        return _redirect(
            msg=f"Project #{project_id} saved"
            + (" and resubmitted" if resubmit_after else "")
        )

    @router.post("/review/{project_id}/resubmit")
    def review_resubmit_form(
        project_id: int, sponsor: Any = Depends(require_role("sponsor"))
    ):
        try:
            resubmit(sponsor, project_id)
        except HTTPException as exc:
            if exc.status_code == 403:
                raise
            return _redirect(error=str(exc.detail))
        return _redirect(msg=f"Project #{project_id} resubmitted for review")

    # ----- JSON API -----
    @router.get("/api/review/queue")
    def api_queue(admin: Any = Depends(require_role("admin"))):
        return {"counts": counts(), "items": _queue_rows()}

    @router.post("/api/review/{project_id}/decision")
    def api_decision(
        project_id: int, body: DecisionIn, admin: Any = Depends(require_role("admin"))
    ):
        state = decide(admin, project_id, body.decision, body.note)
        return {"project_id": project_id, "state": state}

    @router.get("/api/review/mine")
    def api_mine(sponsor: Any = Depends(require_role("sponsor"))):
        return {
            "items": [
                {k: v for k, v in r.items() if k != "confidential_brief"}
                for r in _my_rows(sponsor)
            ]
        }

    return router


def install(app, templates) -> None:
    """One call from main.py: routes, admin console and the visibility gate."""
    from app.admin_console import build_router as build_admin_router

    app.include_router(build_router(templates))
    app.include_router(build_admin_router(templates))
    app.middleware("http")(review_gate)
