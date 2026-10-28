from datetime import datetime, timezone
import hashlib
import json
import sqlite3
from typing import Any, Dict, Optional

import re
import unicodedata

from fastapi import HTTPException
from app.access import membership_state
from app.db import execute, query_one


def validate_non_funded_rewards(rewards: str) -> None:
    """Validate that non-funded charter rewards do not contain currency symbols or payment terms."""
    if not rewards:
        return
    for ch in rewards:
        if unicodedata.category(ch) == "Sc" or ch in ("₹", "$", "€", "£", "¥"):
            raise HTTPException(
                status_code=400,
                detail=f"Non-funded project rewards cannot contain currency symbols ('{ch}')",
            )
    cleaned = re.sub(r"\bno\s+payment\b", "", rewards, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bunpaid\b", "", cleaned, flags=re.IGNORECASE)
    m = re.search(r"\b(pay|paid|payment|salary|stipend|fee)\b", cleaned, flags=re.IGNORECASE)
    if m:
        raise HTTPException(
            status_code=400,
            detail=f"Non-funded project rewards cannot contain payment terms ('{m.group(0)}')",
        )


def canonical_charter_hash(version: int, terms: Dict[str, Any]) -> str:
    """Compute SHA-256 hash of canonical JSON for a charter version and terms dict."""
    payload = {"terms": terms, "version": version}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_project(sponsor: Any, fields: Dict[str, Any]) -> int:
    """Validate sponsor role and fields, insert project and charter v1, and return project id."""
    if not sponsor or sponsor["role"] != "sponsor":
        raise HTTPException(status_code=403, detail="Only sponsors can create projects")

    required = ["title", "public_summary", "confidential_brief", "sensitivity_label", "engagement_model"]
    for r in required:
        if not fields.get(r):
            raise HTTPException(status_code=400, detail=f"Missing required field: {r}")

    title = fields["title"]
    public_summary = fields["public_summary"]
    confidential_brief = fields["confidential_brief"]
    sensitivity_label = fields["sensitivity_label"]
    engagement_model = fields["engagement_model"]

    if sensitivity_label not in ("public", "internal", "confidential"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sensitivity_label '{sensitivity_label}', must be public|internal|confidential",
        )

    if engagement_model not in ("funded", "stipend", "knowledge_sharing", "institutional_credit"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid engagement_model '{engagement_model}'",
        )

    # Prepare terms with all 9 required keys
    terms = fields.get("terms")
    if not terms and "terms_json" in fields:
        terms = json.loads(fields["terms_json"])
    if not terms:
        terms = {
            "engagement_model": engagement_model,
            "rewards": fields.get(
                "rewards",
                "Escrow-backed milestone distribution per Section 8 split rules"
                if engagement_model == "funded"
                else "UNPAID: recognition only",
            ),
            "scope": fields.get("scope", public_summary),
            "people": fields.get("people", "1 sponsor, domain experts, verified students"),
            "ip_publication": fields.get("ip_publication", "Open research publication with named attribution"),
            "confidentiality": fields.get("confidentiality", "Confidential brief and datasets protected"),
            "credit_split": fields.get("credit_split", "Calculated by split engine rules"),
            "exit_disputes": fields.get("exit_disputes", "Disputes audited via immutable ledger"),
            "commercialisation": fields.get("commercialisation", "Future commercialisation requires updated charter"),
        }

    # Non-funded rewards validation (SPEC.md §21)
    if engagement_model not in ("funded", "stipend"):
        validate_non_funded_rewards(terms.get("rewards", ""))

    now_iso = datetime.now(timezone.utc).isoformat()

    project_id = execute(
        """
        INSERT INTO projects (
            sponsor_id, title, public_summary, confidential_brief,
            sensitivity_label, engagement_model, status, current_charter_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sponsor["id"],
            title,
            public_summary,
            confidential_brief,
            sensitivity_label,
            engagement_model,
            "open",
            1,
            now_iso,
        ),
    )
    # Compute brief hash for ledger payload (never store the brief text in a payload - RULES.md l)
    brief_hash = hashlib.sha256(confidential_brief.encode("utf-8")).hexdigest()
    charter_hash = canonical_charter_hash(1, terms)

    import app.ledger as ledger
    ledger.append(
        action="project_posted",
        actor_id=sponsor["id"],
        actor_type="human",
        human_owner_id=sponsor["id"],
        project_id=project_id,
        charter_version=1,
        payload={
            "title": title,
            "engagement_model": engagement_model,
            "sensitivity_label": sensitivity_label,
            "brief_hash": brief_hash,
            "charter_hash": charter_hash,
        },
    )

    execute(
        """
        INSERT INTO charters (project_id, version, terms_json, hash, published_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (project_id, 1, json.dumps(terms), charter_hash, now_iso),
    )
    ledger.append(
        action="charter_published",
        actor_id=sponsor["id"],
        actor_type="human",
        human_owner_id=sponsor["id"],
        project_id=project_id,
        charter_version=1,
        payload={
            "version": 1,
            "charter_hash": charter_hash,
            "engagement_model": engagement_model,
            "change_note": "initial charter",
        },
    )

    return project_id


def publish_charter(user: Any, project_id: int, changes: Dict[str, Any]) -> int:
    """Publish a new charter version (n+1) for a project. Owning sponsor only."""
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not user or user["role"] != "sponsor" or user["id"] != project["sponsor_id"]:
        raise HTTPException(status_code=403, detail="Only the owning sponsor can publish a charter")

    current_charter = query_one(
        "SELECT * FROM charters WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    )
    prev_terms = json.loads(current_charter["terms_json"]) if current_charter else {}
    new_terms = dict(prev_terms)
    new_terms.update(changes)

    current_model = project["engagement_model"]
    new_model = changes.get("engagement_model", current_model)

    # Engagement model transition rules (SPEC.md §21)
    if new_model != current_model:
        # non-funded -> funded gives 400 (start a new project)
        if current_model not in ("funded", "stipend") and new_model in ("funded", "stipend"):
            raise HTTPException(
                status_code=400,
                detail="non-funded to funded engagement model change is not permitted (start a new project)",
            )

        # funded -> non-funded
        if current_model in ("funded", "stipend") and new_model not in ("funded", "stipend"):
            change_note = str(changes.get("change_note", "")).strip()
            if not change_note:
                raise HTTPException(
                    status_code=400,
                    detail="funded to non-funded transition requires a non-empty change_note",
                )

            # Check if any escrow in funded, submitted, accepted, released
            held_escrow = query_one(
                """
                SELECT COUNT(*) AS c
                FROM escrows e
                JOIN milestones m ON m.id = e.milestone_id
                WHERE m.project_id = ? AND e.state IN ('funded', 'submitted', 'accepted', 'released')
                """,
                (project_id,),
            )
            if held_escrow and held_escrow["c"] > 0:
                raise HTTPException(
                    status_code=409,
                    detail="funds are held: resolve escrow first",
                )

            # Draft escrow rows are deleted and milestone amounts set to 0
            execute(
                """
                DELETE FROM escrows WHERE id IN (
                    SELECT e.id FROM escrows e
                    JOIN milestones m ON m.id = e.milestone_id
                    WHERE m.project_id = ? AND e.state = 'draft'
                )
                """,
                (project_id,),
            )
            execute("UPDATE milestones SET amount_inr = 0 WHERE project_id = ?", (project_id,))

            # Replace rewards and credit_split
            if "rewards" in changes and str(changes["rewards"]).strip():
                new_terms["rewards"] = str(changes["rewards"]).strip()
            else:
                new_terms["rewards"] = "UNPAID: recognition only"
            new_terms["credit_split"] = "Credit is shared by reviewed impact. No payment is offered or implied."

    # Validate non-funded rewards
    target_model = new_model
    if target_model not in ("funded", "stipend"):
        rewards_to_check = str(new_terms.get("rewards", "")).strip()
        validate_non_funded_rewards(rewards_to_check)

    new_terms["engagement_model"] = target_model

    new_version = (current_charter["version"] + 1) if current_charter else (project["current_charter_version"] + 1)
    charter_hash = canonical_charter_hash(new_version, new_terms)
    now_iso = datetime.now(timezone.utc).isoformat()

    execute(
        """
        INSERT INTO charters (project_id, version, terms_json, hash, published_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (project_id, new_version, json.dumps(new_terms), charter_hash, now_iso),
    )

    execute(
        """
        UPDATE projects
        SET current_charter_version = ?, engagement_model = ?
        WHERE id = ?
        """,
        (new_version, target_model, project_id),
    )

    import app.ledger as ledger
    ledger.append(
        action="charter_published",
        actor_id=user["id"],
        actor_type="human",
        human_owner_id=user["id"],
        project_id=project_id,
        charter_version=new_version,
        payload={
            "version": new_version,
            "charter_hash": charter_hash,
            "engagement_model": target_model,
            "change_note": changes.get("change_note", ""),
        },
    )

    return new_version


def join_project(user: Any, project_id: int, accept_charter: bool, ack_engagement_model: bool) -> Dict[str, Any]:
    """Join project by accepting charter and engagement model.

    Enforces rules in SPEC.md section 16 in exact order:
    1. role is student or expert (403)
    2. verification_level >= 1 (403)
    3. expert conflict of interest (403, "conflict of interest")
    4. minors need guardian_consent=1 for funded and stipend projects (403, "guardian consent required")
    5. both acknowledgements true (400)
    """
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not user:
        raise HTTPException(status_code=403, detail="Authentication required to join project")

    # 1. role is student or expert (403)
    if user["role"] not in ("student", "expert"):
        raise HTTPException(status_code=403, detail="Only students and experts can join projects")

    # 2. verification_level >= 1 (403)
    if user["verification_level"] < 1:
        raise HTTPException(status_code=403, detail="Verification level 1 or higher required to join")

    # 3. expert conflict of interest (403, "conflict of interest")
    if user["role"] == "expert":
        sponsor = query_one("SELECT * FROM users WHERE id = ?", (project["sponsor_id"],))
        sponsor_institution = sponsor["institution"] if sponsor else None
        conflict_orgs = []
        if user["conflict_orgs"]:
            try:
                conflict_orgs = json.loads(user["conflict_orgs"])
            except Exception:
                conflict_orgs = []
        if sponsor_institution and sponsor_institution in conflict_orgs:
            raise HTTPException(
                status_code=403,
                detail=f"Cannot join: conflict of interest with sponsor institution '{sponsor_institution}'",
            )

    # 4. minors need guardian_consent=1 for funded and stipend projects (403, "guardian consent required")
    if user["is_minor"] == 1 and project["engagement_model"] in ("funded", "stipend"):
        if user["guardian_consent"] != 1:
            raise HTTPException(
                status_code=403,
                detail="guardian consent required: minors cannot join funded or stipend projects without guardian consent",
            )

    # 5. both acknowledgements true (400)
    if not accept_charter or not ack_engagement_model:
        raise HTTPException(
            status_code=400,
            detail="Both charter acceptance and engagement model acknowledgement are required",
        )

    # Idempotent: if already a member of current version, return success without inserting
    current_state = membership_state(project_id, user["id"])
    if current_state == "member":
        return {
            "status": "ok",
            "message": "Already a member of current charter version",
            "membership_state": "member",
        }

    now_iso = datetime.now(timezone.utc).isoformat()
    execute(
        """
        INSERT INTO charter_acceptances (
            project_id, user_id, charter_version, engagement_model_ack, accepted_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (project_id, user["id"], project["current_charter_version"], 1, now_iso),
    )
    # LEDGER HOOK (S2): ledger.append(action='charter_accepted')

    return {
        "status": "ok",
        "message": "Charter accepted successfully",
        "membership_state": "member",
    }


def leave_project(user: Any, project_id: int) -> Dict[str, Any]:
    """Leave project. Allowed only from states 'member' or 'reaccept_required' (409 otherwise).

    Inserts a charter_acceptances row with engagement_model_ack=0 at the current version.
    Records ledger member_left or charter_declined.
    Credit is kept; access is revoked automatically through can_view.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    prev_state = membership_state(project_id, user["id"])
    if prev_state not in ("member", "reaccept_required"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot leave project from membership state '{prev_state}'",
        )

    # Approved contributions count and impact weight on this project
    row = query_one(
        """
        SELECT COUNT(*) AS c, COALESCE(SUM(c.impact_weight), 0.0) AS s
        FROM contributions c
        JOIN milestones m ON m.id = c.milestone_id
        WHERE m.project_id = ? AND c.author_id = ? AND c.review_status = 'approved'
        """,
        (project_id, user["id"]),
    )
    approved_count = row["c"] if row else 0
    total_impact = round(float(row["s"]), 2) if row else 0.0

    now_iso = datetime.now(timezone.utc).isoformat()
    execute(
        """
        INSERT INTO charter_acceptances (
            project_id, user_id, charter_version, engagement_model_ack, accepted_at
        ) VALUES (?, ?, ?, 0, ?)
        """,
        (project_id, user["id"], project["current_charter_version"], now_iso),
    )

    action = "member_left" if prev_state == "member" else "charter_declined"
    import app.ledger as ledger
    ledger.append(
        action=action,
        actor_id=user["id"],
        actor_type="human",
        human_owner_id=user["id"],
        project_id=project_id,
        charter_version=project["current_charter_version"],
        payload={
            "user_id": user["id"],
            "previous_state": prev_state,
            "approved_contributions": approved_count,
            "total_impact": total_impact,
        },
    )

    return {
        "status": "ok",
        "membership_state": "declined",
        "action": action,
    }
