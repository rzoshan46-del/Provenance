"""
app/services/milestones.py — Milestone Management Service for Provenance.
"""
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.access import can_view, membership_state
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

    is_sponsor_or_admin = user and (user["id"] == project["sponsor_id"] or user["role"] == "admin")

    result = []
    for r in rows:
        d = dict(r)
        # Proposed milestones are visible only to the owning sponsor and admin (SPEC §19)
        if d.get("status") == "proposed" and not is_sponsor_or_admin:
            continue
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

    is_sponsor_or_admin = user and (user["id"] == project["sponsor_id"] or user["role"] == "admin")
    if milestone["status"] == "proposed" and not is_sponsor_or_admin:
        raise HTTPException(status_code=403, detail="Proposed milestones are visible only to sponsor and admin")

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


def approve_milestone(user: Any, milestone_id: int, amount_inr: Optional[Any] = None) -> Dict[str, Any]:
    """Approve a proposed milestone.

    Rules (SPEC §19):
    - Only the owning sponsor can approve (403).
    - Status must be 'proposed' (409 otherwise, e.g. already approved or open).
    - Sets status to 'open'.
    - If funded:
      - amount_inr can optionally override milestone's amount_inr (must be positive integer).
      - creates an escrow row in state 'draft'.
    - If non-funded:
      - amount_inr remains 0, no escrow row created.
    - Writes ledger milestone_approved entry.
    """
    milestone = query_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,))
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    project = query_one("SELECT * FROM projects WHERE id = ?", (milestone["project_id"],))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not user or user["id"] != project["sponsor_id"]:
        raise HTTPException(status_code=403, detail="Only the owning sponsor can approve milestones")

    if milestone["status"] != "proposed":
        raise HTTPException(
            status_code=409,
            detail=f"Milestone is in '{milestone['status']}' status; only proposed milestones can be approved",
        )

    is_funded = project["engagement_model"] in ("funded", "stipend")
    final_amount = milestone["amount_inr"]

    if amount_inr is not None and str(amount_inr).strip() != "":
        if is_funded:
            try:
                amt_str = str(amount_inr).strip()
                if "." in amt_str:
                    raise ValueError()
                val = int(amt_str)
                if val <= 0:
                    raise ValueError()
                final_amount = val
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="amount_inr must be a valid positive integer")
        else:
            final_amount = 0

    now_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    # Update milestone status to 'open'
    execute(
        "UPDATE milestones SET status = 'open', amount_inr = ? WHERE id = ?",
        (final_amount, milestone_id),
    )

    # Funded projects get an escrow row in state 'draft'
    if is_funded:
        execute(
            """
            INSERT INTO escrows (milestone_id, amount_inr, state, updated_at)
            VALUES (?, ?, 'draft', ?)
            """,
            (milestone_id, final_amount, now_iso),
        )

    # Ledger milestone_approved
    ledger.append(
        action="milestone_approved",
        actor_id=user["id"],
        actor_type="human",
        human_owner_id=user["id"],
        project_id=project["id"],
        payload={
            "milestone_id": milestone_id,
            "title": milestone["title"],
            "amount_inr": final_amount,
        },
    )

    return get_milestone(user, milestone_id)



def submit_milestone(user: Any, milestone_id: int) -> Dict[str, Any]:
    """Submit a completed milestone for sponsor review.

    Rules:
    - User must be an EXPERT with membership_state == 'member' on the project (403).
    - Milestone must be in status 'open' (409).
    - Requires at least one approved contribution on this milestone (409).
    - Funded project: transitions escrow from 'funded' to 'submitted' via escrow_transition.
    - Updates milestone status to 'submitted'.
    - Records milestone_submitted ledger entry.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    milestone = query_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,))
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    project = query_one("SELECT * FROM projects WHERE id = ?", (milestone["project_id"],))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 1. Expert member check
    if user["role"] != "expert":
        raise HTTPException(
            status_code=403, detail="Only expert members can submit milestones"
        )

    state = membership_state(project["id"], user["id"])
    if state != "member":
        raise HTTPException(
            status_code=403, detail="Submitter must be an active member of the project"
        )

    # 2. Status check
    if milestone["status"] != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Milestone is not open for submission (status: {milestone['status']})",
        )

    # 3. Approved contributions check
    approved_count_row = query_one(
        "SELECT COUNT(*) AS c FROM contributions WHERE milestone_id = ? AND review_status = 'approved'",
        (milestone_id,),
    )
    approved_count = approved_count_row["c"] if approved_count_row else 0
    if approved_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Cannot submit milestone without at least one approved contribution",
        )

    is_funded = project["engagement_model"] in ("funded", "stipend")
    if is_funded:
        escrow = query_one(
            "SELECT * FROM escrows WHERE milestone_id = ?", (milestone_id,)
        )
        if not escrow or escrow["state"] != "funded":
            raise HTTPException(
                status_code=409,
                detail="Escrow must be funded before milestone submission",
            )
        from app.services.escrow import escrow_transition
        escrow_transition(escrow["id"], "submitted", user)

    # Update milestone status to 'submitted'
    execute(
        "UPDATE milestones SET status = 'submitted' WHERE id = ?",
        (milestone_id,),
    )

    ledger.append(
        action="milestone_submitted",
        actor_id=user["id"],
        actor_type="human",
        human_owner_id=user["id"],
        project_id=project["id"],
        payload={"milestone_id": milestone_id},
    )

    return {"status": "submitted", "milestone_id": milestone_id}


def accept_milestone(user: Any, milestone_id: int) -> Dict[str, Any]:
    """Accept a submitted milestone, trigger payouts (if funded), and issue credentials.

    Rules:
    - Only the owning sponsor can accept milestones (403).
    - Milestone status must be 'submitted' (409).
    - Funded project: calls payouts.release_milestone (split, payouts, escrow accepted/released).
    - Non-funded project: sets milestone status to 'accepted', logs milestone_accepted (no escrow, no payouts).
    - All projects: issues certificate credentials to all approved contributors via payouts.issue_credentials.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    milestone = query_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,))
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    project = query_one("SELECT * FROM projects WHERE id = ?", (milestone["project_id"],))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 1. Sponsor authorization
    if user["id"] != project["sponsor_id"]:
        raise HTTPException(
            status_code=403, detail="Only the owning sponsor can accept milestones"
        )

    # 2. Milestone status check (must be submitted)
    if milestone["status"] != "submitted":
        raise HTTPException(
            status_code=409,
            detail=f"Milestone cannot be accepted in status '{milestone['status']}' (must be 'submitted')",
        )

    is_funded = project["engagement_model"] in ("funded", "stipend")

    from app.services import payouts

    if is_funded:
        escrow = query_one(
            "SELECT * FROM escrows WHERE milestone_id = ?", (milestone_id,)
        )
        if not escrow or escrow["state"] != "submitted":
            raise HTTPException(
                status_code=409,
                detail="Escrow must be in 'submitted' state for milestone acceptance",
            )
        payouts.release_milestone(user, milestone, project, escrow)
    else:
        # Non-monetary: no payouts, no escrow
        ledger.append(
            action="milestone_accepted",
            actor_id=user["id"],
            actor_type="human",
            human_owner_id=user["id"],
            project_id=project["id"],
            payload={"milestone_id": milestone_id},
        )

    # Issue credentials for all approved contributors across all engagement models
    payouts.issue_credentials(user, milestone, project)

    # Update milestone status to 'accepted'
    execute(
        "UPDATE milestones SET status = 'accepted' WHERE id = ?",
        (milestone_id,),
    )

    return {"status": "accepted", "milestone_id": milestone_id}

