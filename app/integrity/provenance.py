"""app/integrity/provenance.py — Provenance labeling and AI breakdown computation.
"""
import sqlite3
from typing import Any, Dict, Optional

from app.db import query_all, query_one


def label(contribution_row: Any) -> Dict[str, Any]:
    """Compute provenance metadata object for a contribution.
    
    Returns:
        {
            "kind": str ("human" | "ai_assisted" | "agent_generated"),
            "label": str ("Human" | "AI-assisted" | "Agent-generated"),
            "agent": Optional[str],
            "owner": Optional[str],
        }
    """
    if isinstance(contribution_row, sqlite3.Row):
        row = dict(contribution_row)
    elif isinstance(contribution_row, dict):
        row = contribution_row
    else:
        row = {}

    decl = row.get("ai_declaration") or "human"
    agent_id = row.get("agent_id")

    if decl == "human":
        return {
            "kind": "human",
            "label": "Human",
            "agent": None,
            "owner": None,
        }
    elif decl == "ai_assisted":
        return {
            "kind": "ai_assisted",
            "label": "AI-assisted",
            "agent": None,
            "owner": None,
        }
    elif decl == "agent_generated":
        agent_name = None
        owner_name = None
        if agent_id:
            agent_row = query_one(
                """
                SELECT a.name AS agent_name, u.name AS owner_name
                FROM agents a
                LEFT JOIN users u ON u.id = a.human_owner_id
                WHERE a.id = ?
                """,
                (agent_id,),
            )
            if agent_row:
                agent_name = agent_row["agent_name"]
                owner_name = agent_row["owner_name"]

        return {
            "kind": "agent_generated",
            "label": "Agent-generated",
            "agent": agent_name,
            "owner": owner_name,
        }

    return {
        "kind": decl,
        "label": decl.replace("_", " ").title(),
        "agent": None,
        "owner": None,
    }


def ai_breakdown(milestone_id: int) -> Dict[str, float]:
    """Calculate percentages of reviewed impact by declaration on a milestone.
    
    Percentages each rounded to 1 decimal, with rounding remainder on largest share
    so they sum to 100.0. Computed live and NOT part of any hash (SPEC §20).
    """
    rows = query_all(
        """
        SELECT ai_declaration, impact_weight
        FROM contributions
        WHERE milestone_id = ? AND review_status = 'approved'
        """,
        (milestone_id,),
    )

    totals = {"human": 0.0, "ai_assisted": 0.0, "agent_generated": 0.0}
    for r in rows:
        decl = r["ai_declaration"]
        if decl in totals:
            totals[decl] += float(r["impact_weight"] or 0.0)

    total_impact = sum(totals.values())
    if total_impact == 0:
        return {"human": 0.0, "ai_assisted": 0.0, "agent_generated": 0.0}

    shares = {k: round((totals[k] / total_impact) * 100.0, 1) for k in totals}
    diff = round(100.0 - sum(shares.values()), 1)
    if diff != 0:
        largest_key = max(totals.keys(), key=lambda k: totals[k])
        shares[largest_key] = round(shares[largest_key] + diff, 1)

    return shares
