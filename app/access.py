from typing import Any, Optional
from app.db import query_one


def membership_state(project_id: int, user_id: Optional[int]) -> str:
    """Return membership state for a (project, user) pair.

    Returns: 'member' | 'reaccept_required' | 'declined' | 'none'
    Uses the LATEST charter_acceptances row (highest id) for that pair.
    """
    if user_id is None:
        return "none"

    project = query_one(
        "SELECT current_charter_version FROM projects WHERE id = ?",
        (project_id,),
    )
    if not project:
        return "none"

    row = query_one(
        """
        SELECT charter_version, engagement_model_ack
        FROM charter_acceptances
        WHERE project_id = ? AND user_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (project_id, user_id),
    )
    if not row:
        return "none"

    if row["engagement_model_ack"] == 1:
        if row["charter_version"] == project["current_charter_version"]:
            return "member"
        return "reaccept_required"

    return "declined"


def can_view(user_or_none: Optional[Any], project: Any, resource: str) -> bool:
    """Single source of truth for who can see what across all routes and views.

    Resources:
    - 'public_summary': everyone, including anonymous
    - 'charter': everyone (visible before applying)
    - 'brief': owning sponsor or active member of current charter version.
               Admin must NOT see 'brief' (least privilege).
    - 'roster', 'milestones': owning sponsor, active member, or admin (for audit).
    """
    if resource in ("public_summary", "charter"):
        return True

    if user_or_none is None:
        return False

    project_id = project["id"]
    sponsor_id = project["sponsor_id"]
    user_id = user_or_none["id"]
    user_role = user_or_none["role"]

    if resource == "brief":
        # Admin must NOT see 'brief' per SPEC.md section 16 least-privilege rule
        if user_role == "admin":
            return False
        if user_id == sponsor_id:
            return True
        return membership_state(project_id, user_id) == "member"

    if resource in ("roster", "milestones"):
        if user_role == "admin":
            return True
        if user_id == sponsor_id:
            return True
        return membership_state(project_id, user_id) == "member"

    return False
