"""
app/certificates.py — Public, verifiable certificates with QR codes.

What this module adds (it does NOT change any existing table or route):
  GET  /verify/{credential_hash}              public verification page (shareable link)
  GET  /certificate/{credential_hash}         print-ready certificate (Save as PDF)
  GET  /certificate/{credential_hash}/qr.svg  QR code image that points at /verify/...
  GET  /api/verify/{credential_hash}          the same facts as JSON
  POST /api/credentials/{credential_hash}/revoke   admin only, writes a ledger entry

How verification works:
  * A credential is a row in the existing `credentials` table. Its 64-character
    credential_hash is unguessable, so it doubles as the public certificate id.
  * issue_credentials() already writes a `credential_issued` ledger entry that
    contains that hash. We look that entry up, re-compute its hashes, and also run
    the full ledger.verify() chain check (cached for 2 seconds).
  * Revocations live in a small extra table, `credential_revocations`, created
    on first use, so init_db() and the 14 existing tables are untouched.

Privacy: no email addresses, no confidential brief. Minors are shown as
"First L." only.
"""

import hashlib
import io
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

import app.ledger as ledger
from app.config import get_base_url
from app.db import execute, query_all, query_one
from app.deps import current_user

HASH_RE = re.compile(r"^[0-9a-f]{64}$")

REVOKE_REASONS = {
    "plagiarism": "Plagiarism or copied work found",
    "error": "Issued in error",
    "policy": "Policy violation",
    "other": "Other",
}

DECLARATION_LABELS = {
    "human": "Human-written",
    "ai_assisted": "AI-assisted",
    "agent_generated": "Agent-generated",
}

_chain_cache: Dict[str, Any] = {"t": 0.0, "v": None}


# ─────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────
def _display_name(name: str, is_minor: Any) -> str:
    """Minors are shown as 'First L.' on public pages."""
    name = (name or "").strip()
    if not is_minor:
        return name
    parts = name.split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1][0]}."
    return parts[0] if parts else "Contributor"


def _short_id(credential_hash: str) -> str:
    h = credential_hash[:12].upper()
    return f"PRV-{h[0:4]}-{h[4:8]}-{h[8:12]}"


def _pretty_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d %b %Y")
    except Exception:
        return (iso or "")[:10]


def _public_base(request: Request) -> str:
    """Use APP_BASE_URL in production; fall back to the request host when it is still localhost."""
    base = get_base_url()
    if "127.0.0.1" in base or "localhost" in base:
        return str(request.base_url).rstrip("/")
    return base


def _chain_status() -> Dict[str, Any]:
    """ledger.verify() walks the whole chain, so cache it briefly for public pages."""
    now = time.monotonic()
    if _chain_cache["v"] is None or now - _chain_cache["t"] > 2.0:
        _chain_cache["v"] = ledger.verify()
        _chain_cache["t"] = now
    return _chain_cache["v"]


def _entry_ok(row: Any) -> bool:
    """Re-compute one ledger entry's payload hash and entry hash."""
    try:
        if (
            hashlib.sha256(row["payload_json"].encode("utf-8")).hexdigest()
            != row["payload_hash"]
        ):
            return False
        fields = {
            "action": row["action"],
            "actor_id": row["actor_id"],
            "actor_type": row["actor_type"],
            "charter_version": row["charter_version"],
            "human_owner_id": row["human_owner_id"],
            "payload_hash": row["payload_hash"],
            "project_id": row["project_id"],
            "timestamp": row["timestamp"],
        }
        return ledger.compute_entry_hash(row["prev_hash"], fields) == row["entry_hash"]
    except Exception:
        return False


def _ensure_revocations_table() -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS credential_revocations (
            credential_hash TEXT PRIMARY KEY,
            reason_code TEXT NOT NULL,
            note TEXT,
            revoked_by INTEGER,
            revoked_at TEXT NOT NULL
        )
        """
    )


def _revocation(credential_hash: str) -> Optional[Any]:
    sql = "SELECT * FROM credential_revocations WHERE credential_hash = ?"
    try:
        return query_one(sql, (credential_hash,))
    except Exception:
        _ensure_revocations_table()
        return query_one(sql, (credential_hash,))


# ─────────────────────────────────────────────
# Core: build everything the pages need
# ─────────────────────────────────────────────
def load_certificate(credential_hash: str, base_url: str) -> Optional[Dict[str, Any]]:
    """Return the full certificate facts, or None if the hash is malformed / unknown."""
    credential_hash = (credential_hash or "").strip().lower()
    if not HASH_RE.match(credential_hash):
        return None

    row = query_one(
        """
        SELECT c.id AS credential_id, c.project_id, c.user_id, c.kind, c.issued_at,
               c.credential_hash,
               p.title AS project_title, p.public_summary, p.engagement_model,
               u.name AS holder_name, u.is_minor AS holder_is_minor,
               u.institution AS holder_institution,
               s.name AS sponsor_name
        FROM credentials c
        JOIN projects p ON p.id = c.project_id
        JOIN users u ON u.id = c.user_id
        JOIN users s ON s.id = p.sponsor_id
        WHERE c.credential_hash = ?
        """,
        (credential_hash,),
    )
    if not row:
        return None
    r = dict(row)

    # --- what this person actually did on the project (approved work only) ---
    decl_rows = query_all(
        """
        SELECT c.ai_declaration AS decl, COUNT(*) AS n
        FROM contributions c
        JOIN milestones m ON m.id = c.milestone_id
        WHERE c.author_id = ? AND m.project_id = ? AND c.review_status = 'approved'
        GROUP BY c.ai_declaration
        """,
        (r["user_id"], r["project_id"]),
    )
    counts = {d["decl"]: d["n"] for d in (dict(x) for x in decl_rows)}
    total_contribs = sum(counts.values())
    declarations: List[Dict[str, Any]] = []
    for key in ("human", "ai_assisted", "agent_generated"):
        n = counts.get(key, 0)
        declarations.append(
            {
                "key": key,
                "label": DECLARATION_LABELS[key],
                "count": n,
                "pct": round(100 * n / total_contribs) if total_contribs else 0,
            }
        )

    rev_row = query_one(
        """
        SELECT COUNT(*) AS n
        FROM reviews rv
        JOIN contributions c ON c.id = rv.contribution_id
        JOIN milestones m ON m.id = c.milestone_id
        WHERE rv.reviewer_id = ? AND m.project_id = ? AND rv.decision = 'approve'
        """,
        (r["user_id"], r["project_id"]),
    )
    reviews_n = dict(rev_row)["n"] if rev_row else 0

    if total_contribs and reviews_n:
        role_label = "Contributor and expert reviewer"
    elif total_contribs:
        role_label = "Contributor"
    elif reviews_n:
        role_label = "Expert reviewer"
    else:
        role_label = "Participant"

    # --- ledger proof ---
    entry = query_one(
        """
        SELECT * FROM ledger_entries
        WHERE action = 'credential_issued' AND payload_json LIKE ?
        ORDER BY id ASC LIMIT 1
        """,
        ('%"credential_hash":"' + credential_hash + '"%',),
    )
    chain = _chain_status()
    ledger_info: Optional[Dict[str, Any]] = None
    entry_ok = False
    if entry:
        e = dict(entry)
        entry_ok = _entry_ok(e)
        ledger_info = {
            "entry_id": e["id"],
            "entry_hash": e["entry_hash"],
            "prev_hash": e["prev_hash"],
            "timestamp": e["timestamp"],
            "entry_ok": entry_ok,
        }

    revocation = _revocation(credential_hash)
    revoked = bool(revocation)
    if revoked:
        status = "revoked"
    elif entry and entry_ok and chain.get("ok"):
        status = "valid"
    else:
        status = "unverified"

    verify_url = f"{base_url}/verify/{credential_hash}"
    short_id = _short_id(credential_hash)
    try:
        dt = datetime.fromisoformat(r["issued_at"].replace("Z", "+00:00"))
        year, month = dt.year, dt.month
    except Exception:
        year, month = "", ""
    linkedin_url = "https://www.linkedin.com/profile/add?" + urlencode(
        {
            "startTask": "CERTIFICATION_NAME",
            "name": f"{r['project_title']} - Verified Contributor",
            "organizationName": "Provenance",
            "issueYear": year,
            "issueMonth": month,
            "certUrl": verify_url,
            "certId": short_id,
        }
    )

    return {
        "credential_hash": credential_hash,
        "short_id": short_id,
        "status": status,
        "kind": r["kind"],
        "holder_name": _display_name(r["holder_name"], r["holder_is_minor"]),
        "holder_institution": r["holder_institution"],
        "project_title": r["project_title"],
        "project_summary": r["public_summary"],
        "sponsor_name": r["sponsor_name"],
        "role_label": role_label,
        "contributions_approved": total_contribs,
        "reviews_approved": reviews_n,
        "declarations": declarations,
        "issued_at": r["issued_at"],
        "issued_pretty": _pretty_date(r["issued_at"]),
        "ledger": ledger_info,
        "chain_ok": bool(chain.get("ok")),
        "chain_checked": chain.get("checked"),
        "chain_head": chain.get("head_hash"),
        "chain_broken_at": chain.get("first_broken_id"),
        "revoked": revoked,
        "revoked_at": dict(revocation)["revoked_at"] if revoked else None,
        "revoked_reason": REVOKE_REASONS.get(dict(revocation)["reason_code"], "Revoked")
        if revoked
        else None,
        "verify_url": verify_url,
        "print_url": f"{base_url}/certificate/{credential_hash}",
        "qr_url": f"/certificate/{credential_hash}/qr.svg",
        "linkedin_url": linkedin_url,
    }


def make_qr_svg(text: str) -> bytes:
    """QR as a standalone SVG with a white background (scans on dark pages too)."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_Q,
        box_size=10,
        border=4,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgFillImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()


class RevokeIn(BaseModel):
    reason_code: str
    note: Optional[str] = None


# ─────────────────────────────────────────────
# Router (templates are passed in from main.py to avoid a circular import)
# ─────────────────────────────────────────────
def build_router(templates) -> APIRouter:
    router = APIRouter()

    @router.get("/verify/{credential_hash}")
    def verify_page(
        credential_hash: str,
        request: Request,
        user: Optional[Any] = Depends(current_user),
    ):
        cert = load_certificate(credential_hash, _public_base(request))
        return templates.TemplateResponse(
            request,
            "verify.html",
            {"cert": cert, "user": user, "reasons": REVOKE_REASONS},
            status_code=200 if cert else 404,
        )

    @router.get("/certificate/{credential_hash}")
    def certificate_print_page(credential_hash: str, request: Request):
        cert = load_certificate(credential_hash, _public_base(request))
        if not cert:
            raise HTTPException(status_code=404, detail="Certificate not found")
        return templates.TemplateResponse(request, "certificate.html", {"cert": cert})

    @router.get("/certificate/{credential_hash}/qr.svg")
    def certificate_qr(credential_hash: str, request: Request):
        h = (credential_hash or "").strip().lower()
        if not HASH_RE.match(h) or not query_one(
            "SELECT id FROM credentials WHERE credential_hash = ?", (h,)
        ):
            raise HTTPException(status_code=404, detail="Certificate not found")
        svg = make_qr_svg(f"{_public_base(request)}/verify/{h}")
        return Response(
            content=svg,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @router.get("/api/verify/{credential_hash}")
    def api_verify(credential_hash: str, request: Request):
        cert = load_certificate(credential_hash, _public_base(request))
        if not cert:
            return JSONResponse(
                {"valid": False, "status": "not_found"}, status_code=404
            )
        out = dict(cert)
        out["valid"] = cert["status"] == "valid"
        return out

    @router.post("/api/credentials/{credential_hash}/revoke")
    def api_revoke(
        credential_hash: str,
        body: RevokeIn,
        user: Any = Depends(current_user),
    ):
        if not user or user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Forbidden: administrator access required")
        admin = user
        h = (credential_hash or "").strip().lower()
        if not HASH_RE.match(h):
            raise HTTPException(status_code=404, detail="Certificate not found")
        if body.reason_code not in REVOKE_REASONS:
            raise HTTPException(
                status_code=400,
                detail="reason_code must be one of: "
                + ", ".join(sorted(REVOKE_REASONS)),
            )
        cred = query_one(
            "SELECT id, project_id, user_id FROM credentials WHERE credential_hash = ?",
            (h,),
        )
        if not cred:
            raise HTTPException(status_code=404, detail="Certificate not found")
        if _revocation(h):
            raise HTTPException(
                status_code=409, detail="Certificate is already revoked"
            )

        note = (body.note or "").strip()[:300] or None
        revoked_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        execute(
            """
            INSERT INTO credential_revocations
                (credential_hash, reason_code, note, revoked_by, revoked_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (h, body.reason_code, note, admin["id"], revoked_at),
        )
        # Ledger payloads hold ids, hashes and short labels only (RULES.md).
        ledger.append(
            action="credential_revoked",
            actor_id=admin["id"],
            actor_type="human",
            project_id=cred["project_id"],
            payload={
                "credential_id": cred["id"],
                "credential_hash": h,
                "reason_code": body.reason_code,
                "user_id": cred["user_id"],
            },
        )
        _chain_cache["v"] = None  # force a fresh chain check on the next page view
        return {
            "status": "revoked",
            "credential_hash": h,
            "reason_code": body.reason_code,
        }

    return router
