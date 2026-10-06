"""app/ai/scoping.py — AI-assisted project milestone scoping service.
"""
from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.ai.agents import get_or_create_agent
from app.ai.canned import SCOPING_MILESTONES
import app.ai.gateway as gateway
from app.db import execute, query_all, query_one
import app.ledger as ledger


def _clean_json_text(text: str) -> str:
    """Strip markdown formatting or code blocks from LLM JSON response."""
    cleaned = text.strip()
    # Match ```json ... ``` or ``` ... ```
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return cleaned


def propose_milestones(user: Any, project_id: int, budget_inr: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Propose milestone decomposition using the project's scoping agent.
    
    Rules (SPEC §19):
    - Only the owning sponsor can run scoping (403).
    - If milestones already exist on this project: 409.
    - Funded project: budget_inr must be a positive integer (400 if missing or <= 0).
    - Non-funded project: all milestone amounts are 0.
    - Status is 'proposed' (NO escrow created yet).
    - Output must be a list of at least 2 milestones; invalid output falls back to canned fixture.
    - Ledger milestone_proposed entries written with actor_type 'agent' and human_owner = sponsor.
    """
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not user or user["id"] != project["sponsor_id"]:
        raise HTTPException(status_code=403, detail="Only the owning sponsor can scope milestones")

    # Conflict check: project cannot be scoped twice
    existing_count = query_one("SELECT COUNT(*) as c FROM milestones WHERE project_id = ?", (project_id,))["c"]
    if existing_count > 0:
        raise HTTPException(status_code=409, detail="Project already has milestones")

    is_funded = project["engagement_model"] in ("funded", "stipend")

    # Validate budget
    parsed_budget = 0
    if is_funded:
        if budget_inr is None:
            raise HTTPException(status_code=400, detail="Funded project requires a positive budget_inr")
        try:
            if isinstance(budget_inr, str):
                if "." in budget_inr:
                    raise ValueError()
                parsed_budget = int(budget_inr.strip())
            elif isinstance(budget_inr, int) and not isinstance(budget_inr, bool):
                parsed_budget = budget_inr
            else:
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="budget_inr must be a valid positive integer")

        if parsed_budget <= 0:
            raise HTTPException(status_code=400, detail="budget_inr must be greater than 0")
    else:
        parsed_budget = 0

    # Ensure scoping agent exists for sponsor
    agent = get_or_create_agent("scoping", project_id, user["id"])

    instruction = (
        "Analyze the project confidential brief and propose at least 2 milestones for the research team. "
        "Return ONLY a JSON array of objects, each containing: 'title', 'deliverables', "
        "'acceptance_criteria', and 'required_skills' (a list of skill keywords)."
    )
    brief_data = project["confidential_brief"] if project["confidential_brief"] else ""

    gw_res = gateway.call(
        agent_id=agent["id"],
        task="scoping",
        instruction=instruction,
        data=brief_data,
        project_id=project_id,
        meta={"budget_inr": parsed_budget},
    )

    # Robust parsing of model output
    milestones_parsed: List[Dict[str, Any]] = []
    try:
        raw_text = _clean_json_text(gw_res.text)
        data = json.loads(raw_text)
        if isinstance(data, list) and len(data) >= 2:
            for item in data:
                if (
                    isinstance(item, dict)
                    and item.get("title")
                    and item.get("deliverables")
                    and item.get("acceptance_criteria")
                    and isinstance(item.get("required_skills"), list)
                ):
                    milestones_parsed.append(item)
    except Exception:
        milestones_parsed = []

    if len(milestones_parsed) < 2:
        milestones_parsed = list(SCOPING_MILESTONES)

    n = len(milestones_parsed)
    if is_funded:
        base_amt = parsed_budget // n
        remainder = parsed_budget % n
        amounts = [base_amt] * (n - 1) + [base_amt + remainder]
    else:
        amounts = [0] * n

    created_milestones: List[Dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    for i, m in enumerate(milestones_parsed):
        amt = amounts[i]
        title = str(m["title"]).strip()
        deliverables = str(m["deliverables"]).strip()
        criteria = str(m["acceptance_criteria"]).strip()
        skills = [str(s).strip() for s in m.get("required_skills", []) if str(s).strip()]
        skills_json = json.dumps(skills)

        m_id = execute(
            """
            INSERT INTO milestones (
                project_id, title, deliverables, acceptance_criteria,
                required_skills, amount_inr, status, acceptance_window_days, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'proposed', 7, ?)
            """,
            (project_id, title, deliverables, criteria, skills_json, amt, now_iso),
        )

        # Ledger milestone_proposed (actor_type = agent, human_owner = sponsor)
        ledger.append(
            action="milestone_proposed",
            actor_id=agent["id"],
            actor_type="agent",
            human_owner_id=user["id"],
            project_id=project_id,
            payload={
                "milestone_id": m_id,
                "title": title,
                "amount_inr": amt,
                "required_skills": skills,
            },
        )

        created_milestones.append({
            "id": m_id,
            "project_id": project_id,
            "title": title,
            "deliverables": deliverables,
            "acceptance_criteria": criteria,
            "required_skills": skills,
            "amount_inr": amt,
            "status": "proposed",
            "acceptance_window_days": 7,
            "created_at": now_iso,
        })

    return created_milestones
