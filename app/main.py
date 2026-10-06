from contextlib import asynccontextmanager
import json
import sqlite3
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.access import can_view, membership_state
from app.db import get_conn, init_db, query_all, query_one
from app.deps import current_user, require_role
from app.seed import seed_projects, seed_users
from app.services.projects import create_project, join_project, publish_charter


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run DB init and seed on startup
    init_db()
    seed_users()
    seed_projects()
    yield


app = FastAPI(
    title="Provenance",
    description="Collaborative Research Ecosystem",
    lifespan=lifespan,
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Register custom Jinja filter for JSON parsing
templates.env.filters["from_json"] = lambda s: json.loads(s) if s else []


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 403:
        user = current_user(request)
        all_users = query_all("SELECT * FROM users ORDER BY id ASC")
        return templates.TemplateResponse(
            request,
            "forbidden.html",
            {
                "user": user,
                "all_users": all_users,
                "detail": exc.detail,
            },
            status_code=403,
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# ─────────────────────────────────────────────
# Core / auth routes
# ─────────────────────────────────────────────

@app.get("/health")
def health():
    table_row = query_one(
        "SELECT count(*) as count FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    user_row = query_one("SELECT count(*) as count FROM users")
    table_count = table_row["count"] if table_row else 0
    user_count = user_row["count"] if user_row else 0
    return {
        "status": "ok",
        "tables": table_count,
        "users": user_count,
    }


@app.get("/")
def home(request: Request, user: Optional[sqlite3.Row] = Depends(current_user)):
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    user_row = query_one("SELECT count(*) as count FROM users")
    user_count = user_row["count"] if user_row else 0

    skills = []
    if user and user["skills"]:
        try:
            skills = json.loads(user["skills"])
        except Exception:
            skills = []

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "user": user,
            "all_users": all_users,
            "skills": skills,
            "user_count": user_count,
        },
    )


@app.get("/switch/{user_id}")
def switch_persona(user_id: int):
    # MOCKED: production would use real authentication and KYC
    target_user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="persona_id", value=str(user_id), path="/")
    return response


@app.get("/switch-clear")
def clear_persona():
    """Helper route to clear active persona."""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key="persona_id", path="/")
    return response


@app.get("/admin")
def admin_console(request: Request, admin: sqlite3.Row = Depends(require_role("admin"))):
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    return templates.TemplateResponse(
        request,
        "placeholder.html",
        {
            "title": "Admin Console",
            "module_note": "Admin Console & System Governance (Admin Role Confirmed)",
            "user": admin,
            "all_users": all_users,
        },
    )


@app.get("/ledger")
def ledger(request: Request, user: Optional[sqlite3.Row] = Depends(current_user)):
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    return templates.TemplateResponse(
        request,
        "placeholder.html",
        {
            "title": "Tamper-Evident Ledger",
            "module_note": "Module S2 will build the append-only Hash-Chain Ledger, Verification, and Tamper Demo.",
            "user": user,
            "all_users": all_users,
        },
    )


# ─────────────────────────────────────────────
# Helper: build project list rows
# ─────────────────────────────────────────────

def _project_list_rows(user: Optional[Any]) -> list:
    """Return all projects joined with sponsor name."""
    rows = query_all(
        """
        SELECT p.*, u.name as sponsor_name
        FROM projects p
        JOIN users u ON u.id = p.sponsor_id
        ORDER BY p.id ASC
        """
    )
    return rows


# ─────────────────────────────────────────────
# HTML Project routes (S1b)
# ─────────────────────────────────────────────

@app.get("/projects")
def projects_list(request: Request, user: Optional[sqlite3.Row] = Depends(current_user)):
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    projects = _project_list_rows(user)

    # Compute membership state for each project for this user
    membership_states: Dict[int, str] = {}
    for p in projects:
        uid = user["id"] if user else None
        membership_states[p["id"]] = membership_state(p["id"], uid)

    return templates.TemplateResponse(
        request,
        "projects_list.html",
        {
            "user": user,
            "all_users": all_users,
            "projects": projects,
            "membership_states": membership_states,
        },
    )


@app.get("/projects/new")
def project_new_get(
    request: Request,
    sponsor: sqlite3.Row = Depends(require_role("sponsor")),
):
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    return templates.TemplateResponse(
        request,
        "project_new.html",
        {
            "user": sponsor,
            "all_users": all_users,
            "error": None,
            "form": {},
        },
    )


@app.post("/projects/new")
async def project_new_post(
    request: Request,
    sponsor: sqlite3.Row = Depends(require_role("sponsor")),
    title: str = Form(""),
    public_summary: str = Form(""),
    confidential_brief: str = Form(""),
    sensitivity_label: str = Form(""),
    engagement_model: str = Form(""),
    rewards: str = Form(""),
    ip_publication: str = Form(""),
):
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    form_data = {
        "title": title,
        "public_summary": public_summary,
        "confidential_brief": confidential_brief,
        "sensitivity_label": sensitivity_label,
        "engagement_model": engagement_model,
        "rewards": rewards,
        "ip_publication": ip_publication,
    }
    try:
        project_id = create_project(sponsor, form_data)
        return RedirectResponse(url=f"/projects/{project_id}", status_code=303)
    except HTTPException as exc:
        return templates.TemplateResponse(
            request,
            "project_new.html",
            {
                "user": sponsor,
                "all_users": all_users,
                "error": exc.detail,
                "form": form_data,
            },
            status_code=exc.status_code,
        )


def _build_project_context(project_id: int, user: Optional[Any]) -> Dict[str, Any]:
    """Shared helper: gather all data needed for the project_detail template."""
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    sponsor = query_one("SELECT * FROM users WHERE id = ?", (project["sponsor_id"],))
    charter = query_one(
        "SELECT * FROM charters WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    )

    uid = user["id"] if user else None
    state = membership_state(project_id, uid)
    can_see_brief = can_view(user, project, "brief")
    can_see_roster = can_view(user, project, "roster")
    can_see_milestones = can_view(user, project, "milestones")

    # Brief text only entered into context when allowed — never when locked
    brief_text = project["confidential_brief"] if can_see_brief else None

    # Members (only fetched if allowed to see roster)
    members = []
    if can_see_roster:
        members = query_all(
            """
            SELECT u.name, u.role, u.institution, ca.charter_version
            FROM charter_acceptances ca
            JOIN users u ON u.id = ca.user_id
            WHERE ca.project_id = ?
            ORDER BY ca.id ASC
            """,
            (project_id,),
        )

    # Milestones (only fetched if allowed)
    milestones = []
    if can_see_milestones:
        milestones = query_all(
            "SELECT * FROM milestones WHERE project_id = ? ORDER BY id ASC",
            (project_id,),
        )

    return {
        "project": project,
        "sponsor": sponsor,
        "charter": charter,
        "state": state,
        "can_see_brief": can_see_brief,
        "can_see_roster": can_see_roster,
        "can_see_milestones": can_see_milestones,
        "brief_text": brief_text,
        "members": members,
        "milestones": milestones,
    }


@app.get("/projects/{project_id}")
def project_detail(
    project_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    ctx = _build_project_context(project_id, user)
    ctx["user"] = user
    ctx["all_users"] = all_users
    return templates.TemplateResponse(request, "project_detail.html", ctx)


@app.get("/projects/{project_id}/join")
def join_get(
    project_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    if not user or user["role"] not in ("student", "expert"):
        raise HTTPException(status_code=403, detail="Only students and experts can join projects")

    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    sponsor = query_one("SELECT * FROM users WHERE id = ?", (project["sponsor_id"],))
    charter = query_one(
        "SELECT * FROM charters WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    )
    charter_terms = json.loads(charter["terms_json"]) if charter else {}
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    state = membership_state(project_id, user["id"])

    return templates.TemplateResponse(
        request,
        "join.html",
        {
            "user": user,
            "all_users": all_users,
            "project": project,
            "sponsor": sponsor,
            "charter": charter,
            "charter_terms": charter_terms,
            "state": state,
            "error": None,
            "form_accept_charter": False,
            "form_ack_engagement": False,
        },
    )


@app.post("/projects/{project_id}/join")
async def join_post(
    project_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    accept_charter: Optional[str] = Form(None),
    ack_engagement_model: Optional[str] = Form(None),
):
    if not user or user["role"] not in ("student", "expert"):
        raise HTTPException(status_code=403, detail="Only students and experts can join projects")

    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    sponsor = query_one("SELECT * FROM users WHERE id = ?", (project["sponsor_id"],))
    charter = query_one(
        "SELECT * FROM charters WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    )
    charter_terms = json.loads(charter["terms_json"]) if charter else {}
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    state = membership_state(project_id, user["id"])

    accept_bool = accept_charter == "1"
    ack_bool = ack_engagement_model == "1"

    try:
        join_project(user, project_id, accept_bool, ack_bool)
        return RedirectResponse(url=f"/projects/{project_id}", status_code=303)
    except HTTPException as exc:
        return templates.TemplateResponse(
            request,
            "join.html",
            {
                "user": user,
                "all_users": all_users,
                "project": project,
                "sponsor": sponsor,
                "charter": charter,
                "charter_terms": charter_terms,
                "state": state,
                "error": exc.detail,
                "form_accept_charter": accept_bool,
                "form_ack_engagement": ack_bool,
            },
            status_code=exc.status_code,
        )


def _build_charter_versions(project_id: int) -> list:
    """Build version list with diff_rows for versions > 1."""
    all_charters = query_all(
        "SELECT * FROM charters WHERE project_id = ? ORDER BY version ASC",
        (project_id,),
    )
    versions = []
    for i, ch in enumerate(all_charters):
        terms = json.loads(ch["terms_json"])
        diff_rows = None
        if i > 0:
            prev_terms = json.loads(all_charters[i - 1]["terms_json"])
            diff_rows = []
            all_keys = list(dict.fromkeys(list(prev_terms.keys()) + list(terms.keys())))
            for key in all_keys:
                before = prev_terms.get(key, "")
                after = terms.get(key, "")
                diff_rows.append({"key": key, "before": before, "after": after, "changed": before != after})
        versions.append({
            "id": ch["id"],
            "version": ch["version"],
            "hash": ch["hash"],
            "published_at": ch["published_at"],
            "terms": terms,
            "diff_rows": diff_rows,
        })
    # Return newest first
    versions.reverse()
    return versions


@app.get("/projects/{project_id}/charter")
def charter_page(
    project_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    versions = _build_charter_versions(project_id)
    is_sponsor = user is not None and user["id"] == project["sponsor_id"]
    next_version = (project["current_charter_version"] or 1) + 1

    return templates.TemplateResponse(
        request,
        "charter.html",
        {
            "user": user,
            "all_users": all_users,
            "project": project,
            "versions": versions,
            "is_sponsor": is_sponsor,
            "next_version": next_version,
            "publish_error": None,
        },
    )


@app.post("/projects/{project_id}/charter")
async def charter_publish_post(
    project_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    rewards: str = Form(""),
    engagement_model: str = Form(""),
    change_note: str = Form(""),
):
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    is_sponsor = user is not None and user["id"] == project["sponsor_id"]
    next_version = (project["current_charter_version"] or 1) + 1

    changes: Dict[str, Any] = {}
    if rewards.strip():
        changes["rewards"] = rewards.strip()
    if engagement_model.strip():
        changes["engagement_model"] = engagement_model.strip()
    if change_note.strip():
        changes["change_note"] = change_note.strip()

    try:
        publish_charter(user, project_id, changes)
        return RedirectResponse(url=f"/projects/{project_id}/charter", status_code=303)
    except HTTPException as exc:
        versions = _build_charter_versions(project_id)
        return templates.TemplateResponse(
            request,
            "charter.html",
            {
                "user": user,
                "all_users": all_users,
                "project": project,
                "versions": versions,
                "is_sponsor": is_sponsor,
                "next_version": next_version,
                "publish_error": exc.detail,
            },
            status_code=exc.status_code,
        )


@app.get("/projects/{project_id}/visibility")
def visibility_page(
    project_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    all_users_rows = query_all("SELECT * FROM users ORDER BY id ASC")
    resources = ["public_summary", "charter", "brief", "roster", "milestones"]

    # Build columns (all seeded users)
    columns = []
    for u in all_users_rows:
        state = membership_state(project_id, u["id"])
        columns.append({"id": u["id"], "name": u["name"], "role": u["role"], "state": state})

    # Build matrix: {user_id or 'anonymous': {resource: bool}}
    matrix: Dict[Any, Dict[str, bool]] = {}

    # Anonymous row
    matrix["anonymous"] = {r: can_view(None, project, r) for r in resources}

    # Per-user rows
    for u in all_users_rows:
        matrix[u["id"]] = {r: can_view(u, project, r) for r in resources}

    return templates.TemplateResponse(
        request,
        "visibility.html",
        {
            "user": user,
            "all_users": all_users_rows,
            "project": project,
            "resources": resources,
            "columns": columns,
            "matrix": matrix,
        },
    )


# ─────────────────────────────────────────────
# JSON API routes (S1a — consumed by tests / future JS)
# ─────────────────────────────────────────────

@app.post("/api/projects")
async def api_create_project(
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    title: str = Form(""),
    public_summary: str = Form(""),
    confidential_brief: str = Form(""),
    sensitivity_label: str = Form(""),
    engagement_model: str = Form(""),
    rewards: str = Form(""),
    ip_publication: str = Form(""),
):
    fields = {
        "title": title,
        "public_summary": public_summary,
        "confidential_brief": confidential_brief,
        "sensitivity_label": sensitivity_label,
        "engagement_model": engagement_model,
        "rewards": rewards,
        "ip_publication": ip_publication,
    }
    project_id = create_project(user, fields)
    return JSONResponse({"project_id": project_id}, status_code=201)


@app.get("/api/projects/{project_id}/brief")
def api_brief(
    project_id: int,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_view(user, project, "brief"):
        raise HTTPException(status_code=403, detail="Access denied to confidential brief")
    return {"project_id": project_id, "brief": project["confidential_brief"]}


@app.post("/api/projects/{project_id}/join")
async def api_join(
    project_id: int,
    user: Optional[sqlite3.Row] = Depends(current_user),
    accept_charter: Optional[str] = Form(None),
    ack_engagement_model: Optional[str] = Form(None),
):
    accept_bool = accept_charter in ("1", "true", "True")
    ack_bool = ack_engagement_model in ("1", "true", "True")
    result = join_project(user, project_id, accept_bool, ack_bool)
    return JSONResponse(result)


@app.post("/api/projects/{project_id}/charter")
async def api_publish_charter(
    project_id: int,
    user: Optional[sqlite3.Row] = Depends(current_user),
    rewards: str = Form(""),
    engagement_model: str = Form(""),
    change_note: str = Form(""),
):
    changes: Dict[str, Any] = {}
    if rewards.strip():
        changes["rewards"] = rewards.strip()
    if engagement_model.strip():
        changes["engagement_model"] = engagement_model.strip()
    if change_note.strip():
        changes["change_note"] = change_note.strip()
    new_version = publish_charter(user, project_id, changes)
    return {"project_id": project_id, "new_version": new_version}


@app.get("/api/projects/{project_id}/membership")
def api_membership(
    project_id: int,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    uid = user["id"] if user else None
    state = membership_state(project_id, uid)
    return {"state": state}
