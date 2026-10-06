"""
app/credits.py — Centralised credit computation for Provenance.

Credits are earned by on-chain verified actions. They cannot be self-assigned.
Any attempt to fake credits would require tampering with the ledger hash chain.

Credit weights (per SPEC intent):
  contribution_submitted  → 20 cr  (you did work)
  contribution_reviewed   → 30 cr  (you verified someone else's work)
  milestone_accepted      → 50 cr  (project milestone completed)
  agent_action_approved   → 15 cr  (human oversight of AI)
  charter_accepted        →  5 cr  (committed to project governance)
"""

from app.db import query_all

WEIGHTS: dict[str, int] = {
    "contribution_submitted": 20,
    "contribution_reviewed": 30,
    "milestone_accepted": 50,
    "agent_action_approved": 15,
    "charter_accepted": 5,
}


def total(user_id: int) -> int:
    """Return the total credits earned by a user."""
    rows = query_all(
        "SELECT action FROM ledger_entries WHERE actor_id=? AND actor_type='human'",
        (user_id,),
    )
    return sum(WEIGHTS.get(r["action"], 0) for r in rows)


def history(user_id: int) -> list[dict]:
    """Return a list of credit-earning events for a user, newest first."""
    rows = query_all(
        """
        SELECT le.action, le.timestamp, le.project_id, p.title AS project_title
        FROM ledger_entries le
        LEFT JOIN projects p ON p.id = le.project_id
        WHERE le.actor_id = ? AND le.actor_type = 'human'
        ORDER BY le.id DESC
        """,
        (user_id,),
    )
    result = []
    for r in rows:
        pts = WEIGHTS.get(r["action"], 0)
        if pts > 0:
            result.append(
                {
                    "action": r["action"],
                    "pts": pts,
                    "timestamp": r["timestamp"],
                    "project_title": r["project_title"] or "—",
                }
            )
    return result


def breakdown(user_id: int) -> dict[str, int]:
    """Return per-action credit totals for a user."""
    rows = query_all(
        "SELECT action FROM ledger_entries WHERE actor_id=? AND actor_type='human'",
        (user_id,),
    )
    out: dict[str, int] = {k: 0 for k in WEIGHTS}
    for r in rows:
        action = r["action"]
        if action in out:
            out[action] += WEIGHTS[action]
    return {k: v for k, v in out.items() if v > 0}
