"""
app/services/escrow.py — Escrow State Machine and Funding Service.

MOCKED: production would use a payment gateway and KYC (SPEC.md §18).
"""
from datetime import datetime, timezone
import sqlite3
from typing import Any, Dict, Optional, Set

from fastapi import HTTPException

from app.db import execute, query_one
import app.ledger as ledger


ALLOWED: Dict[str, Set[str]] = {
    "draft": {"funded"},
    "funded": {"submitted"},
    "submitted": {"accepted", "funded"},
    "accepted": {"released"},
    "disputed": {"released", "refunded"},
    "released": set(),
    "refunded": set(),
}


def escrow_transition(
    escrow_id: int,
    to_state: str,
    actor: Any,
    ledger_action: str = "escrow_state_changed",
    extra_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute a state transition on an escrow row and record a ledger entry.

    Raises ValueError on an illegal transition or unknown escrow.
    Note: Database updates are committed BEFORE calling ledger.append to avoid
    holding open transactions that could lock SQLite.
    """
    escrow = query_one("SELECT * FROM escrows WHERE id = ?", (escrow_id,))
    if not escrow:
        raise ValueError(f"Escrow #{escrow_id} not found")

    from_state = escrow["state"]
    allowed_next = ALLOWED.get(from_state, set())
    if to_state not in allowed_next:
        raise ValueError(
            f"Illegal escrow transition from '{from_state}' to '{to_state}'"
        )

    now_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    execute(
        "UPDATE escrows SET state = ?, updated_at = ? WHERE id = ?",
        (to_state, now_iso, escrow_id),
    )

    # Resolve milestone and project id
    milestone = query_one(
        "SELECT * FROM milestones WHERE id = ?", (escrow["milestone_id"],)
    )
    project_id = milestone["project_id"] if milestone else None

    # Actor ID resolution — actor=None means system action
    if actor is None:
        actor_id = None
        resolved_actor_type = "system"
        human_owner_id = None
    elif isinstance(actor, (dict, sqlite3.Row)):
        actor_id = actor["id"]
        resolved_actor_type = "human"
        human_owner_id = actor_id
    elif isinstance(actor, int):
        actor_id = actor
        resolved_actor_type = "human"
        human_owner_id = actor_id
    else:
        actor_id = None
        resolved_actor_type = "system"
        human_owner_id = None

    payload: Dict[str, Any] = {
        "milestone_id": escrow["milestone_id"],
        "from": from_state,
        "to": to_state,
    }
    if extra_payload:
        payload.update(extra_payload)

    # Write ledger entry after DB commit
    ledger.append(
        action=ledger_action,
        actor_id=actor_id,
        actor_type=resolved_actor_type,
        human_owner_id=human_owner_id,
        project_id=project_id,
        payload=payload,
    )

    return {
        "escrow_id": escrow_id,
        "milestone_id": escrow["milestone_id"],
        "from_state": from_state,
        "to_state": to_state,
    }


def fund_milestone(user: Any, milestone_id: int) -> Dict[str, Any]:
    """Fund a milestone's escrow account.

    Only the owning sponsor can fund. Non-funded projects reject with 400.
    Escrow must currently be in state 'draft'.
    """
    # MOCKED: production would use a payment gateway and KYC (SPEC.md §18)
    milestone = query_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,))
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    project = query_one("SELECT * FROM projects WHERE id = ?", (milestone["project_id"],))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Access control: only the owning sponsor (403)
    if not user or user["id"] != project["sponsor_id"]:
        raise HTTPException(
            status_code=403, detail="Only the owning sponsor can fund milestones"
        )

    # Non-monetary check: engagement_model must be funded or stipend (400)
    if project["engagement_model"] not in ("funded", "stipend"):
        raise HTTPException(
            status_code=400, detail="no escrow on non-funded projects"
        )

    escrow = query_one(
        "SELECT * FROM escrows WHERE milestone_id = ?", (milestone_id,)
    )
    if not escrow:
        raise HTTPException(
            status_code=400, detail="no escrow on non-funded projects"
        )

    if escrow["state"] != "draft":
        raise HTTPException(
            status_code=409,
            detail=f"Escrow is already in state '{escrow['state']}', cannot fund",
        )

    escrow_transition(
        escrow_id=escrow["id"],
        to_state="funded",
        actor=user,
        ledger_action="escrow_funded",
        extra_payload={"amount_inr": escrow["amount_inr"]},
    )

    return {
        "status": "funded",
        "milestone_id": milestone_id,
        "amount_inr": escrow["amount_inr"],
    }
