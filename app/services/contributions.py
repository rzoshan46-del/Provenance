"""
app/services/contributions.py — Contribution Submission & Review Service for Provenance.
"""
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.access import can_view, membership_state
from app.db import execute, query_all, query_one
import app.ledger as ledger


_VALID_AI_DECLARATIONS = frozenset({"human", "ai_assisted", "agent_generated"})


def submit_contribution(
    user: Any,
    milestone_id: int,
    title: str,
    text: str,
    ai_declaration: str,
    agent_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Submit a contribution artefact to a milestone.

    Rules:
    - User must have membership_state == 'member' of the current charter version (403).
    - ai_declaration must be human, ai_assisted, or agent_generated (400).
    - Funded projects: escrow must be in state 'funded' (409).
    - Non-funded projects: milestone status must be 'open' (409).
    - artefact_hash = SHA-256(text).
    - Ledger action: contribution_submitted (artefact text is NEVER stored in the ledger).
    """
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    milestone = query_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,))
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    project = query_one("SELECT * FROM projects WHERE id = ?", (milestone["project_id"],))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 1. Charter membership validation
    uid = user["id"]
    state = membership_state(project["id"], uid)
    if state != "member":
        raise HTTPException(
            status_code=403,
            detail="You must be an active member of the current charter version to submit contributions",
        )

    # 2. AI Declaration validation
    if not ai_declaration or ai_declaration not in _VALID_AI_DECLARATIONS:
        raise HTTPException(
            status_code=400,
            detail="ai_declaration must be one of: human, ai_assisted, agent_generated",
        )

    title_str = (title or "").strip()
    if not title_str:
        raise HTTPException(status_code=400, detail="Artefact title is required")

    text_str = text or ""

    # 3. Escrow / Milestone Status checks
    is_funded = project["engagement_model"] in ("funded", "stipend")
    if is_funded:
        escrow = query_one(
            "SELECT * FROM escrows WHERE milestone_id = ?", (milestone_id,)
        )
        if not escrow or escrow["state"] != "funded":
            raise HTTPException(
                status_code=409,
                detail="Work cannot be submitted until the milestone escrow is funded",
            )
    else:
        if milestone["status"] != "open":
            raise HTTPException(
                status_code=409,
                detail=f"Milestone is not open for contributions (status: {milestone['status']})",
            )

    artefact_hash = hashlib.sha256(text_str.encode("utf-8")).hexdigest()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    contribution_id = execute(
        """
        INSERT INTO contributions (
            milestone_id, author_id, agent_id, artefact_title, artefact_text,
            artefact_hash, ai_declaration, similarity_score, review_status,
            impact_weight, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0.0, 'pending', 1.0, ?)
        """,
        (
            milestone_id,
            uid,
            agent_id,
            title_str,
            text_str,
            artefact_hash,
            ai_declaration,
            now_iso,
        ),
    )

    # Record ledger entry (NEVER store the artefact text in ledger - SPEC §17, §18)
    ledger_payload: Dict[str, Any] = {
        "contribution_id": contribution_id,
        "milestone_id": milestone_id,
        "artefact_hash": artefact_hash,
        "ai_declaration": ai_declaration,
    }
    if agent_id is not None:
        ledger_payload["agent_id"] = agent_id

    ledger.append(
        action="contribution_submitted",
        actor_id=uid,
        actor_type="human",
        human_owner_id=uid,
        project_id=project["id"],
        payload=ledger_payload,
    )

    from app.integrity.service import check_contribution
    check_contribution(contribution_id)

    return {
        "status": "submitted",
        "contribution_id": contribution_id,
        "artefact_hash": artefact_hash,
    }


def review_contribution(
    user: Any,
    contribution_id: int,
    decision: str,
    impact_score: Optional[Any] = None,
    reasons: Optional[str] = None,
    criteria_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Review a submitted contribution.

    Rules:
    - Reviewer must be an EXPERT with membership_state == 'member' (403).
    - Reviewer cannot be the contribution author (403).
    - Reviewer must not have conflict of interest with sponsor's institution (403).
    - Contribution must be in review_status 'pending' or 'flagged' (409).
    - decision must be 'approve' or 'reject' (400).
    - approve requires integer impact_score between 1 and 10 (400), stored as impact_weight.
    - reject requires non-empty reasons (400).
    - Inserts row into reviews, updates contribution review_status, and logs review_recorded.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    contribution = query_one(
        "SELECT * FROM contributions WHERE id = ?", (contribution_id,)
    )
    if not contribution:
        raise HTTPException(status_code=404, detail="Contribution not found")

    milestone = query_one(
        "SELECT * FROM milestones WHERE id = ?", (contribution["milestone_id"],)
    )
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    project = query_one("SELECT * FROM projects WHERE id = ?", (milestone["project_id"],))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 1. Reviewer role check (Expert role required)
    if user["role"] != "expert":
        raise HTTPException(
            status_code=403, detail="Only expert members can review contributions"
        )

    # 2. Reviewer membership check
    state = membership_state(project["id"], user["id"])
    if state != "member":
        raise HTTPException(
            status_code=403, detail="Reviewer must be an active member of the project"
        )

    # 3. Self-review prohibition
    if user["id"] == contribution["author_id"]:
        raise HTTPException(
            status_code=403, detail="Experts cannot review their own contributions"
        )

    # 4. Conflict of interest check
    sponsor = query_one("SELECT * FROM users WHERE id = ?", (project["sponsor_id"],))
    sponsor_inst = sponsor["institution"] if sponsor else None
    conflict_orgs = []
    if user["conflict_orgs"]:
        try:
            conflict_orgs = (
                json.loads(user["conflict_orgs"])
                if isinstance(user["conflict_orgs"], str)
                else user["conflict_orgs"]
            )
        except Exception:
            conflict_orgs = []

    if sponsor_inst and sponsor_inst in conflict_orgs:
        raise HTTPException(
            status_code=403,
            detail="conflict of interest: reviewer has conflict with sponsor institution",
        )

    # 5. Review status check
    if contribution["review_status"] not in ("pending", "flagged"):
        raise HTTPException(
            status_code=409,
            detail=f"Contribution has already been reviewed (status: {contribution['review_status']})",
        )

    dec = (decision or "").strip().lower()
    if dec not in ("approve", "reject"):
        raise HTTPException(
            status_code=400, detail="Decision must be either 'approve' or 'reject'"
        )

    # 6. Decision specifics
    reasons_str = str(reasons or "").strip()
    criteria_str = str(criteria_ref or "").strip()

    if contribution["review_status"] == "flagged" and not reasons_str:
        raise HTTPException(
            status_code=400,
            detail="written justification required for flagged work",
        )

    if dec == "approve":
        if impact_score is None:
            raise HTTPException(
                status_code=400, detail="impact_score is required for approval"
            )
        try:
            if isinstance(impact_score, str):
                if "." in impact_score:
                    raise ValueError("non-integer impact_score")
                score_int = int(impact_score)
            elif isinstance(impact_score, int) and not isinstance(impact_score, bool):
                score_int = impact_score
            else:
                raise ValueError("invalid impact_score type")
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail="impact_score must be an integer between 1 and 10",
            )

        if score_int < 1 or score_int > 10:
            raise HTTPException(
                status_code=400,
                detail="impact_score must be an integer between 1 and 10",
            )

        impact_weight = float(score_int)
        new_status = "approved"
    else:
        if not reasons_str:
            raise HTTPException(
                status_code=400,
                detail="Reasons are required when rejecting a contribution",
            )
        score_int = None
        impact_weight = 0.0
        new_status = "rejected"

    now_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    # Insert review
    execute(
        """
        INSERT INTO reviews (contribution_id, reviewer_id, decision, reasons, criteria_ref, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (contribution_id, user["id"], dec, reasons_str, criteria_str, now_iso),
    )

    # Update contribution
    execute(
        """
        UPDATE contributions
        SET review_status = ?, impact_weight = ?
        WHERE id = ?
        """,
        (new_status, impact_weight, contribution_id),
    )

    reasons_hash = (
        hashlib.sha256(reasons_str.encode("utf-8")).hexdigest() if reasons_str else ""
    )

    # Record ledger entry
    ledger.append(
        action="review_recorded",
        actor_id=user["id"],
        actor_type="human",
        human_owner_id=user["id"],
        project_id=project["id"],
        payload={
            "contribution_id": contribution_id,
            "decision": dec,
            "impact_score": score_int,
            "criteria_ref": criteria_str,
            "reasons_hash": reasons_hash,
        },
    )

    return {
        "status": new_status,
        "contribution_id": contribution_id,
        "impact_weight": impact_weight,
    }


def list_contributions(user: Any, milestone_id: int) -> List[Dict[str, Any]]:
    """List all contributions for a milestone.

    Requires access.can_view(user, project, 'milestones') else 403.
    """
    milestone = query_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,))
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    project = query_one("SELECT * FROM projects WHERE id = ?", (milestone["project_id"],))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not can_view(user, project, "milestones"):
        raise HTTPException(status_code=403, detail="Access denied to contributions")

    rows = query_all(
        """
        SELECT c.*, u.name AS author_name, u.role AS author_role
        FROM contributions c
        JOIN users u ON u.id = c.author_id
        WHERE c.milestone_id = ?
        ORDER BY c.id ASC
        """,
        (milestone_id,),
    )
    from app.integrity.provenance import label as provenance_label
    from app.integrity.service import protect
    result = []
    for r in rows:
        d = dict(r)
        d["provenance"] = provenance_label(d)
        if d.get("artefact_text"):
            d["artefact_text"] = protect(
                viewer=user,
                owner_id=d["author_id"],
                text=d["artefact_text"],
                resource="contribution",
                resource_id=d["id"],
                project_id=project["id"],
            )
        result.append(d)
    return result
