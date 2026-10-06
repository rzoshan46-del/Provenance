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
    import app.ledger as ledger
    ledger.ensure_genesis()
    yield


app = FastAPI(
    title="Provenance",
    description="Collaborative Research Ecosystem",
    lifespan=lifespan,
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Register custom Jinja filters
templates.env.filters["from_json"] = lambda s: json.loads(s) if s else []


def inr_format(val: Any) -> str:
    """Format an integer with Indian digit grouping and the rupee sign.
    e.g. 100000 -> ₹1,00,000, 25783 -> ₹25,783
    """
    if val is None or val == "":
        return ""
    try:
        val_int = int(val)
    except (ValueError, TypeError):
        return str(val)
    s = str(abs(val_int))
    if len(s) <= 3:
        res = s
    else:
        last3 = s[-3:]
        rest = s[:-3]
        parts = []
        while len(rest) > 2:
            parts.append(rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.append(rest)
        parts.reverse()
        res = ",".join(parts) + "," + last3
    prefix = "-" if val_int < 0 else ""
    return f"{prefix}₹{res}"


templates.env.filters["inr"] = inr_format

# Jinja2 globals — callable from any template
import app.credits as _credits_mod
templates.env.globals["user_credits"] = _credits_mod.total  # user_credits(user_id) → int


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

    import app.ledger as ledger
    ledger_info = ledger.verify()

    project_count_row = query_one("SELECT count(*) as c FROM projects")
    project_count = project_count_row["c"] if project_count_row else 0

    ledger_entry_row = query_one("SELECT count(*) as c FROM ledger_entries")
    ledger_entry_count = ledger_entry_row["c"] if ledger_entry_row else 0

    ai_calls_row = query_one("SELECT count(*) as c FROM ai_calls")
    ai_calls_count = ai_calls_row["c"] if ai_calls_row else 0

    # Recent public projects for the preview strip
    recent_projects = query_all(
        "SELECT * FROM projects WHERE sensitivity_label = 'public' ORDER BY id DESC LIMIT 4"
    )

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "user": user,
            "all_users": all_users,
            "skills": skills,
            "user_count": user_count,
            "ledger_info": ledger_info,
            "project_count": project_count,
            "ledger_entry_count": ledger_entry_count,
            "ai_calls_count": ai_calls_count,
            "recent_projects": recent_projects,
        },
    )


@app.get("/login")
def login_page(request: Request, user: Optional[sqlite3.Row] = Depends(current_user)):
    """Login / persona selection page. MOCKED: production would use real Google OAuth."""
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    if user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"user": user, "all_users": all_users},
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
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="persona_id", path="/")
    return response


@app.get("/me")
def my_profile(request: Request, user: Optional[sqlite3.Row] = Depends(current_user)):
    """Profile page: credits, history, memberships, credentials."""
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    import app.credits as cr
    cr_total = cr.total(user["id"])
    cr_hist  = cr.history(user["id"])
    cr_break = cr.breakdown(user["id"])

    # User's skills
    skills = []
    try:
        skills = json.loads(user["skills"] or "[]")
    except Exception:
        pass

    # Projects the user is a member of
    memberships = query_all(
        """
        SELECT p.id, p.title, p.engagement_model, p.sensitivity_label,
               pm.membership_state, pm.joined_at
        FROM project_memberships pm
        JOIN projects p ON p.id = pm.project_id
        WHERE pm.user_id = ? AND pm.membership_state = 'member'
        ORDER BY pm.joined_at DESC
        """,
        (user["id"],),
    )

    # Credentials
    my_creds = query_all(
        """
        SELECT c.credential_hash, c.issued_at, c.contribution_hash,
               m.title as milestone_title, proj.title as project_title
        FROM credentials c
        JOIN contributions con ON con.id = c.contribution_id
        JOIN milestones m ON m.id = con.milestone_id
        JOIN projects proj ON proj.id = m.project_id
        WHERE c.user_id = ?
        ORDER BY c.issued_at DESC
        """,
        (user["id"],),
    )

    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "user": user,
            "all_users": all_users,
            "skills": skills,
            "cr_total": cr_total,
            "cr_hist": cr_hist,
            "cr_break": cr_break,
            "memberships": memberships,
            "my_creds": my_creds,
        },
    )


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


def _action_category_color(action: Optional[str]) -> str:
    if not action:
        return "system"
    if action in (
        "project_posted",
        "charter_published",
        "charter_accepted",
        "charter_declined",
        "member_left",
        "dispute_opened",
        "dispute_resolved",
    ):
        return "gov"
    if action in ("escrow_funded", "escrow_state_changed", "payout_released"):
        return "money"
    if action in (
        "contribution_submitted",
        "contribution_flagged",
        "agent_action",
        "agent_action_approved",
        "milestone_proposed",
        "review_recorded",
        "credential_issued",
    ):
        return "work"
    return "system"


@app.get("/ledger")
def ledger(
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    project_id: Optional[int] = None,
    actor_type: Optional[str] = None,
):
    import app.ledger as ledger
    verify = ledger.verify()

    # Full chain for chain strip (ascending order)
    strip_entries = ledger.list_entries(user)
    for block in strip_entries:
        if not block.get("redacted"):
            block["action_color"] = _action_category_color(block.get("action"))

    # Filtered entries for entry list
    if project_id is not None:
        raw_list = ledger.list_entries(user, project_id=project_id)
    else:
        raw_list = strip_entries

    if actor_type:
        raw_list = [e for e in raw_list if e.get("actor_type") == actor_type]

    # Order newest first (descending by id)
    list_entries = sorted(raw_list, key=lambda x: x["id"], reverse=True)

    # Resolution helpers — query name and role only (no email addresses)
    all_users_rows = query_all("SELECT id, name, role FROM users ORDER BY id ASC")
    user_names = {u["id"]: u["name"] for u in all_users_rows}
    projects_rows = query_all("SELECT id, title FROM projects ORDER BY id ASC")
    project_titles = {p["id"]: p["title"] for p in projects_rows}

    for entry in list_entries:
        if not entry.get("redacted"):
            entry["action_color"] = _action_category_color(entry.get("action"))
            payload_data = entry.get("payload")
            entry["payload_pretty"] = (
                json.dumps(payload_data, indent=2) if payload_data is not None else ""
            )
            entry["human_owner_name"] = user_names.get(entry.get("human_owner_id")) or (
                "System" if entry.get("actor_type") == "system" else "Unknown"
            )
            entry["project_title"] = project_titles.get(entry.get("project_id")) or ""

    # Demo panel setup: identify earliest entry that has a project_id
    is_demo = ledger.demo_mode()
    demo_entries = strip_entries
    default_demo_entry_id = None
    for entry in strip_entries:
        if entry.get("project_id") is not None:
            default_demo_entry_id = entry["id"]
            break
    if default_demo_entry_id is None and strip_entries:
        default_demo_entry_id = strip_entries[0]["id"]

    # ── Contribution Scorecard ──────────────────────────────────
    # Credits: 20 per contribution_submitted, 30 per review approved,
    #          50 per milestone_accepted, 15 per agent_action_approved
    credit_map: dict = {}
    CREDIT_WEIGHTS = {
        "contribution_submitted": 20,
        "contribution_reviewed": 30,
        "milestone_accepted": 50,
        "agent_action_approved": 15,
        "charter_accepted": 5,
    }
    all_entries_for_credits = query_all(
        "SELECT actor_id, actor_type, action FROM ledger_entries WHERE actor_type='human'"
    )
    for e in all_entries_for_credits:
        uid = e["actor_id"]
        action = e["action"]
        pts = CREDIT_WEIGHTS.get(action, 0)
        if pts > 0:
            credit_map[uid] = credit_map.get(uid, 0) + pts

    # Build ranked list
    scorecard_rows = []
    for u in all_users_rows:
        uid = u["id"]
        credits = credit_map.get(uid, 0)
        if credits > 0:
            scorecard_rows.append({
                "user_id": uid,
                "name": u["name"],
                "role": u["role"],
                "credits": credits,
            })
    scorecard_rows.sort(key=lambda x: x["credits"], reverse=True)
    max_credits = scorecard_rows[0]["credits"] if scorecard_rows else 1
    for row in scorecard_rows:
        row["pct"] = round(row["credits"] / max_credits * 100)

    return templates.TemplateResponse(
        request,
        "ledger.html",
        {
            "user": user,
            "all_users": all_users_rows,
            "verify": verify,
            "strip_entries": strip_entries,
            "list_entries": list_entries,
            "projects": projects_rows,
            "selected_project_id": project_id,
            "selected_actor_type": actor_type,
            "is_demo_mode": is_demo,
            "demo_entries": demo_entries,
            "default_demo_entry_id": default_demo_entry_id,
            "scorecard_rows": scorecard_rows,
            "max_credits": max_credits,
            "total_contributors": len(scorecard_rows),
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

    ledger_count_row = query_one(
        "SELECT COUNT(*) as c FROM ledger_entries WHERE project_id = ?", (project_id,)
    )
    ledger_count = ledger_count_row["c"] if ledger_count_row else 0

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
        "ledger_count": ledger_count,
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


# ─────────────────────────────────────────────
# Ledger JSON API routes (S2)
# ─────────────────────────────────────────────

@app.get("/api/ledger/verify")
def api_ledger_verify():
    import app.ledger as ledger
    return ledger.verify()


@app.post("/api/ledger/tamper")
async def api_ledger_tamper(
    request: Request,
    entry_id: Optional[int] = Form(None),
):
    import app.ledger as ledger
    if not ledger.demo_mode():
        raise HTTPException(status_code=403, detail="Demo mode disabled")
    try:
        if entry_id is None:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    entry_id = body.get("entry_id")
            except Exception:
                pass
        tampered_id = ledger.tamper_demo(entry_id)
        return {"status": "tampered", "entry_id": tampered_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ledger/restore")
def api_ledger_restore():
    import app.ledger as ledger
    if not ledger.demo_mode():
        raise HTTPException(status_code=403, detail="Demo mode disabled")
    try:
        count = ledger.restore_demo()
        return {"status": "restored", "restored_count": count}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─────────────────────────────────────────────
# Milestones & Escrow API routes (S3a)
# ─────────────────────────────────────────────

@app.post("/api/projects/{project_id}/milestones")
async def api_create_milestone(
    project_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    title: str = Form(""),
    deliverables: str = Form(""),
    acceptance_criteria: str = Form(""),
    required_skills: str = Form(""),
    amount_inr: Any = Form(0),
    acceptance_window_days: int = Form(7),
):
    from app.services.milestones import create_milestone

    fields = {
        "title": title,
        "deliverables": deliverables,
        "acceptance_criteria": acceptance_criteria,
        "required_skills": required_skills,
        "amount_inr": amount_inr,
        "acceptance_window_days": acceptance_window_days,
    }

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                fields.update(body)
        except Exception:
            pass

    milestone_id = create_milestone(user, project_id, fields)
    return JSONResponse({"status": "ok", "id": milestone_id, "milestone_id": milestone_id}, status_code=200)


@app.get("/api/projects/{project_id}/milestones")
def api_list_milestones(
    project_id: int,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    from app.services.milestones import list_milestones
    return list_milestones(user, project_id)


@app.get("/api/milestones/{milestone_id}")
def api_get_milestone(
    milestone_id: int,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    from app.services.milestones import get_milestone
    return get_milestone(user, milestone_id)


@app.post("/api/milestones/{milestone_id}/fund")
def api_fund_milestone(
    milestone_id: int,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    from app.services.escrow import fund_milestone
    result = fund_milestone(user, milestone_id)
    return JSONResponse(result, status_code=200)


# ─────────────────────────────────────────────
# Contributions, Reviews, Acceptance & Credentials (S3b)
# ─────────────────────────────────────────────

@app.post("/api/milestones/{milestone_id}/contributions")
async def api_submit_contribution(
    milestone_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    title: str = Form(""),
    text: str = Form(""),
    ai_declaration: str = Form(""),
):
    from app.services.contributions import submit_contribution

    title_val = title
    text_val = text
    ai_decl_val = ai_declaration

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                title_val = body.get("title", title_val)
                text_val = body.get("text", text_val)
                ai_decl_val = body.get("ai_declaration", ai_decl_val)
        except Exception:
            pass

    res = submit_contribution(user, milestone_id, title_val, text_val, ai_decl_val)
    return JSONResponse(res, status_code=200)


@app.get("/api/milestones/{milestone_id}/contributions")
def api_list_contributions(
    milestone_id: int,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    from app.services.contributions import list_contributions
    return list_contributions(user, milestone_id)


@app.post("/api/contributions/{contribution_id}/review")
async def api_review_contribution(
    contribution_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    decision: str = Form(""),
    impact_score: Optional[Any] = Form(None),
    reasons: Optional[str] = Form(None),
    criteria_ref: Optional[str] = Form(None),
):
    from app.services.contributions import review_contribution

    dec_val = decision
    score_val = impact_score
    reasons_val = reasons
    criteria_val = criteria_ref

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                dec_val = body.get("decision", dec_val)
                score_val = body.get("impact_score", score_val)
                reasons_val = body.get("reasons", reasons_val)
                criteria_val = body.get("criteria_ref", criteria_val)
        except Exception:
            pass

    res = review_contribution(user, contribution_id, dec_val, score_val, reasons_val, criteria_val)
    return JSONResponse(res, status_code=200)


@app.post("/api/milestones/{milestone_id}/submit")
def api_submit_milestone(
    milestone_id: int,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    from app.services.milestones import submit_milestone
    res = submit_milestone(user, milestone_id)
    return JSONResponse(res, status_code=200)


@app.post("/api/milestones/{milestone_id}/accept")
def api_accept_milestone(
    milestone_id: int,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    from app.services.milestones import accept_milestone
    res = accept_milestone(user, milestone_id)
    return JSONResponse(res, status_code=200)


@app.get("/api/milestones/{milestone_id}/receipt")
def api_milestone_receipt(
    milestone_id: int,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    milestone = query_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,))
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    project = query_one("SELECT * FROM projects WHERE id = ?", (milestone["project_id"],))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not can_view(user, project, "milestones"):
        raise HTTPException(status_code=403, detail="Access denied to milestone receipt")

    from app.services import payouts

    is_funded = project["engagement_model"] in ("funded", "stipend")
    if is_funded:
        return payouts.build_receipt(milestone_id)
    else:
        return payouts.credit_statement(milestone_id)


@app.get("/api/credentials/{credential_hash}")
def api_get_credential(credential_hash: str):
    row = query_one(
        """
        SELECT c.*, p.title AS project_title
        FROM credentials c
        JOIN projects p ON p.id = c.project_id
        WHERE c.credential_hash = ?
        """,
        (credential_hash,),
    )
    if not row:
        return JSONResponse({"valid": False}, status_code=404)

    return {
        "valid": True,
        "project_title": row["project_title"],
        "kind": row["kind"],
        "issued_at": row["issued_at"],
        "user_id": row["user_id"],
        "credential_hash": row["credential_hash"],
    }


@app.get("/api/me/credentials")
def api_my_credentials(user: Optional[sqlite3.Row] = Depends(current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    rows = query_all(
        """
        SELECT c.*, p.title AS project_title
        FROM credentials c
        JOIN projects p ON p.id = c.project_id
        WHERE c.user_id = ?
        ORDER BY c.id DESC
        """,
        (user["id"],),
    )
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# HTML Routes: Milestones, Escrow, Receipts & Credentials (S3c)
# ─────────────────────────────────────────────

def _render_milestones_page(
    request: Request,
    project_id: int,
    user: Optional[sqlite3.Row],
    error: Optional[str] = None,
    status_code: int = 200,
):
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    sponsor = query_one("SELECT * FROM users WHERE id = ?", (project["sponsor_id"],))
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    can_see_milestones = can_view(user, project, "milestones")
    is_funded = project["engagement_model"] in ("funded", "stipend")
    u_membership = membership_state(project_id, user["id"]) if user else "none"

    milestones_data = []
    if can_see_milestones:
        from app.services.milestones import list_milestones
        from app.services.contributions import list_contributions
        raw_ms = list_milestones(user, project_id)
        for ms in raw_ms:
            ms_dict = dict(ms)
            ms_dict["contributions"] = list_contributions(user, ms["id"])
            milestones_data.append(ms_dict)

    return templates.TemplateResponse(
        request,
        "milestones.html",
        {
            "user": user,
            "all_users": all_users,
            "project": project,
            "sponsor": sponsor,
            "can_see_milestones": can_see_milestones,
            "is_funded": is_funded,
            "milestones": milestones_data,
            "user_membership": u_membership,
            "is_sponsor": bool(user and user["id"] == project["sponsor_id"]),
            "is_expert": bool(user and user["role"] == "expert" and u_membership == "member"),
            "is_member": bool(user and u_membership == "member"),
            "error": error,
        },
        status_code=status_code,
    )


@app.get("/projects/{project_id}/milestones")
def project_milestones_page(
    project_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    return _render_milestones_page(request, project_id, user)


@app.post("/projects/{project_id}/milestones")
async def project_milestones_create_post(
    project_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    title: str = Form(""),
    deliverables: str = Form(""),
    acceptance_criteria: str = Form(""),
    required_skills: str = Form(""),
    amount_inr: Any = Form(0),
    acceptance_window_days: int = Form(7),
):
    from app.services.milestones import create_milestone
    fields = {
        "title": title,
        "deliverables": deliverables,
        "acceptance_criteria": acceptance_criteria,
        "required_skills": required_skills,
        "amount_inr": amount_inr,
        "acceptance_window_days": acceptance_window_days,
    }
    try:
        create_milestone(user, project_id, fields)
        return RedirectResponse(url=f"/projects/{project_id}/milestones", status_code=303)
    except HTTPException as exc:
        return _render_milestones_page(request, project_id, user, error=exc.detail, status_code=exc.status_code)


@app.post("/milestones/{milestone_id}/fund")
def milestone_fund_post(
    milestone_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    ms = query_one("SELECT project_id FROM milestones WHERE id = ?", (milestone_id,))
    project_id = ms["project_id"] if ms else None
    if not project_id:
        raise HTTPException(status_code=404, detail="Milestone not found")

    from app.services.escrow import fund_milestone
    try:
        fund_milestone(user, milestone_id)
        return RedirectResponse(url=f"/projects/{project_id}/milestones", status_code=303)
    except HTTPException as exc:
        return _render_milestones_page(request, project_id, user, error=exc.detail, status_code=exc.status_code)


@app.post("/milestones/{milestone_id}/contributions")
async def milestone_contributions_post(
    milestone_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    title: str = Form(""),
    text: str = Form(""),
    ai_declaration: str = Form(""),
):
    ms = query_one("SELECT project_id FROM milestones WHERE id = ?", (milestone_id,))
    project_id = ms["project_id"] if ms else None
    if not project_id:
        raise HTTPException(status_code=404, detail="Milestone not found")

    from app.services.contributions import submit_contribution
    try:
        submit_contribution(user, milestone_id, title, text, ai_declaration)
        return RedirectResponse(url=f"/projects/{project_id}/milestones", status_code=303)
    except HTTPException as exc:
        return _render_milestones_page(request, project_id, user, error=exc.detail, status_code=exc.status_code)


@app.post("/contributions/{contribution_id}/review")
async def contribution_review_post(
    contribution_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    decision: str = Form(""),
    impact_score: Optional[Any] = Form(None),
    reasons: Optional[str] = Form(None),
    criteria_ref: Optional[str] = Form(None),
):
    contrib = query_one("SELECT milestone_id FROM contributions WHERE id = ?", (contribution_id,))
    if not contrib:
        raise HTTPException(status_code=404, detail="Contribution not found")
    ms = query_one("SELECT project_id FROM milestones WHERE id = ?", (contrib["milestone_id"],))
    project_id = ms["project_id"] if ms else None
    if not project_id:
        raise HTTPException(status_code=404, detail="Milestone not found")

    from app.services.contributions import review_contribution
    try:
        review_contribution(user, contribution_id, decision, impact_score, reasons, criteria_ref)
        return RedirectResponse(url=f"/projects/{project_id}/milestones", status_code=303)
    except HTTPException as exc:
        return _render_milestones_page(request, project_id, user, error=exc.detail, status_code=exc.status_code)


@app.post("/milestones/{milestone_id}/submit")
def milestone_submit_post(
    milestone_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    ms = query_one("SELECT project_id FROM milestones WHERE id = ?", (milestone_id,))
    project_id = ms["project_id"] if ms else None
    if not project_id:
        raise HTTPException(status_code=404, detail="Milestone not found")

    from app.services.milestones import submit_milestone
    try:
        submit_milestone(user, milestone_id)
        return RedirectResponse(url=f"/projects/{project_id}/milestones", status_code=303)
    except HTTPException as exc:
        return _render_milestones_page(request, project_id, user, error=exc.detail, status_code=exc.status_code)


@app.post("/milestones/{milestone_id}/accept")
def milestone_accept_post(
    milestone_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    ms = query_one("SELECT project_id FROM milestones WHERE id = ?", (milestone_id,))
    project_id = ms["project_id"] if ms else None
    if not project_id:
        raise HTTPException(status_code=404, detail="Milestone not found")

    from app.services.milestones import accept_milestone
    try:
        accept_milestone(user, milestone_id)
        return RedirectResponse(url=f"/milestones/{milestone_id}/receipt", status_code=303)
    except HTTPException as exc:
        return _render_milestones_page(request, project_id, user, error=exc.detail, status_code=exc.status_code)


@app.get("/milestones/{milestone_id}/receipt")
def milestone_receipt_page(
    milestone_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    milestone = query_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,))
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    project = query_one("SELECT * FROM projects WHERE id = ?", (milestone["project_id"],))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    can_see = can_view(user, project, "milestones")
    is_funded = project["engagement_model"] in ("funded", "stipend")

    from app.services import payouts

    if is_funded:
        receipt = payouts.build_receipt(milestone_id) if can_see else None
        return templates.TemplateResponse(
            request,
            "receipt.html",
            {
                "user": user,
                "all_users": all_users,
                "project": project,
                "milestone": milestone,
                "receipt": receipt,
                "can_see": can_see,
            },
            status_code=200,
        )
    else:
        statement = payouts.credit_statement(milestone_id) if can_see else None
        return templates.TemplateResponse(
            request,
            "credit_statement.html",
            {
                "user": user,
                "all_users": all_users,
                "project": project,
                "milestone": milestone,
                "statement": statement,
                "can_see": can_see,
            },
            status_code=200,
        )


@app.get("/credentials")
def credentials_page(
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    creds = []
    if user:
        rows = query_all(
            """
            SELECT c.*, p.title AS project_title
            FROM credentials c
            JOIN projects p ON p.id = c.project_id
            WHERE c.user_id = ?
            ORDER BY c.id DESC
            """,
            (user["id"],),
        )
        creds = [dict(r) for r in rows]

    return templates.TemplateResponse(
        request,
        "credentials.html",
        {
            "user": user,
            "all_users": all_users,
            "credentials": creds,
        },
        status_code=200,
    )


# ─────────────────────────────────────────────
# Module S4a: AI Scoping, Matching & Calls API
# ─────────────────────────────────────────────

@app.post("/api/projects/{project_id}/scope")
async def api_scope_milestones(
    project_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    budget_inr: Any = Form(None),
):
    from app.ai.scoping import propose_milestones
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict) and "budget_inr" in body:
                budget_inr = body["budget_inr"]
        except Exception:
            pass

    proposed = propose_milestones(user, project_id, budget_inr)
    return JSONResponse(proposed, status_code=200)


@app.post("/api/milestones/{milestone_id}/approve")
async def api_approve_milestone(
    milestone_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
    amount_inr: Any = Form(None),
):
    from app.services.milestones import approve_milestone
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict) and "amount_inr" in body:
                amount_inr = body["amount_inr"]
        except Exception:
            pass

    res = approve_milestone(user, milestone_id, amount_inr)
    return JSONResponse(res, status_code=200)


@app.post("/api/projects/{project_id}/match")
def api_match_recommend(
    project_id: int,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    from app.ai.matching import recommend
    res = recommend(user, project_id)
    return JSONResponse(res, status_code=200)


@app.get("/api/projects/{project_id}/match")
def api_match_latest(
    project_id: int,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    from app.ai.matching import latest
    res = latest(user, project_id)
    return JSONResponse(res, status_code=200)


@app.get("/api/projects/{project_id}/ai-calls")
def api_get_ai_calls(
    project_id: int,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Visible to owning sponsor, members and admin (SPEC §19, Check 87)
    if not can_view(user, project, "milestones"):
        raise HTTPException(status_code=403, detail="Access denied to AI calls audit log")

    rows = query_all(
        """
        SELECT ac.*,
               a.name AS agent_name,
               u.name AS human_owner_name
        FROM ai_calls ac
        LEFT JOIN agents a ON a.id = ac.agent_id
        LEFT JOIN users u ON u.id = ac.human_owner_id
        WHERE ac.project_id = ?
        ORDER BY ac.id ASC
        """,
        (project_id,),
    )

    result = []
    for r in rows:
        ps = {}
        try:
            ps = json.loads(r["prompt_summary"] or "{}")
        except Exception:
            pass

        status = ps.get("status", "done")
        result.append({
            "id": r["id"],
            "created_at": r["created_at"],
            "agent_name": r["agent_name"] or "System Agent",
            "human_owner_name": r["human_owner_name"] or "System",
            "sensitivity_label": r["sensitivity_label"],
            "model_route": r["model_route"],
            "prompt_summary": ps,
            "status": status,
        })

    return JSONResponse(result, status_code=200)



# ──────────────────────────────────────────────────────────────────────────────
# S4b: Workspace Agent Routes
# ──────────────────────────────────────────────────────────────────────────────
from app.ai import workspace as workspace_mod


@app.post("/api/milestones/{milestone_id}/agent/draft")
async def api_agent_draft(
    milestone_id: int,
    instruction: Optional[str] = Form(None),
    source_text: str = Form(""),
    user: dict = Depends(current_user),
):
    """POST /api/milestones/{id}/agent/draft — create a pending workspace draft.

    Form fields: instruction (required), source_text (optional).
    Returns: {ai_call_id, draft, flags, blocked_tools, route}.
    """
    result = workspace_mod.draft(user, milestone_id, instruction or "", source_text)
    return JSONResponse(result, status_code=200)


@app.get("/api/projects/{project_id}/agent/actions")
async def api_list_agent_actions(
    project_id: int,
    user: dict = Depends(current_user),
):
    """GET /api/projects/{id}/agent/actions — list workspace actions for the project.

    Visible to sponsor, current-charter members, admin.
    Draft text included only for the action owner.
    """
    result = workspace_mod.list_actions(user, project_id)
    return JSONResponse(result, status_code=200)


@app.post("/api/agent-actions/{ai_call_id}/approve")
async def api_approve_agent_action(
    ai_call_id: int,
    confirm_flagged: str = Form(""),
    user: dict = Depends(current_user),
):
    """POST /api/agent-actions/{id}/approve — owner approves a pending draft.

    Form field: confirm_flagged (any truthy string enables bypassing injection warning).
    Returns: {status, ai_call_id, contribution_id}.
    """
    confirm = confirm_flagged.strip().lower() in ("1", "true", "yes")
    result = workspace_mod.approve_action(user, ai_call_id, confirm_flagged=confirm)
    return JSONResponse(result, status_code=200)


@app.post("/api/agent-actions/{ai_call_id}/reject")
async def api_reject_agent_action(
    ai_call_id: int,
    user: dict = Depends(current_user),
):
    """POST /api/agent-actions/{id}/reject — owner rejects a pending draft.

    Returns: {status, ai_call_id}.
    """
    result = workspace_mod.reject_action(user, ai_call_id)
    return JSONResponse(result, status_code=200)


# ─────────────────────────────────────────────
# S4c — AI HTML pages: scoping, matching, workspace, firewall
# ─────────────────────────────────────────────

def _ai_call_info(project_id: int, task: str) -> Optional[dict]:
    """Return a small dict with agent/owner/route info from the latest ai_call for a task."""
    row = query_one(
        """
        SELECT ac.model_route, ac.prompt_summary,
               a.name AS agent_name,
               u.name AS owner_name
        FROM ai_calls ac
        LEFT JOIN agents a ON a.id = ac.agent_id
        LEFT JOIN users u ON u.id = ac.human_owner_id
        WHERE ac.project_id = ? AND ac.prompt_summary LIKE ?
        ORDER BY ac.id DESC LIMIT 1
        """,
        (project_id, f'%"task": "{task}"%'),
    )
    if not row:
        return None
    try:
        ps = json.loads(row["prompt_summary"] or "{}")
    except Exception:
        ps = {}
    return {
        "agent_name": row["agent_name"] or "scoping agent",
        "owner_name": row["owner_name"] or "—",
        "intended_route": ps.get("intended_route"),
        "actual_route": row["model_route"],
        "fallback_reason": ps.get("fallback_reason"),
    }


def _scoping_context(request: Request, project_id: int, user: Any) -> dict:
    """Build template context for the scoping page."""
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    sponsor = query_one("SELECT * FROM users WHERE id = ?", (project["sponsor_id"],))
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    can_scope = bool(user and (user["id"] == project["sponsor_id"] or user["role"] == "admin"))
    is_funded = project["engagement_model"] in ("funded", "stipend")
    proposed = []
    opened = []
    ai_info = None
    if can_scope:
        proposed = [dict(r) for r in query_all(
            "SELECT * FROM milestones WHERE project_id = ? AND status = 'proposed' ORDER BY id ASC",
            (project_id,),
        )]
        opened = [dict(r) for r in query_all(
            "SELECT * FROM milestones WHERE project_id = ? AND status = 'open' ORDER BY id ASC",
            (project_id,),
        )]
        ai_info = _ai_call_info(project_id, "scoping")
    return {
        "project": project,
        "sponsor": sponsor,
        "all_users": all_users,
        "user": user,
        "can_scope": can_scope,
        "is_funded": is_funded,
        "proposed_milestones": proposed,
        "open_milestones": opened,
        "ai_call_info": ai_info,
        "error": None,
        "error_code": None,
    }


@app.get("/projects/{project_id}/scoping")
def ui_scoping_get(
    project_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    ctx = _scoping_context(request, project_id, user)
    return templates.TemplateResponse(request, "scoping.html", ctx)


@app.post("/projects/{project_id}/scoping")
async def ui_scoping_post(
    project_id: int,
    request: Request,
    budget_inr: Optional[str] = Form(None),
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    from app.ai.scoping import propose_milestones
    try:
        propose_milestones(user, project_id, budget_inr=budget_inr)
        return RedirectResponse(url=f"/projects/{project_id}/scoping", status_code=303)
    except HTTPException as e:
        ctx = _scoping_context(request, project_id, user)
        ctx["error"] = e.detail
        ctx["error_code"] = e.status_code
        return templates.TemplateResponse(request, "scoping.html", ctx, status_code=e.status_code)


@app.post("/milestones/{milestone_id}/approve-ui")
async def ui_approve_milestone(
    milestone_id: int,
    request: Request,
    amount_inr: Optional[str] = Form(None),
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    from app.services.milestones import approve_milestone
    milestone = query_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,))
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")
    project_id = milestone["project_id"]
    try:
        amt = int(amount_inr.strip()) if amount_inr and amount_inr.strip() else None
        approve_milestone(user, milestone_id, amount_inr=amt)
        return RedirectResponse(url=f"/projects/{project_id}/scoping", status_code=303)
    except HTTPException as e:
        ctx = _scoping_context(request, project_id, user)
        ctx["error"] = e.detail
        ctx["error_code"] = e.status_code
        return templates.TemplateResponse(request, "scoping.html", ctx, status_code=e.status_code)


# ── Matching ──

def _matching_context(request: Request, project_id: int, user: Any) -> dict:
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    can_match = bool(user and (user["id"] == project["sponsor_id"] or user["role"] == "admin"))
    match_result = None
    ai_info = None
    if can_match:
        from app.ai.matching import latest as match_latest
        try:
            match_result = match_latest(user, project_id)
        except HTTPException:
            pass
        ai_info = _ai_call_info(project_id, "matching")
    return {
        "project": project,
        "all_users": all_users,
        "user": user,
        "can_match": can_match,
        "match_result": match_result,
        "ai_call_info": ai_info,
        "error": None,
        "error_code": None,
    }


@app.get("/projects/{project_id}/matching")
def ui_matching_get(
    project_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    ctx = _matching_context(request, project_id, user)
    return templates.TemplateResponse(request, "matching.html", ctx)


@app.post("/projects/{project_id}/matching")
async def ui_matching_post(
    project_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    from app.ai.matching import recommend
    try:
        recommend(user, project_id)
        return RedirectResponse(url=f"/projects/{project_id}/matching", status_code=303)
    except HTTPException as e:
        ctx = _matching_context(request, project_id, user)
        ctx["error"] = e.detail
        ctx["error_code"] = e.status_code
        return templates.TemplateResponse(request, "matching.html", ctx, status_code=e.status_code)


# ── Workspace ──

def _workspace_context(request: Request, project_id: int, user: Any) -> dict:
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    can_access = can_view(user, project, "milestones")
    is_member = bool(
        user and user["role"] in ("student", "expert")
        and membership_state(project_id, user["id"]) == "member"
    )
    actions = []
    open_milestones = []
    if can_access:
        from app.ai import workspace as workspace_mod2
        try:
            actions = workspace_mod2.list_actions(user, project_id)
        except HTTPException:
            actions = []
        if is_member:
            open_milestones = [
                dict(r) for r in query_all(
                    "SELECT * FROM milestones WHERE project_id = ? AND status = 'open' ORDER BY id ASC",
                    (project_id,),
                )
            ]
    return {
        "project": project,
        "all_users": all_users,
        "user": user,
        "can_access": can_access,
        "is_member": is_member,
        "actions": actions,
        "open_milestones": open_milestones,
        "error": None,
        "error_code": None,
    }


@app.get("/projects/{project_id}/workspace")
def ui_workspace_get(
    project_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    ctx = _workspace_context(request, project_id, user)
    return templates.TemplateResponse(request, "workspace.html", ctx)


@app.post("/projects/{project_id}/workspace")
async def ui_workspace_post(
    project_id: int,
    request: Request,
    milestone_id: Optional[str] = Form(None),
    instruction: Optional[str] = Form(None),
    source_text: str = Form(""),
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    from app.ai import workspace as workspace_mod2
    try:
        ms_id = int(milestone_id) if milestone_id and milestone_id.strip() else None
        if not ms_id:
            raise HTTPException(status_code=400, detail="Please select a milestone.")
        workspace_mod2.draft(user, ms_id, instruction or "", source_text)
        return RedirectResponse(url=f"/projects/{project_id}/workspace", status_code=303)
    except HTTPException as e:
        ctx = _workspace_context(request, project_id, user)
        ctx["error"] = e.detail
        ctx["error_code"] = e.status_code
        return templates.TemplateResponse(request, "workspace.html", ctx, status_code=e.status_code)


@app.post("/workspace-actions/{ai_call_id}/approve-ui")
async def ui_approve_workspace_action(
    ai_call_id: int,
    request: Request,
    project_id: int = Form(...),
    confirm_flagged: Optional[str] = Form(None),
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    from app.ai import workspace as workspace_mod2
    cf = confirm_flagged == "true" or confirm_flagged == "on"
    try:
        workspace_mod2.approve_action(user, ai_call_id, confirm_flagged=cf)
        return RedirectResponse(url=f"/projects/{project_id}/workspace", status_code=303)
    except HTTPException as e:
        ctx = _workspace_context(request, project_id, user)
        ctx["error"] = e.detail
        ctx["error_code"] = e.status_code
        return templates.TemplateResponse(request, "workspace.html", ctx, status_code=e.status_code)


@app.post("/workspace-actions/{ai_call_id}/reject-ui")
async def ui_reject_workspace_action(
    ai_call_id: int,
    request: Request,
    project_id: int = Form(...),
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    from app.ai import workspace as workspace_mod2
    try:
        workspace_mod2.reject_action(user, ai_call_id)
        return RedirectResponse(url=f"/projects/{project_id}/workspace", status_code=303)
    except HTTPException as e:
        ctx = _workspace_context(request, project_id, user)
        ctx["error"] = e.detail
        ctx["error_code"] = e.status_code
        return templates.TemplateResponse(request, "workspace.html", ctx, status_code=e.status_code)


# ── Firewall ──

@app.get("/projects/{project_id}/firewall")
def ui_firewall_get(
    project_id: int,
    request: Request,
    user: Optional[sqlite3.Row] = Depends(current_user),
):
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    all_users = query_all("SELECT * FROM users ORDER BY id ASC")
    can_access = can_view(user, project, "milestones")

    total_calls = 0
    confidential_external = 0
    blocked_tools_count = 0
    pending_approvals = 0
    calls_display = []

    if can_access:
        total_calls = (
            query_one("SELECT COUNT(*) as c FROM ai_calls WHERE project_id = ?", (project_id,))["c"]
        )
        confidential_external = query_one(
            "SELECT COUNT(*) as c FROM ai_calls WHERE project_id = ? AND sensitivity_label = 'confidential' AND model_route = 'api'",
            (project_id,),
        )["c"]
        blocked_tools_count = query_one(
            "SELECT COUNT(*) as c FROM ledger_entries WHERE action = 'agent_action_blocked' AND project_id = ?",
            (project_id,),
        )["c"]
        pending_approvals = query_one(
            "SELECT COUNT(*) as c FROM ai_calls WHERE project_id = ? AND prompt_summary LIKE '%\"status\": \"pending\"%'",
            (project_id,),
        )["c"]

        rows = query_all(
            """
            SELECT ac.*, a.name AS agent_name, u.name AS owner_name
            FROM ai_calls ac
            LEFT JOIN agents a ON a.id = ac.agent_id
            LEFT JOIN users u ON u.id = ac.human_owner_id
            WHERE ac.project_id = ?
            ORDER BY ac.id DESC
            """,
            (project_id,),
        )
        for row in rows:
            r = dict(row)
            try:
                r["ps"] = json.loads(r.get("prompt_summary") or "{}")
            except Exception:
                r["ps"] = {}
            calls_display.append(r)

    return templates.TemplateResponse(
        request,
        "firewall.html",
        {
            "project": project,
            "all_users": all_users,
            "user": user,
            "can_access": can_access,
            "total_calls": total_calls,
            "confidential_external": confidential_external,
            "blocked_tools_count": blocked_tools_count,
            "pending_approvals": pending_approvals,
            "calls_display": calls_display,
        },
    )
