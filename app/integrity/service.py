"""app/integrity/service.py — Integrity verification service for Provenance.

SPEC.md §20:
- check_contribution(contribution_id)
- integrity_report(user, contribution_id)
- preview_check(user, text, ai_declaration="human", milestone_id=None)
- authorship_lookup(user, text)
"""
import hashlib
import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.access import can_view
from app.db import execute, query_all, query_one
from app.integrity import watermark
from app.integrity.signals import ai_markers
from app.integrity.similarity import FLAG_THRESHOLD, compare, shingles, tokenize
import app.ledger as ledger


def check_contribution(contribution_id: int) -> Dict[str, Any]:
    """Run similarity & AI marker checks on a newly submitted contribution.
    
    Compares against other authors' contributions across all projects.
    Flags contribution if score >= 0.6 or undisclosed AI is detected.
    """
    contrib = query_one(
        """
        SELECT c.*, m.project_id
        FROM contributions c
        JOIN milestones m ON m.id = c.milestone_id
        WHERE c.id = ?
        """,
        (contribution_id,),
    )
    if not contrib:
        return {"status": "not_found"}

    author_id = contrib["author_id"]
    project_id = contrib["project_id"]
    new_text = contrib["artefact_text"] or ""
    ai_decl = contrib["ai_declaration"] or "human"

    # Query up to 2000 other contributions by DIFFERENT authors (own earlier work never counts)
    other_rows = query_all(
        """
        SELECT c.id, c.author_id, c.artefact_title, c.artefact_text, c.artefact_hash, m.project_id
        FROM contributions c
        JOIN milestones m ON m.id = c.milestone_id
        WHERE c.author_id != ? AND c.id != ?
        ORDER BY c.id ASC
        LIMIT 2000
        """,
        (author_id, contribution_id),
    )

    max_score = 0.0
    matched_row: Optional[sqlite3.Row] = None

    for other in other_rows:
        # A user's own earlier work never counts (SPEC §20):
        # If the author already submitted this work earlier than `other`, `other` is a copy of author's work
        has_prior = query_one(
            "SELECT 1 FROM contributions WHERE author_id = ? AND artefact_hash = ? AND id < ?",
            (author_id, other["artefact_hash"], other["id"]),
        )
        if has_prior:
            continue

        other_text = other["artefact_text"] or ""
        cmp_res = compare(new_text, other_text)
        if cmp_res["score"] > max_score:
            max_score = cmp_res["score"]
            matched_row = other

    # Check for AI markers
    markers = ai_markers(new_text)

    reasons: List[str] = []
    if max_score >= FLAG_THRESHOLD:
        reasons.append("similarity")

    # Undisclosed AI check: only when ai_declaration is 'human'
    if ai_decl == "human" and len(markers) > 0:
        reasons.append("possible_undisclosed_ai")

    # Update similarity_score on contribution
    execute(
        "UPDATE contributions SET similarity_score = ? WHERE id = ?",
        (round(max_score, 4), contribution_id),
    )

    is_flagged = len(reasons) > 0
    matched_id = None
    is_cross_project = False

    if is_flagged:
        execute(
            "UPDATE contributions SET review_status = 'flagged' WHERE id = ?",
            (contribution_id,),
        )

        if matched_row and max_score >= FLAG_THRESHOLD:
            is_cross_project = matched_row["project_id"] != project_id
            if not is_cross_project:
                matched_id = matched_row["id"]
            else:
                matched_id = None

        ledger_payload: Dict[str, Any] = {
            "contribution_id": contribution_id,
            "cross_project": is_cross_project,
            "matched_contribution_id": matched_id,
            "reasons": reasons,
            "score": round(max_score, 2),
        }

        # Do not hold a write transaction open while calling ledger.append (SPEC §20)
        ledger.append(
            action="contribution_flagged",
            actor_id=None,
            actor_type="system",
            human_owner_id=None,
            project_id=project_id,
            payload=ledger_payload,
        )

    return {
        "status": "flagged" if is_flagged else "pending",
        "similarity_score": round(max_score, 4),
        "reasons": reasons,
        "matched_contribution_id": matched_id,
        "cross_project": is_cross_project,
    }


def _extract_shared_phrases(text_a: str, text_b: str, limit: int = 3) -> List[str]:
    """Extract up to `limit` shared 3-word phrases in text_a.

    Exact duplicates can legitimately share a phrase even when the shingle search is
    skipped by punctuation or a degenerate token arrangement, so we keep a stable
    fallback to the first contiguous shared 3-word phrase in the original text.
    """
    toks_a = tokenize(text_a)
    toks_b = tokenize(text_b)
    if len(toks_a) < 3 or len(toks_b) < 3:
        return []

    sh_b = shingles(toks_b, 3)
    phrases: List[str] = []
    seen: set = set()
    for i in range(len(toks_a) - 2):
        tup = tuple(toks_a[i : i + 3])
        if tup in sh_b and tup not in seen:
            seen.add(tup)
            phrases.append(" ".join(tup))
            if len(phrases) >= limit:
                break

    if not phrases:
        lead_tup = tuple(toks_a[:3])
        lead_match = " ".join(lead_tup)
        if lead_tup in sh_b:
            return [lead_match]

        # Fallback: if the first n tokens are present contiguously in the other text,
        # surface it even when shingling missed a degenerate edge case.
        b_joined = " ".join(toks_b)
        if lead_match in b_joined:
            return [lead_match]

    return phrases[:limit]


def integrity_report(user: Any, contribution_id: int) -> Dict[str, Any]:
    """Generate detailed integrity report for a contribution.
    
    Visible to sponsor, members, and admin (can_view 'milestones') else 403.
    """
    contrib = query_one(
        """
        SELECT c.*, m.project_id
        FROM contributions c
        JOIN milestones m ON m.id = c.milestone_id
        WHERE c.id = ?
        """,
        (contribution_id,),
    )
    if not contrib:
        raise HTTPException(status_code=404, detail="Contribution not found")

    project = query_one("SELECT * FROM projects WHERE id = ?", (contrib["project_id"],))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not can_view(user, project, "milestones"):
        raise HTTPException(status_code=403, detail="Access denied to integrity report")

    author_id = contrib["author_id"]
    new_text = contrib["artefact_text"] or ""
    ai_decl = contrib["ai_declaration"] or "human"
    sim_score = float(contrib["similarity_score"] or 0.0)

    # Re-evaluate match against other authors
    other_rows = query_all(
        """
        SELECT c.id, c.author_id, c.artefact_title, c.artefact_text, m.project_id, u.name AS author_name
        FROM contributions c
        JOIN milestones m ON m.id = c.milestone_id
        JOIN users u ON u.id = c.author_id
        WHERE c.author_id != ? AND c.id != ?
        ORDER BY c.id ASC
        LIMIT 2000
        """,
        (author_id, contribution_id),
    )

    best_score = 0.0
    matched_row: Optional[sqlite3.Row] = None
    for other in other_rows:
        cmp_res = compare(new_text, other["artefact_text"] or "")
        if cmp_res["score"] > best_score:
            best_score = cmp_res["score"]
            matched_row = other

    score_to_report = max(sim_score, best_score)
    reasons: List[str] = []
    if score_to_report >= FLAG_THRESHOLD:
        reasons.append("similarity")

    markers = ai_markers(new_text)
    if ai_decl == "human" and len(markers) > 0:
        reasons.append("possible_undisclosed_ai")

    report: Dict[str, Any] = {
        "contribution_id": contribution_id,
        "review_status": contrib["review_status"],
        "score": round(score_to_report, 2),
        "reasons": reasons,
    }

    if matched_row and score_to_report >= FLAG_THRESHOLD:
        is_cross = matched_row["project_id"] != contrib["project_id"]
        report["cross_project"] = is_cross
        if is_cross:
            report["notice"] = "matches content in another project (details hidden)"
            report["matched_contribution_id"] = None
        else:
            report["matched_contribution_id"] = matched_row["id"]
            report["matched_title"] = matched_row["artefact_title"]
            report["matched_author_name"] = matched_row["author_name"]
            report["shared_phrases"] = _extract_shared_phrases(
                new_text, matched_row["artefact_text"] or "", limit=3
            )
    else:
        report["cross_project"] = False
        report["matched_contribution_id"] = None

    return report


def preview_check(
    user: Any,
    text: str,
    ai_declaration: str = "human",
    milestone_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Preview similarity check without creating a contribution row."""
    uid = user["id"] if user else 0
    query = """
        SELECT c.id, c.author_id, c.artefact_title, c.artefact_text, m.project_id, u.name as author_name
        FROM contributions c
        JOIN milestones m ON m.id = c.milestone_id
        JOIN users u ON u.id = c.author_id
        WHERE c.author_id != ?
        ORDER BY c.id ASC
        LIMIT 2000
    """
    other_rows = query_all(query, (uid,))

    max_score = 0.0
    matched_row: Optional[sqlite3.Row] = None
    for other in other_rows:
        cmp_res = compare(text, other["artefact_text"] or "")
        if cmp_res["score"] > max_score:
            max_score = cmp_res["score"]
            matched_row = other

    markers = ai_markers(text)
    reasons: List[str] = []
    if max_score >= FLAG_THRESHOLD:
        reasons.append("similarity")
    if ai_declaration == "human" and len(markers) > 0:
        reasons.append("possible_undisclosed_ai")

    res: Dict[str, Any] = {
        "score": round(max_score, 2),
        "reasons": reasons,
        "ai_markers": markers,
    }

    # Match details only when milestone_id is given and visible to caller
    if milestone_id is not None:
        milestone = query_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,))
        if milestone:
            project = query_one("SELECT * FROM projects WHERE id = ?", (milestone["project_id"],))
            if project and can_view(user, project, "milestones") and matched_row:
                if matched_row["project_id"] == project["id"]:
                    res["matched_contribution_id"] = matched_row["id"]
                    res["matched_title"] = matched_row["artefact_title"]
                    res["matched_author_name"] = matched_row["author_name"]
                else:
                    res["notice"] = "matches content in another project (details hidden)"

    return res


def authorship_lookup(user: Any, text: str) -> Dict[str, Any]:
    """Lookup the earliest original contribution matching text exactly.
    
    Matches in projects the user cannot see are never revealed (SPEC §20).
    """
    if not text:
        return {"found": False}

    h = hashlib.sha256(text.encode("utf-8")).hexdigest()

    candidates = query_all(
        """
        SELECT c.*, u.name AS author_name, m.project_id
        FROM contributions c
        JOIN milestones m ON m.id = c.milestone_id
        JOIN users u ON u.id = c.author_id
        WHERE c.artefact_hash = ?
        ORDER BY c.id ASC
        """,
        (h,),
    )

    for cand in candidates:
        project = query_one("SELECT * FROM projects WHERE id = ?", (cand["project_id"],))
        if project and can_view(user, project, "milestones"):
            # Lookup contribution_submitted ledger entry id
            entry = query_one(
                """
                SELECT id FROM ledger_entries
                WHERE action = 'contribution_submitted'
                  AND project_id = ?
                  AND payload_json LIKE ?
                ORDER BY id ASC LIMIT 1
                """,
                (project["id"], f'%"contribution_id":{cand["id"]}%'),
            )
            return {
                "found": True,
                "author_name": cand["author_name"],
                "submitted_at": cand["created_at"],
                "ledger_entry_id": entry["id"] if entry else None,
                "contribution_id": cand["id"],
                "artefact_hash": cand["artefact_hash"],
                "sha256": cand["artefact_hash"],
            }

    return {"found": False}


def protect(
    viewer: Any,
    owner_id: int,
    text: str,
    resource: str,
    resource_id: Any,
    project_id: int,
) -> str:
    """Protect confidential text by invisible per-viewer watermarking and access logging.

    If viewer is the owner, returns clean text.
    Otherwise applies watermark(viewer.id) and records content_viewed in the ledger at most once.
    Stored text and artefact_hash are never modified.
    """
    if not text:
        return text

    viewer_id = None
    if viewer is not None:
        try:
            viewer_id = viewer["id"]
        except Exception:
            viewer_id = getattr(viewer, "id", None)
    if viewer_id is None:
        return text

    if viewer_id == owner_id:
        return text

    # Check if this viewer already has a content_viewed entry for this resource
    rows = query_all(
        """
        SELECT payload_json FROM ledger_entries
        WHERE action = 'content_viewed' AND actor_id = ? AND project_id = ?
        """,
        (viewer_id, project_id),
    )
    already_logged = False
    for r in rows:
        try:
            p = json.loads(r["payload_json"])
            if p.get("resource") == resource and str(p.get("resource_id")) == str(resource_id):
                already_logged = True
                break
        except Exception:
            pass

    if not already_logged:
        ledger.append(
            action="content_viewed",
            actor_id=viewer_id,
            actor_type="human",
            human_owner_id=viewer_id,
            project_id=project_id,
            payload={
                "resource": resource,
                "resource_id": resource_id,
                "watermark_id": viewer_id,
            },
        )

    return watermark.apply(text, viewer_id)


def trace(user: Any, text: str) -> Dict[str, Any]:
    """Trace leaked text to its viewer via extracted watermark.

    Sponsor or admin only. Admin can trace any user; sponsor only viewers
    with logged views on the sponsor's projects.
    """
    user_role = None
    user_id = None
    if user is not None:
        try:
            user_id = user["id"]
            user_role = user["role"]
        except Exception:
            user_id = getattr(user, "id", None)
            user_role = getattr(user, "role", None)

    if not user or user_role not in ("sponsor", "admin"):
        raise HTTPException(status_code=403, detail="Forbidden: only sponsor or admin may trace leaks")

    res = watermark.extract(text)
    if not res.get("found") or not res.get("valid") or not res.get("user_id"):
        return {
            "found": False,
            "message": "no watermark found (text may have been retyped, stripped or paraphrased)",
        }

    traced_user_id = res["user_id"]
    traced_user = query_one("SELECT * FROM users WHERE id = ?", (traced_user_id,))
    if not traced_user:
        raise HTTPException(status_code=404, detail="no matching viewer on your projects")

    sponsor_projects: List[int] = []
    if user_role == "sponsor":
        sponsor_projects = [
            p["id"] for p in query_all("SELECT id FROM projects WHERE sponsor_id = ?", (user_id,))
        ]
        if not sponsor_projects:
            raise HTTPException(status_code=404, detail="no matching viewer on your projects")

        placeholders = ",".join("?" for _ in sponsor_projects)
        view_entry = query_one(
            f"""
            SELECT 1 FROM ledger_entries
            WHERE action = 'content_viewed' AND actor_id = ? AND project_id IN ({placeholders})
            LIMIT 1
            """,
            (traced_user_id, *sponsor_projects),
        )
        if not view_entry:
            raise HTTPException(status_code=404, detail="no matching viewer on your projects")

    # Collect logged views limited to projects the caller can see
    view_rows = query_all(
        """
        SELECT project_id, timestamp, payload_json
        FROM ledger_entries
        WHERE action = 'content_viewed' AND actor_id = ?
        ORDER BY id ASC
        """,
        (traced_user_id,),
    )
    logged_views = []
    for vr in view_rows:
        pid = vr["project_id"]
        can_see = True if user_role == "admin" else (pid in sponsor_projects)
        if can_see:
            try:
                p = json.loads(vr["payload_json"])
                logged_views.append({
                    "resource": p.get("resource"),
                    "resource_id": p.get("resource_id"),
                    "project_id": pid,
                    "timestamp": vr["timestamp"],
                })
            except Exception:
                pass

    ledger.append(
        action="leak_traced",
        actor_id=user_id,
        actor_type="human",
        human_owner_id=user_id,
        project_id=None,
        payload={
            "traced_user_id": traced_user_id,
            "confidence": res["confidence"],
        },
    )

    return {
        "found": True,
        "user_id": traced_user_id,
        "name": traced_user["name"],
        "role": traced_user["role"],
        "confidence": res["confidence"],
        "marks_found": res["marks_found"],
        "marks_valid": res["marks_valid"],
        "logged_views": logged_views,
    }
