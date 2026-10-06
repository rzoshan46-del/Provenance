"""
app/services/milestones.py — Milestone Management Service for Provenance.
"""
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.access import can_view
from app.db import execute, query_all, query_one
import app.ledger as ledger


def create_milestone(user: Any, project_id: int, fields: Dict[str, Any]) -> int:
    """Create a new milestone on a project.

    Rules:
    - Only the owning sponsor can create milestones (403).
    - Funded project: amount_inr must be a positive integer (400); escrows row created in 'draft'.
    - Non-funded project: amount_inr must be 0 (400 "non-monetary projects cannot carry an amount"); no escrow row.
    - Status is set to 'open'.
    - Records ledger entry with action 'milestone_created'.
    """
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not user or user["id"] != project["sponsor_id"]:
        raise HTTPException(
            status_code=403, detail="Only the owning sponsor can create milestones"
        )

    title = str(fields.get("title", "")).strip()
    if not title:
        raise HTTPException(status_code=400, detail="Milestone title is required")

    deliverables = str(fields.get("deliverables", "")).strip()
    acceptance_criteria = str(fields.get("acceptance_criteria", "")).strip()

    # Skills parsing: comma-separated string or list -> JSON list
    raw_skills = fields.get("required_skills", [])
    if isinstance(raw_skills, str):
        skills_list = [s.strip() for s in raw_skills.split(",") if s.strip()]
    elif isinstance(raw_skills, list):
        skills_list = [str(s).strip() for s in raw_skills if str(s).strip()]
    else:
        skills_list = []
    required_skills_json = json.dumps(skills_list)

    # Acceptance window days
    try:
        acceptance_window_days = int(fields.get("acceptance_window_days", 7))
        if acceptance_window_days <= 0:
            acceptance_window_days = 7
    except (ValueError, TypeError):
        acceptance_window_days = 7

    # Amount validation based on engagement model
    raw_amount = fields.get("amount_inr", 0)
    # Parse integer if string passed
    try:
        if isinstance(raw_amount, str):
            raw_amount = raw_amount.strip()
            # If string contains decimal point, it is not an integer
            if "." in raw_amount:
                raise ValueError("non-integer amount")
            amount_inr = int(raw_amount)
        elif isinstance(raw_amount, int) and not isinstance(raw_amount, bool):
            amount_inr = raw_amount
        else:
            raise ValueError("invalid amount type")
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400, detail="Milestone amount must be a valid integer"
        )

    is_funded = project["engagement_model"] in ("funded", "stipend")

    if is_funded:
        if amount_inr <= 0:
            raise HTTPException(
                status_code=400,
                detail="Funded milestones must carry a positive integer amount",
            )
    else:
        if amount_inr != 0:
            raise HTTPException(
                status_code=400,
                detail="non-monetary projects cannot carry an amount",
            )

    now_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    milestone_id = execute(
        """
        INSERT INTO milestones (
            project_id, title, deliverables, acceptance_criteria,
            required_skills, amount_inr, status, acceptance_window_days, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)
        """,
        (
            project_id,
            title,
            deliverables,
            acceptance_criteria,
            required_skills_json,
            amount_inr,
            acceptance_window_days,
            now_iso,
        ),
    )

    # Create escrow row in state 'draft' if funded
    if is_funded:
        execute(
            """
            INSERT INTO escrows (milestone_id, amount_inr, state, updated_at)
            VALUES (?, ?, 'draft', ?)
            """,
            (milestone_id, amount_inr, now_iso),
        )

    # Record ledger entry
    actor_id = user["id"] if isinstance(user, (dict, sqlite3.Row)) else user
    ledger.append(
        action="milestone_created",
        actor_id=actor_id,
        actor_type="human",
        human_owner_id=actor_id,
        project_id=project_id,
        payload={
            "milestone_id": milestone_id,
            "title": title,
            "engagement_model": project["engagement_model"],
            "amount_inr": amount_inr,
        },
    )

    return milestone_id


def list_milestones(user: Any, project_id: int) -> List[Dict[str, Any]]:
    """List all milestones for a project with their escrow states.

    Requires access.can_view(user, project, 'milestones') else 403.
    """
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not can_view(user, project, "milestones"):
        raise HTTPException(status_code=403, detail="Access denied to milestones")

    rows = query_all(
        """
        SELECT m.*, e.state AS escrow_state, e.id AS escrow_id
        FROM milestones m
        LEFT JOIN escrows e ON e.milestone_id = m.id
        WHERE m.project_id = ?
        ORDER BY m.id ASC
        """,
        (project_id,),
    )

    result = []
    for r in rows:
        d = dict(r)
        try:
            d["required_skills"] = json.loads(d.get("required_skills") or "[]")
        except Exception:
            d["required_skills"] = []
        result.append(d)

    return result


def get_milestone(user: Any, milestone_id: int) -> Dict[str, Any]:
    """Retrieve a single milestone by id.

    Requires access.can_view(user, project, 'milestones') else 403.
    """
    milestone = query_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,))
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    project = query_one("SELECT * FROM projects WHERE id = ?", (milestone["project_id"],))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not can_view(user, project, "milestones"):
        raise HTTPException(status_code=403, detail="Access denied to milestone")

    escrow = query_one(
        "SELECT * FROM escrows WHERE milestone_id = ?", (milestone_id,)
    )

    result = dict(milestone)
    try:
        result["required_skills"] = json.loads(result.get("required_skills") or "[]")
    except Exception:
        result["required_skills"] = []
    result["escrow_state"] = escrow["state"] if escrow else None
    result["escrow_id"] = escrow["id"] if escrow else None

    return result
