"""app/ai/agents.py — Agent lifecycle and allowed tool registry for Provenance.
"""
from typing import Any, Dict, List, Optional
import json

from app.db import execute, query_one


ALLOWED_TOOLS_BY_KIND: Dict[str, List[str]] = {
    "scoping": ["propose_milestones"],
    "matching": ["rank_candidates"],
    "workspace": ["draft_text", "summarize"],
    "integrity": [],
}


def get_agent(agent_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve an agent by id."""
    row = query_one("SELECT * FROM agents WHERE id = ?", (agent_id,))
    if not row:
        return None
    d = dict(row)
    try:
        d["allowed_tools"] = json.loads(d["allowed_tools"])
    except Exception:
        d["allowed_tools"] = []
    return d


def get_or_create_agent(
    kind: str,
    project_id: Optional[int],
    human_owner_id: Optional[int],
) -> Dict[str, Any]:
    """Get or create an agent row in the database.
    
    Rules (SPEC §19):
    - Agents are rows in agents, unique per (kind, project_id, human_owner_id).
    - Must have a valid human owner (raises ValueError if missing or does not exist).
    - Allowed tools are strictly scoped by kind.
    """
    if human_owner_id is None:
        raise ValueError("Agent must have a human_owner_id")

    # Validate human owner exists
    owner = query_one("SELECT id FROM users WHERE id = ?", (human_owner_id,))
    if not owner:
        raise ValueError(f"Human owner with id {human_owner_id} does not exist")

    if kind not in ALLOWED_TOOLS_BY_KIND:
        raise ValueError(f"Invalid agent kind '{kind}'. Must be one of: {list(ALLOWED_TOOLS_BY_KIND.keys())}")

    # Check for existing agent
    if project_id is not None:
        existing = query_one(
            "SELECT * FROM agents WHERE kind = ? AND project_id = ? AND human_owner_id = ?",
            (kind, project_id, human_owner_id),
        )
    else:
        existing = query_one(
            "SELECT * FROM agents WHERE kind = ? AND project_id IS NULL AND human_owner_id = ?",
            (kind, human_owner_id),
        )

    if existing:
        d = dict(existing)
        try:
            d["allowed_tools"] = json.loads(d["allowed_tools"])
        except Exception:
            d["allowed_tools"] = []
        return d

    # Create new agent
    tools = ALLOWED_TOOLS_BY_KIND[kind]
    tools_json = json.dumps(tools)
    
    if project_id is not None:
        name = f"{kind.capitalize()} Agent (P{project_id})"
    else:
        name = f"{kind.capitalize()} Agent"

    agent_id = execute(
        """
        INSERT INTO agents (name, kind, human_owner_id, project_id, allowed_tools)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, kind, human_owner_id, project_id, tools_json),
    )

    created = query_one("SELECT * FROM agents WHERE id = ?", (agent_id,))
    d = dict(created)
    d["allowed_tools"] = tools
    return d
