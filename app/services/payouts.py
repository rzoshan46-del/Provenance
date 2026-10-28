"""
app/services/payouts.py — Payouts, Verifiable Receipts, Credentials & Credit Statements.

MOCKED: production would use one atomic transaction and a payment gateway (SPEC.md §18).
"""
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.access import can_view
from app.db import execute, query_all, query_one
import app.ledger as ledger
from app.ledger import canonical
from app.services.escrow import escrow_transition
import app.splits as splits


def release_milestone(
    user: Any,
    milestone: sqlite3.Row,
    project: sqlite3.Row,
    escrow: sqlite3.Row,
    auto: bool = False,
) -> Dict[str, Any]:
    """Execute split engine, write verifiable payouts, transition escrow, and log ledger entries.

    MOCKED: production would use one atomic transaction and a payment gateway.

    Payout and credential participants = everyone with an approved contribution on the milestone,
    whether or not they are still members (credit is kept even after leaving — SPEC §21).
    """
    milestone_id = milestone["id"]
    amount_inr = milestone["amount_inr"]

    # 1. Gather approved contributions for students and experts
    #    Include ex-members: do NOT filter by current membership state
    approved_contribs = query_all(
        """
        SELECT c.*, u.role
        FROM contributions c
        JOIN users u ON u.id = c.author_id
        WHERE c.milestone_id = ? AND c.review_status = 'approved'
        """,
        (milestone_id,),
    )

    if not approved_contribs:
        raise HTTPException(
            status_code=409,
            detail="Cannot accept milestone without any approved contributions",
        )

    student_weights: Dict[int, float] = {}
    has_agent_work: Dict[int, bool] = {}
    expert_ids_set = set()

    for c in approved_contribs:
        author_id = c["author_id"]
        role = c["role"]
        if role == "student":
            student_weights[author_id] = (
                student_weights.get(author_id, 0.0) + c["impact_weight"]
            )
            if c["ai_declaration"] == "agent_generated":
                has_agent_work[author_id] = True
        elif role == "expert":
            expert_ids_set.add(author_id)

    # Also include expert reviewers who approved contributions on this milestone
    expert_reviewers = query_all(
        """
        SELECT DISTINCT r.reviewer_id
        FROM reviews r
        JOIN contributions c ON c.id = r.contribution_id
        JOIN users u ON u.id = r.reviewer_id
        WHERE c.milestone_id = ? AND r.decision = 'approve' AND u.role = 'expert'
        """,
        (milestone_id,),
    )
    for er in expert_reviewers:
        expert_ids_set.add(er["reviewer_id"])

    # If still empty, check active expert members of the project
    if not expert_ids_set:
        from app.access import membership_state
        proj_experts = query_all("SELECT id FROM users WHERE role = 'expert'")
        for pe in proj_experts:
            if membership_state(project["id"], pe["id"]) == "member":
                expert_ids_set.add(pe["id"])

    if not student_weights:
        raise HTTPException(
            status_code=409,
            detail="Cannot execute split without at least one approved student contribution",
        )

    expert_ids = sorted(list(expert_ids_set))

    # 2. Compute split
    split_res = splits.compute_split(amount_inr, student_weights, expert_ids)

    fee_inr = split_res["fee_inr"]
    ai_reserve_inr = split_res["ai_reserve_inr"]
    net_inr = split_res["net_inr"]
    cfg = split_res["config"]

    payout_hashes = []

    # 3. Write Expert Payout rows
    for eid, amt in split_res["experts"].items():
        user_row = query_one("SELECT name FROM users WHERE id = ?", (eid,))
        user_name = user_row["name"] if user_row else ""
        sentence = f"Expert pool share for milestone '{milestone['title']}'."
        rationale = {
            "amount_inr": amt,
            "config": cfg,
            "fee": fee_inr,
            "ai_reserve": ai_reserve_inr,
            "net": net_inr,
            "role": "expert",
            "sentence": sentence,
        }
        rationale_json = canonical(rationale)
        receipt_data = {
            "amount_inr": amt,
            "escrow_id": escrow["id"],
            "rationale": rationale,
            "user_id": eid,
        }
        receipt_hash = hashlib.sha256(canonical(receipt_data).encode("utf-8")).hexdigest()
        now_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

        execute(
            """
            INSERT INTO payouts (escrow_id, user_id, amount_inr, role, rationale_json, receipt_hash, created_at)
            VALUES (?, ?, ?, 'expert', ?, ?, ?)
            """,
            (escrow["id"], eid, amt, rationale_json, receipt_hash, now_iso),
        )
        payout_hashes.append(receipt_hash)

    # 4. Write Student Payout rows
    for sid, s_info in split_res["students"].items():
        amt = s_info["amount_inr"]
        user_row = query_one("SELECT name FROM users WHERE id = ?", (sid,))
        is_agent = has_agent_work.get(sid, False)

        sentence = f"Student contribution share for milestone '{milestone['title']}'."
        if is_agent:
            sentence += (
                " includes AI-generated work credited to the human who directed and reviewed it"
            )

        rationale = {
            "amount_inr": amt,
            "config": cfg,
            "fee": fee_inr,
            "ai_reserve": ai_reserve_inr,
            "net": net_inr,
            "role": "student",
            "weight": s_info["weight"],
            "weight_share": s_info["weight_share"],
            "equal_part": s_info["equal_part"],
            "weighted_part": s_info["weighted_part"],
            "rounding_adjustment": s_info["rounding_adjustment"],
            "sentence": sentence,
        }
        if is_agent:
            rationale["ai_credit_note"] = (
                "includes AI-generated work credited to the human who directed and reviewed it"
            )

        rationale_json = canonical(rationale)
        receipt_data = {
            "amount_inr": amt,
            "escrow_id": escrow["id"],
            "rationale": rationale,
            "user_id": sid,
        }
        receipt_hash = hashlib.sha256(canonical(receipt_data).encode("utf-8")).hexdigest()
        now_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

        execute(
            """
            INSERT INTO payouts (escrow_id, user_id, amount_inr, role, rationale_json, receipt_hash, created_at)
            VALUES (?, ?, ?, 'student', ?, ?, ?)
            """,
            (escrow["id"], sid, amt, rationale_json, receipt_hash, now_iso),
        )
        payout_hashes.append(receipt_hash)

    # 5. Milestone Receipt Hash
    payout_hashes_sorted = sorted(payout_hashes)
    milestone_receipt_data = {
        "ai_reserve_inr": ai_reserve_inr,
        "amount_inr": amount_inr,
        "fee_inr": fee_inr,
        "milestone_id": milestone_id,
        "payout_hashes": payout_hashes_sorted,
    }
    milestone_receipt_hash = hashlib.sha256(
        canonical(milestone_receipt_data).encode("utf-8")
    ).hexdigest()

    # 6. Escrow Transitions: submitted -> accepted -> released
    #    actor=None if system auto-accept
    escrow_actor = None if auto else user
    escrow_transition(escrow["id"], "accepted", escrow_actor)
    escrow_transition(escrow["id"], "released", escrow_actor)

    # 7. Ledger: payout_released and milestone_accepted
    if auto:
        actor_id = None
        actor_type = "system"
        human_owner_id = None
    else:
        actor_id = user["id"] if user and isinstance(user, (dict, sqlite3.Row)) else None
        actor_type = "human"
        human_owner_id = actor_id

    ledger.append(
        action="payout_released",
        actor_id=actor_id,
        actor_type=actor_type,
        human_owner_id=human_owner_id,
        project_id=project["id"],
        payload={
            "amount_inr": amount_inr,
            "fee_inr": fee_inr,
            "ai_reserve_inr": ai_reserve_inr,
            "milestone_id": milestone_id,
            "milestone_receipt_hash": milestone_receipt_hash,
            "payout_count": len(payout_hashes),
        },
    )

    milestone_accepted_payload: Dict[str, Any] = {"milestone_id": milestone_id}
    if auto:
        milestone_accepted_payload["auto"] = True
        milestone_accepted_payload["reason"] = "acceptance window elapsed"

    ledger.append(
        action="milestone_accepted",
        actor_id=actor_id,
        actor_type=actor_type,
        human_owner_id=human_owner_id,
        project_id=project["id"],
        payload=milestone_accepted_payload,
    )

    return {
        "status": "accepted",
        "milestone_id": milestone_id,
        "milestone_receipt_hash": milestone_receipt_hash,
        "payout_count": len(payout_hashes),
    }


def issue_credentials(
    user: Any,
    milestone: sqlite3.Row,
    project: sqlite3.Row,
) -> List[Dict[str, Any]]:
    """Issue certificate credentials to all contributors with approved contributions."""
    milestone_id = milestone["id"]
    project_id = project["id"]
    charter_version = project["current_charter_version"]

    author_rows = query_all(
        """
        SELECT DISTINCT author_id
        FROM contributions
        WHERE milestone_id = ? AND review_status = 'approved'
        ORDER BY author_id ASC
        """,
        (milestone_id,),
    )
    reviewer_rows = query_all(
        """
        SELECT DISTINCT r.reviewer_id
        FROM reviews r
        JOIN contributions c ON c.id = r.contribution_id
        JOIN users u ON u.id = r.reviewer_id
        WHERE c.milestone_id = ? AND r.decision = 'approve' AND u.role = 'expert'
        ORDER BY r.reviewer_id ASC
        """,
        (milestone_id,),
    )
    all_uids = sorted(list(set([r["author_id"] for r in author_rows] + [r["reviewer_id"] for r in reviewer_rows])))

    issued = []
    # Support actor=None (system auto-accept path)
    if user is None:
        actor_id = None
        actor_type = "system"
        human_owner_id = None
    elif isinstance(user, (dict, sqlite3.Row)):
        actor_id = user["id"]
        actor_type = "human"
        human_owner_id = actor_id
    else:
        actor_id = None
        actor_type = "system"
        human_owner_id = None

    for uid in all_uids:
        issued_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        cred_fields = {
            "charter_version": charter_version,
            "issued_at": issued_at,
            "kind": "certificate",
            "milestone_id": milestone_id,
            "project_id": project_id,
            "user_id": uid,
        }
        credential_hash = hashlib.sha256(canonical(cred_fields).encode("utf-8")).hexdigest()

        cred_id = execute(
            """
            INSERT INTO credentials (project_id, user_id, kind, issued_at, credential_hash)
            VALUES (?, ?, 'certificate', ?, ?)
            """,
            (project_id, uid, issued_at, credential_hash),
        )

        ledger.append(
            action="credential_issued",
            actor_id=actor_id,
            actor_type=actor_type,
            human_owner_id=human_owner_id,
            project_id=project_id,
            payload={
                "credential_id": cred_id,
                "credential_hash": credential_hash,
                "kind": "certificate",
                "user_id": uid,
            },
        )

        issued.append({
            "credential_id": cred_id,
            "user_id": uid,
            "credential_hash": credential_hash,
            "kind": "certificate",
        })

    return issued


def build_receipt(milestone_id: int) -> Dict[str, Any]:
    """Build the verifiable receipt structure for a funded milestone."""
    milestone = query_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,))
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    project = query_one("SELECT * FROM projects WHERE id = ?", (milestone["project_id"],))
    escrow = query_one("SELECT * FROM escrows WHERE milestone_id = ?", (milestone_id,))
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow record not found")

    payout_rows = query_all(
        """
        SELECT p.*, u.name as user_name
        FROM payouts p
        JOIN users u ON u.id = p.user_id
        WHERE p.escrow_id = ?
        ORDER BY p.id ASC
        """,
        (escrow["id"],),
    )

    amount_inr = milestone["amount_inr"]
    fee_inr = 0
    ai_reserve_inr = 0
    net_inr = 0
    expert_pool_inr = 0
    student_pool_inr = 0

    lines = []
    payout_hashes = []
    all_lines_verified = True

    for row in payout_rows:
        try:
            rationale = json.loads(row["rationale_json"])
        except Exception:
            rationale = {}

        if not fee_inr and "fee" in rationale:
            fee_inr = rationale["fee"]
            ai_reserve_inr = rationale.get("ai_reserve", 0)
            net_inr = rationale.get("net", 0)

        if row["role"] == "expert":
            expert_pool_inr += row["amount_inr"]
        else:
            student_pool_inr += row["amount_inr"]

        receipt_data = {
            "amount_inr": row["amount_inr"],
            "escrow_id": row["escrow_id"],
            "rationale": rationale,
            "user_id": row["user_id"],
        }
        recomputed_hash = hashlib.sha256(canonical(receipt_data).encode("utf-8")).hexdigest()
        is_verified = recomputed_hash == row["receipt_hash"]
        if not is_verified:
            all_lines_verified = False

        lines.append({
            "user_id": row["user_id"],
            "name": row["user_name"],
            "role": row["role"],
            "amount_inr": row["amount_inr"],
            "sentence": rationale.get("sentence", ""),
            "receipt_hash": row["receipt_hash"],
            "verified": is_verified,
        })
        payout_hashes.append(row["receipt_hash"])

    payouts_sum = sum(l["amount_inr"] for l in lines)
    total_check = (payouts_sum + fee_inr + ai_reserve_inr == amount_inr) if lines else False

    payout_hashes_sorted = sorted(payout_hashes)
    milestone_receipt_data = {
        "ai_reserve_inr": ai_reserve_inr,
        "amount_inr": amount_inr,
        "fee_inr": fee_inr,
        "milestone_id": milestone_id,
        "payout_hashes": payout_hashes_sorted,
    }
    milestone_receipt_hash = hashlib.sha256(
        canonical(milestone_receipt_data).encode("utf-8")
    ).hexdigest()

    receipt_verified = all_lines_verified and total_check and bool(lines)

    from app.integrity.provenance import ai_breakdown

    return {
        "milestone_id": milestone_id,
        "project_id": milestone["project_id"],
        "amount_inr": amount_inr,
        "fee_inr": fee_inr,
        "ai_reserve_inr": ai_reserve_inr,
        "net_inr": net_inr,
        "expert_pool_inr": expert_pool_inr,
        "student_pool_inr": student_pool_inr,
        "lines": lines,
        "total_check": total_check,
        "receipt_hash": milestone_receipt_hash,
        "receipt_verified": receipt_verified,
        "ai_breakdown": ai_breakdown(milestone_id),
    }


def verify_receipt(milestone_id: int) -> Dict[str, Any]:
    """Verify the integrity of all payout receipts for a milestone."""
    receipt = build_receipt(milestone_id)
    if not receipt["lines"]:
        return {
            "ok": False,
            "reason": "No payouts recorded for milestone",
            "total_check": False,
            "lines_checked": 0,
        }

    if not receipt["total_check"]:
        return {
            "ok": False,
            "reason": "Payout amounts plus fee and reserve do not equal milestone amount",
            "total_check": False,
            "lines_checked": len(receipt["lines"]),
        }

    if not receipt["receipt_verified"]:
        return {
            "ok": False,
            "reason": "One or more individual payout receipt hashes failed verification",
            "total_check": True,
            "lines_checked": len(receipt["lines"]),
        }

    return {
        "ok": True,
        "reason": None,
        "total_check": True,
        "lines_checked": len(receipt["lines"]),
    }


def credit_statement(milestone_id: int) -> Dict[str, Any]:
    """Generate a non-monetary credit statement based on approved contributions.

    Strict rule: contains NO currency symbols and NO payment wording (SPEC §16, §18).
    """
    milestone = query_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,))
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    project = query_one("SELECT * FROM projects WHERE id = ?", (milestone["project_id"],))

    approved_contribs = query_all(
        """
        SELECT c.*, u.name as author_name, u.role as author_role
        FROM contributions c
        JOIN users u ON u.id = c.author_id
        WHERE c.milestone_id = ? AND c.review_status = 'approved'
        ORDER BY c.id ASC
        """,
        (milestone_id,),
    )

    user_impacts: Dict[int, float] = {}
    user_info: Dict[int, Dict[str, Any]] = {}

    for c in approved_contribs:
        uid = c["author_id"]
        user_impacts[uid] = user_impacts.get(uid, 0.0) + c["impact_weight"]
        if uid not in user_info:
            user_info[uid] = {
                "user_id": uid,
                "name": c["author_name"],
                "role": c["author_role"],
            }

    total_impact = sum(user_impacts.values())
    contributors = []

    if user_impacts:
        # Largest remainder rounding to tenths of a percent (sum == 100.0)
        # Convert to units of 0.1% (1000 units total)
        target_units = 1000
        shares_tenths: Dict[int, float] = {}
        for uid, imp in user_impacts.items():
            shares_tenths[uid] = (imp / total_impact) * target_units if total_impact > 0 else (target_units / len(user_impacts))

        floor_tenths = {uid: int(shares_tenths[uid]) for uid in user_impacts}
        remainders = {uid: shares_tenths[uid] - floor_tenths[uid] for uid in user_impacts}

        allocated = sum(floor_tenths.values())
        rem_distribute = target_units - allocated

        sorted_uids = sorted(user_impacts.keys(), key=lambda u: (-remainders[u], u))
        bonus_uids = set(sorted_uids[:rem_distribute])

        for uid in user_impacts:
            final_tenths = floor_tenths[uid] + (1 if uid in bonus_uids else 0)
            percentage_share = round(final_tenths / 10.0, 1)

            # Fetch issued credentials for this user and milestone
            creds = query_all(
                """
                SELECT id, kind, issued_at, credential_hash
                FROM credentials
                WHERE project_id = ? AND user_id = ?
                ORDER BY id ASC
                """,
                (project["id"], uid),
            )

            contributors.append({
                "user_id": uid,
                "name": user_info[uid]["name"],
                "role": user_info[uid]["role"],
                "impact_score": round(user_impacts[uid], 1),
                "percentage_share": percentage_share,
                "credentials": [dict(cr) for cr in creds],
            })

    from app.integrity.provenance import ai_breakdown

    return {
        "milestone_id": milestone_id,
        "project_id": project["id"],
        "engagement_model": project["engagement_model"],
        "status": "unpaid",
        "contributors": contributors,
        "ai_breakdown": ai_breakdown(milestone_id),
    }
