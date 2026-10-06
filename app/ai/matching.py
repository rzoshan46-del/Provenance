"""app/ai/matching.py — Candidate matching and team recommendation service.
"""
import json
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.ai.agents import get_or_create_agent
import app.ai.gateway as gateway
from app.db import query_all, query_one


def recommend(user: Any, project_id: int) -> Dict[str, Any]:
    """Rank and recommend 1 expert and 3 students for a project.
    
    Rules (SPEC §19):
    - Only the owning sponsor can run matching (403).
    - Required skills = union (lower-cased) of skills from project's proposed and open milestones.
      If none exist: 409.
    - Exclusions:
      - verification_level < 1 -> "verification level too low"
      - expert conflict of interest (sponsor institution in conflict_orgs) -> "conflict of interest"
      - minor without guardian consent on funded project -> "guardian consent required"
    - Score = matched / required (+0.05 newcomer boost for students with no credentials).
    - Ties broken by higher verification_level, then lower user id.
    - One gateway call records the matching action and audit log.
    """
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not user or user["id"] != project["sponsor_id"]:
        raise HTTPException(status_code=403, detail="Only the owning sponsor can run candidate matching")

    # Aggregate required skills from proposed and open milestones
    ms_rows = query_all(
        "SELECT required_skills FROM milestones WHERE project_id = ? AND status IN ('proposed', 'open')",
        (project_id,),
    )
    all_skills = set()
    for row in ms_rows:
        try:
            sk_list = json.loads(row["required_skills"] or "[]")
            for s in sk_list:
                s_clean = str(s).strip().lower()
                if s_clean:
                    all_skills.add(s_clean)
        except Exception:
            pass

    if not all_skills:
        raise HTTPException(status_code=409, detail="No required skills found on project milestones")

    required_skills = sorted(list(all_skills))

    # Sponsor details for conflict check
    sponsor = query_one("SELECT * FROM users WHERE id = ?", (project["sponsor_id"],))
    sponsor_institution = sponsor["institution"] if sponsor else ""

    is_funded = project["engagement_model"] in ("funded", "stipend")

    candidate_users = query_all(
        "SELECT * FROM users WHERE role IN ('expert', 'student') ORDER BY id ASC"
    )

    excluded: List[Dict[str, Any]] = []
    eligible_experts: List[Dict[str, Any]] = []
    eligible_students: List[Dict[str, Any]] = []

    for row in candidate_users:
        u = dict(row)
        u_role = u["role"]
        u_name = u["name"]
        u_id = u["id"]
        v_level = int(u.get("verification_level", 0))

        # Check conflict orgs
        try:
            conflict_orgs = [str(x).strip().lower() for x in json.loads(u.get("conflict_orgs") or "[]")]
        except Exception:
            conflict_orgs = []

        # 1. Verification level check
        if v_level < 1:
            excluded.append({
                "user_id": u_id,
                "name": u_name,
                "role": u_role,
                "reason": "verification level too low",
            })
            continue

        # 2. Conflict of interest for experts
        if u_role == "expert" and sponsor_institution:
            if sponsor_institution.strip().lower() in conflict_orgs:
                excluded.append({
                    "user_id": u_id,
                    "name": u_name,
                    "role": u_role,
                    "reason": "conflict of interest",
                })
                continue

        # 3. Guardian consent for minors on funded projects
        if is_funded and int(u.get("is_minor", 0)) == 1 and int(u.get("guardian_consent", 0)) != 1:
            excluded.append({
                "user_id": u_id,
                "name": u_name,
                "role": u_role,
                "reason": "guardian consent required",
            })
            continue

        # Compute skill overlap
        try:
            user_skills = [str(s).strip().lower() for s in json.loads(u.get("skills") or "[]")]
        except Exception:
            user_skills = []

        matched = [s for s in required_skills if s in user_skills]
        missing = [s for s in required_skills if s not in user_skills]

        base_score = len(matched) / len(required_skills)
        final_score = base_score
        is_newcomer = False

        if u_role == "student":
            cred_count = query_one(
                "SELECT COUNT(*) as c FROM credentials WHERE user_id = ?", (u_id,)
            )["c"]
            if cred_count == 0:
                is_newcomer = True
                final_score += 0.05

        matched_str = ", ".join(matched) if matched else "none"
        missing_str = ", ".join(missing) if missing else "none"
        explanation = (
            f"Matched skills: {matched_str}; Missing: {missing_str}; "
            f"Verification level: {v_level}"
        )
        if is_newcomer:
            explanation += " (newcomer boost applied)"

        candidate_obj = {
            "user_id": u_id,
            "name": u_name,
            "role": u_role,
            "institution": u["institution"],
            "verification_level": v_level,
            "score": round(final_score, 4),
            "matched_skills": matched,
            "missing_skills": missing,
            "explanation": explanation,
            "is_newcomer": is_newcomer,
        }

        if u_role == "expert":
            eligible_experts.append(candidate_obj)
        else:
            eligible_students.append(candidate_obj)

    # Sort candidates: (-score, -verification_level, user_id)
    eligible_experts.sort(key=lambda c: (-c["score"], -c["verification_level"], c["user_id"]))
    eligible_students.sort(key=lambda c: (-c["score"], -c["verification_level"], c["user_id"]))

    top_expert = eligible_experts[0] if eligible_experts else None
    top_students = eligible_students[:3]

    structured_result = {
        "project_id": project_id,
        "required_skills": required_skills,
        "expert": top_expert,
        "students": top_students,
        "excluded": excluded,
    }

    # Gateway call recording
    agent = get_or_create_agent("matching", project_id, user["id"])
    serialized_summary = json.dumps(structured_result)

    gateway.call(
        agent_id=agent["id"],
        task="matching",
        instruction="Rank eligible expert and student researchers by skills, reputation and policy criteria.",
        project_id=project_id,
        extra_payload={
            "expert_id": top_expert["user_id"] if top_expert else None,
            "student_ids": [s["user_id"] for s in top_students],
            "excluded_count": len(excluded),
        },
        response_override=serialized_summary,
    )

    return structured_result


def latest(user: Any, project_id: int) -> Dict[str, Any]:
    """Retrieve the latest matching recommendation for a project.
    
    Accessible to owning sponsor and admin only (403 otherwise).
    """
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    is_sponsor = user and user["id"] == project["sponsor_id"]
    is_admin = user and user["role"] == "admin"
    if not (is_sponsor or is_admin):
        raise HTTPException(status_code=403, detail="Access denied to matching recommendations")

    row = query_one(
        """
        SELECT * FROM ai_calls
        WHERE project_id = ? AND prompt_summary LIKE '%"task": "matching"%'
        ORDER BY id DESC LIMIT 1
        """,
        (project_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="No matching recommendations found for this project")

    try:
        return json.loads(row["response_summary"])
    except Exception:
        raise HTTPException(status_code=500, detail="Invalid matching summary data")
