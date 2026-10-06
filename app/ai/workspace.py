"""
app/ai/workspace.py — Workspace Agent: draft, list_actions, approve_action, reject_action.

The workspace agent helps members draft research contributions.  Every draft
goes through the gateway security pipeline; no tool executes automatically.
A human-approval gate (approve_action / reject_action) converts a pending
draft into a real contribution or discards it.
"""
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.access import membership_state
from app.ai.agents import get_agent, get_or_create_agent
from app.ai import gateway
from app.db import execute, query_all, query_one
import app.ledger as ledger
import app.services.contributions as contributions_svc


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_user(user_id: int) -> Dict[str, Any]:
    """Fetch a user row by id; raise 500 if missing (should never happen)."""
    row = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not row:
        raise HTTPException(status_code=500, detail="User record not found")
    return dict(row)


def _patch_ai_call_status(call_id: int, new_status: str) -> None:
    """Update the status field inside ai_calls.prompt_summary JSON."""
    row = query_one("SELECT prompt_summary FROM ai_calls WHERE id = ?", (call_id,))
    if not row:
        return
    try:
        ps = json.loads(row["prompt_summary"] or "{}")
    except Exception:
        ps = {}
    ps["status"] = new_status
    execute(
        "UPDATE ai_calls SET prompt_summary = ? WHERE id = ?",
        (json.dumps(ps, sort_keys=True), call_id),
    )


def _get_ai_call(call_id: int) -> Dict[str, Any]:
    row = query_one("SELECT * FROM ai_calls WHERE id = ?", (call_id,))
    if not row:
        raise HTTPException(status_code=404, detail="AI call not found")
    return dict(row)


def _require_workspace_draft(call_id: int) -> Dict[str, Any]:
    """Return the ai_calls row and ensure it is a workspace_draft task."""
    row = _get_ai_call(call_id)
    try:
        ps = json.loads(row.get("prompt_summary") or "{}")
    except Exception:
        ps = {}
    if ps.get("task") != "workspace_draft":
        raise HTTPException(status_code=404, detail="AI call is not a workspace_draft")
    return row


# ─────────────────────────────────────────────────────────────────────────────
# 1. draft
# ─────────────────────────────────────────────────────────────────────────────

def draft(
    user: Any,
    milestone_id: int,
    instruction: str,
    source_text: str = "",
) -> Dict[str, Any]:
    """Create a pending workspace draft via the AI gateway.

    Rules:
    - User membership_state must be exactly 'member' (403 otherwise,
      including reaccept_required).
    - Milestone must be 'open' (409 otherwise).
    - instruction required, max 500 chars (400).
    - source_text optional, max 8000 chars (400).
    - Does NOT create a contribution; does NOT execute any tool.
    - After gateway.call the ai_calls.prompt_summary.status is patched to
      'pending' so approve/reject gates can act on it.
    - TOOL: lines are stripped from the returned draft text.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    milestone = query_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,))
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    project = query_one("SELECT * FROM projects WHERE id = ?", (milestone["project_id"],))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Membership gate
    state = membership_state(project["id"], user["id"])
    if state != "member":
        raise HTTPException(
            status_code=403,
            detail="You must be an active member of the current charter to use the workspace agent",
        )

    # Milestone must be open
    if milestone["status"] != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Milestone is not open for drafts (status: {milestone['status']})",
        )

    # Input validation
    instruction = (instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction is required")
    if len(instruction) > 500:
        raise HTTPException(status_code=400, detail="instruction must be at most 500 characters")

    source_text = source_text or ""
    if len(source_text) > 8000:
        raise HTTPException(status_code=400, detail="source_text must be at most 8000 characters")

    project_id = project["id"]

    # Get or create workspace agent for this user × project
    agent = get_or_create_agent("workspace", project_id, user["id"])
    agent_id = agent["id"]

    # Build meta for audit trail
    title = "Draft: " + instruction[:60]
    meta = {
        "milestone_id": milestone_id,
        "title": title,
    }

    # Call gateway — draft text may contain hostile TOOL: lines (canned injects
    # them when injection flags are present).  We pass response_override=None
    # so the gateway uses its normal routing pipeline.
    result = gateway.call(
        agent_id=agent_id,
        task="workspace_draft",
        instruction=instruction,
        data=source_text,
        project_id=project_id,
        meta=meta,
    )

    call_id = result.call_id
    raw_draft = result.text

    # Strip TOOL: lines from the draft before returning / storing
    clean_draft = "\n".join(
        line for line in raw_draft.splitlines()
        if not line.strip().startswith("TOOL:")
    )

    # Update response_summary to the cleaned draft and patch status → pending
    execute(
        "UPDATE ai_calls SET response_summary = ? WHERE id = ?",
        (clean_draft, call_id),
    )
    _patch_ai_call_status(call_id, "pending")

    return {
        "ai_call_id": call_id,
        "draft": clean_draft,
        "flags": result.flags,
        "blocked_tools": [t[0] for t in result.blocked_tools],
        "route": result.route,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. list_actions
# ─────────────────────────────────────────────────────────────────────────────

def list_actions(user: Any, project_id: int) -> List[Dict[str, Any]]:
    """List workspace actions for a project.

    Visible to: the owning sponsor, current-charter members, admin.
    The draft text is included ONLY when the viewer is the action's owner.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    uid = user["id"]
    role = user["role"]
    is_admin = role == "admin"
    is_sponsor = (project["sponsor_id"] == uid)
    state = membership_state(project_id, uid)
    is_member = (state == "member")

    if not (is_admin or is_sponsor or is_member):
        raise HTTPException(status_code=403, detail="Access denied to workspace actions")

    rows = query_all(
        """
        SELECT ac.id, ac.created_at, ac.human_owner_id, ac.approved_by,
               ac.response_summary, ac.prompt_summary,
               a.name AS agent_name, u.name AS owner_name
        FROM ai_calls ac
        LEFT JOIN agents a ON a.id = ac.agent_id
        LEFT JOIN users u ON u.id = ac.human_owner_id
        WHERE ac.project_id = ?
          AND json_extract(ac.prompt_summary, '$.task') = 'workspace_draft'
        ORDER BY ac.id ASC
        """,
        (project_id,),
    )

    result = []
    for r in rows:
        r = dict(r)
        try:
            ps = json.loads(r.get("prompt_summary") or "{}")
        except Exception:
            ps = {}

        status = ps.get("status", "pending")
        flags = ps.get("injection_flags", [])
        blocked = ps.get("blocked_tools", [])
        meta = ps.get("meta", {})
        milestone_id_val = meta.get("milestone_id")

        # Find linked contribution_id when approved
        linked_contribution_id = None
        if status == "approved" and r["approved_by"]:
            contrib_row = query_one(
                "SELECT id FROM contributions WHERE milestone_id = ? AND author_id = ? ORDER BY id DESC LIMIT 1",
                (milestone_id_val, r["human_owner_id"]),
            )
            if contrib_row:
                linked_contribution_id = contrib_row["id"]

        item: Dict[str, Any] = {
            "id": r["id"],
            "created_at": r["created_at"],
            "agent_name": r["agent_name"] or "Workspace Agent",
            "owner_name": r["owner_name"] or "Unknown",
            "status": status,
            "flags": flags,
            "blocked_tools": blocked,
            "milestone_id": milestone_id_val,
            "linked_contribution_id": linked_contribution_id,
        }

        # Draft text only for the owner
        if uid == r["human_owner_id"]:
            item["draft"] = r.get("response_summary", "")

        result.append(item)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 3. approve_action
# ─────────────────────────────────────────────────────────────────────────────

def approve_action(
    user: Any,
    ai_call_id: int,
    confirm_flagged: bool = False,
) -> Dict[str, Any]:
    """Human owner approves a pending workspace draft → creates a contribution.

    Rules:
    - Row must be a workspace_draft (404 otherwise).
    - Status must be 'pending' (409 otherwise).
    - Only the human owner may approve (403 for everyone else).
    - If injection_flags are non-empty and confirm_flagged is False → 400.
    - On success: submit_contribution(owner, ..., ai_declaration='agent_generated',
      agent_id=<workspace agent id>); set approved_by; patch status 'approved';
      write ledger agent_action_approved.
    - If submit_contribution raises (e.g. 409 unfunded), re-raise and leave pending.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    row = _require_workspace_draft(ai_call_id)

    try:
        ps = json.loads(row.get("prompt_summary") or "{}")
    except Exception:
        ps = {}

    status = ps.get("status", "done")
    injection_flags = ps.get("injection_flags", [])
    meta = ps.get("meta", {})
    milestone_id = meta.get("milestone_id")
    title = meta.get("title", "Agent draft")

    # Owner-only gate
    owner_id = row["human_owner_id"]
    if user["id"] != owner_id:
        raise HTTPException(status_code=403, detail="Only the draft owner may approve it")

    # Pending gate
    if status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve: action is already '{status}'",
        )

    # Injection confirmation gate
    if injection_flags and not confirm_flagged:
        raise HTTPException(
            status_code=400,
            detail="document contained suspicious instructions; confirm_flagged required",
        )

    if not milestone_id:
        raise HTTPException(status_code=500, detail="Action has no milestone_id in meta")

    # Fetch owner user row
    owner_user = _get_user(owner_id)

    # Clean draft text (strip any TOOL: lines that slipped through)
    draft_text = row.get("response_summary") or ""
    draft_text = "\n".join(
        line for line in draft_text.splitlines()
        if not line.strip().startswith("TOOL:")
    )

    # Identify the workspace agent (agent linked to this ai_calls row)
    agent_id_val = row["agent_id"]

    # Submit contribution — raises HTTPException on error; we re-raise, leaving pending
    contrib_result = contributions_svc.submit_contribution(
        owner_user,
        milestone_id,
        title,
        draft_text,
        "agent_generated",
        agent_id=agent_id_val,
    )
    contribution_id = contrib_result["contribution_id"]

    # Mark approved_by and patch status
    execute(
        "UPDATE ai_calls SET approved_by = ? WHERE id = ?",
        (owner_id, ai_call_id),
    )
    _patch_ai_call_status(ai_call_id, "approved")

    # Ledger: agent_action_approved (actor = human owner)
    project_id = row["project_id"]
    ledger.append(
        action="agent_action_approved",
        actor_id=owner_id,
        actor_type="human",
        human_owner_id=owner_id,
        project_id=project_id,
        payload={
            "ai_call_id": ai_call_id,
            "contribution_id": contribution_id,
        },
    )

    return {
        "status": "approved",
        "ai_call_id": ai_call_id,
        "contribution_id": contribution_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. reject_action
# ─────────────────────────────────────────────────────────────────────────────

def reject_action(user: Any, ai_call_id: int) -> Dict[str, Any]:
    """Owner rejects a pending workspace draft — no contribution is created.

    Rules:
    - Row must be a workspace_draft (404 otherwise).
    - Status must be 'pending' (409 otherwise).
    - Only the human owner may reject (403 for everyone else).
    - Writes ledger agent_action_rejected.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    row = _require_workspace_draft(ai_call_id)

    try:
        ps = json.loads(row.get("prompt_summary") or "{}")
    except Exception:
        ps = {}

    status = ps.get("status", "done")
    owner_id = row["human_owner_id"]

    # Owner-only gate
    if user["id"] != owner_id:
        raise HTTPException(status_code=403, detail="Only the draft owner may reject it")

    # Pending gate
    if status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot reject: action is already '{status}'",
        )

    _patch_ai_call_status(ai_call_id, "rejected")

    project_id = row["project_id"]
    ledger.append(
        action="agent_action_rejected",
        actor_id=owner_id,
        actor_type="human",
        human_owner_id=owner_id,
        project_id=project_id,
        payload={"ai_call_id": ai_call_id},
    )

    return {"status": "rejected", "ai_call_id": ai_call_id}
