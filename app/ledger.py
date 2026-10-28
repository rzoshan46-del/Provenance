"""
app/ledger.py — Append-only hash-chain ledger for Provenance.

Only this module may INSERT into ledger_entries through append().
The only permitted UPDATE/DELETE are the clearly-labelled demo helpers
tamper_demo() and restore_demo() — no other code may touch ledger_entries
with UPDATE or DELETE (RULES.md rule m).

MOCKED: production would anchor the head hash on a public blockchain and
        use per-user Ed25519 signatures (SPEC.md §17).
"""
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db import get_db_path, get_conn
from app.access import can_view

# Genesis sentinel — prev_hash of the very first ledger entry
GENESIS_HASH = "0" * 64

_VALID_ACTOR_TYPES = frozenset({"human", "agent", "system"})


# ─────────────────────────────────────────────
# Public hash helpers (smoke tests call these)
# ─────────────────────────────────────────────

def canonical(obj: Any) -> str:
    """Canonical JSON serialisation — sort_keys, no spaces, ASCII-safe."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def compute_entry_hash(prev_hash: str, fields: Dict[str, Any]) -> str:
    """Recompute an entry_hash from prev_hash and the entry's own fields dict.

    fields must contain exactly these keys (None values become JSON null):
        timestamp, actor_id, actor_type, human_owner_id,
        action, project_id, payload_hash, charter_version
    """
    return _sha256(prev_hash + "|" + canonical(fields))


# ─────────────────────────────────────────────
# Genesis
# ─────────────────────────────────────────────

def ensure_genesis() -> None:
    """Idempotent — inserts the genesis entry only if ledger_entries is empty."""
    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None   # manual transaction control
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT COUNT(*) AS c FROM ledger_entries").fetchone()
        if row["c"] > 0:
            conn.execute("ROLLBACK")
            return

        payload = {"note": "ledger initialised"}
        payload_json = canonical(payload)
        payload_hash = _sha256(payload_json)
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

        fields: Dict[str, Any] = {
            "action": "genesis",
            "actor_id": None,
            "actor_type": "system",
            "charter_version": None,
            "human_owner_id": None,
            "payload_hash": payload_hash,
            "project_id": None,
            "timestamp": ts,
        }
        entry_hash = compute_entry_hash(GENESIS_HASH, fields)

        conn.execute(
            """
            INSERT INTO ledger_entries
                (prev_hash, entry_hash, timestamp, actor_id, actor_type,
                 human_owner_id, action, project_id, payload_json, payload_hash, charter_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (GENESIS_HASH, entry_hash, ts, None, "system", None,
             "genesis", None, payload_json, payload_hash, None),
        )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────
# Append — the ONLY normal write path
# ─────────────────────────────────────────────

def append(
    action: str,
    actor_id: Optional[int] = None,
    actor_type: str = "human",
    human_owner_id: Optional[int] = None,
    project_id: Optional[int] = None,
    payload: Optional[Dict[str, Any]] = None,
    charter_version: Optional[int] = None,
) -> int:
    """Append a new entry to the ledger. Runs inside BEGIN IMMEDIATE.

    Raises ValueError for:
    - invalid actor_type (must be human, agent, or system)
    - agent entry without human_owner_id

    Returns the new entry id.

    Payloads must contain ids, hashes and short labels only.
    NEVER put confidential text or email addresses in a payload (RULES.md l).
    """
    if actor_type not in _VALID_ACTOR_TYPES:
        raise ValueError(
            f"Invalid actor_type '{actor_type}'. Must be one of: human, agent, system."
        )
    if actor_type == "agent" and human_owner_id is None:
        raise ValueError("Agent entries must have a human_owner_id set.")
    if actor_type == "human" and human_owner_id is None:
        human_owner_id = actor_id

    if payload is None:
        payload = {}

    payload_json = canonical(payload)
    payload_hash = _sha256(payload_json)
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None   # manual transaction control
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        last = conn.execute(
            "SELECT entry_hash FROM ledger_entries ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_hash = last["entry_hash"] if last else GENESIS_HASH

        fields: Dict[str, Any] = {
            "action": action,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "charter_version": charter_version,
            "human_owner_id": human_owner_id,
            "payload_hash": payload_hash,
            "project_id": project_id,
            "timestamp": ts,
        }
        entry_hash = compute_entry_hash(prev_hash, fields)

        cursor = conn.execute(
            """
            INSERT INTO ledger_entries
                (prev_hash, entry_hash, timestamp, actor_id, actor_type,
                 human_owner_id, action, project_id, payload_json, payload_hash, charter_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (prev_hash, entry_hash, ts, actor_id, actor_type, human_owner_id,
             action, project_id, payload_json, payload_hash, charter_version),
        )
        conn.execute("COMMIT")
        return cursor.lastrowid
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────
# Verify
# ─────────────────────────────────────────────

def verify() -> Dict[str, Any]:
    """Walk all ledger entries by id and verify the hash chain.

    Checks per entry (in order):
      (1) payload_hash == SHA-256(payload_json)
      (2) entry_hash recomputes correctly
      (3) prev_hash equals the previous entry's entry_hash (GENESIS_HASH for the first)

    Returns:
        ok, checked, first_broken_id, reason, head_hash
    Reasons: "payload hash mismatch", "entry hash mismatch",
             "prev_hash does not match previous entry", "invalid payload JSON"
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM ledger_entries ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {
            "ok": True,
            "checked": 0,
            "first_broken_id": None,
            "reason": None,
            "head_hash": GENESIS_HASH,
        }

    prev_entry_hash = GENESIS_HASH
    head_hash = rows[-1]["entry_hash"]

    for i, row in enumerate(rows):
        entry_id = row["id"]

        # (1) payload JSON must be parseable
        try:
            json.loads(row["payload_json"])
        except (json.JSONDecodeError, TypeError, ValueError):
            return {
                "ok": False,
                "checked": i + 1,
                "first_broken_id": entry_id,
                "reason": "invalid payload JSON",
                "head_hash": head_hash,
            }

        # (1) payload hash
        computed_payload_hash = _sha256(row["payload_json"])
        if computed_payload_hash != row["payload_hash"]:
            return {
                "ok": False,
                "checked": i + 1,
                "first_broken_id": entry_id,
                "reason": "payload hash mismatch",
                "head_hash": head_hash,
            }

        # (2) entry hash
        fields: Dict[str, Any] = {
            "action": row["action"],
            "actor_id": row["actor_id"],
            "actor_type": row["actor_type"],
            "charter_version": row["charter_version"],
            "human_owner_id": row["human_owner_id"],
            "payload_hash": row["payload_hash"],
            "project_id": row["project_id"],
            "timestamp": row["timestamp"],
        }
        computed_entry_hash = compute_entry_hash(row["prev_hash"], fields)
        if computed_entry_hash != row["entry_hash"]:
            return {
                "ok": False,
                "checked": i + 1,
                "first_broken_id": entry_id,
                "reason": "entry hash mismatch",
                "head_hash": head_hash,
            }

        # (3) prev_hash link
        if row["prev_hash"] != prev_entry_hash:
            return {
                "ok": False,
                "checked": i + 1,
                "first_broken_id": entry_id,
                "reason": "prev_hash does not match previous entry",
                "head_hash": head_hash,
            }

        prev_entry_hash = row["entry_hash"]

    return {
        "ok": True,
        "checked": len(rows),
        "first_broken_id": None,
        "reason": None,
        "head_hash": rows[-1]["entry_hash"],
    }


# ─────────────────────────────────────────────
# List entries
# ─────────────────────────────────────────────

def _full_entry(row: sqlite3.Row) -> Dict[str, Any]:
    payload = None
    try:
        payload = json.loads(row["payload_json"])
    except Exception:
        payload = None
    return {
        "id": row["id"],
        "prev_hash": row["prev_hash"],
        "entry_hash": row["entry_hash"],
        "timestamp": row["timestamp"],
        "actor_id": row["actor_id"],
        "actor_name": row["actor_name"],
        "actor_type": row["actor_type"],
        "human_owner_id": row["human_owner_id"],
        "action": row["action"],
        "project_id": row["project_id"],
        "charter_version": row["charter_version"],
        "payload": payload,
        "payload_hash": row["payload_hash"],
    }


def _redacted_entry(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "prev_hash": row["prev_hash"],
        "entry_hash": row["entry_hash"],
        "timestamp": row["timestamp"],
        "redacted": True,
    }


def list_entries(
    user: Any,
    project_id: Optional[int] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Return ledger entries in ascending id order.

    Visibility (SPEC §17):
    - Entries with no project_id (genesis, system) → always full.
    - Entries with a project_id → full if can_view(user, project, 'roster'),
      otherwise redacted (id, prev_hash, entry_hash, timestamp, redacted=True).
      The chain stays checkable even when content is hidden.
    """
    conn = get_conn()
    try:
        if project_id is not None:
            rows = conn.execute(
                """
                SELECT le.*,
                    CASE
                        WHEN le.actor_type = 'agent' THEN a.name
                        ELSE u.name
                    END AS actor_name
                FROM ledger_entries le
                LEFT JOIN users u ON u.id = le.actor_id
                LEFT JOIN agents a ON a.id = le.actor_id
                WHERE le.project_id = ?
                ORDER BY le.id ASC
                LIMIT ?
                """,
                (project_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT le.*,
                    CASE
                        WHEN le.actor_type = 'agent' THEN a.name
                        ELSE u.name
                    END AS actor_name
                FROM ledger_entries le
                LEFT JOIN users u ON u.id = le.actor_id
                LEFT JOIN agents a ON a.id = le.actor_id
                ORDER BY le.id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    finally:
        conn.close()

    # Cache projects needed for visibility checks
    project_cache: Dict[int, Any] = {}

    result = []
    for row in rows:
        pid = row["project_id"]
        if pid is None:
            # System/genesis — no project scope, visible to all
            result.append(_full_entry(row))
        else:
            if pid not in project_cache:
                project_cache[pid] = get_conn()
                tmp = get_conn()
                try:
                    p = tmp.execute(
                        "SELECT * FROM projects WHERE id = ?", (pid,)
                    ).fetchone()
                finally:
                    tmp.close()
                project_cache[pid] = p

            project = project_cache[pid]
            if project and can_view(user, project, "roster"):
                result.append(_full_entry(row))
            else:
                result.append(_redacted_entry(row))

    return result


# ─────────────────────────────────────────────
# Demo mode flag
# ─────────────────────────────────────────────

def demo_mode() -> bool:
    """Return True unless PROVENANCE_DEMO env var is exactly "0". Read on every call."""
    return os.environ.get("PROVENANCE_DEMO", "1") != "0"


# ─────────────────────────────────────────────
# Demo tools — the ONLY places allowed to UPDATE ledger_entries
# ─────────────────────────────────────────────

def tamper_demo(entry_id: Optional[int] = None) -> int:
    """DEMO TOOL: simulates someone editing the database directly.

    Adds "_tampered": true to the payload_json of an old entry using a raw
    UPDATE, so verify() will fail at that entry. Defaults to the earliest
    entry that has a project_id.

    Raises ValueError if no matching entry is found.
    """
    conn = get_conn()
    try:
        if entry_id is not None:
            row = conn.execute(
                "SELECT id, payload_json FROM ledger_entries WHERE id = ?",
                (entry_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT id, payload_json FROM ledger_entries
                   WHERE project_id IS NOT NULL
                   ORDER BY id ASC LIMIT 1"""
            ).fetchone()

        if not row:
            raise ValueError(f"No ledger entry found (entry_id={entry_id})")

        try:
            payload = json.loads(row["payload_json"])
        except Exception:
            payload = {}
        payload["_tampered"] = True
        # DEMO TOOL: raw UPDATE — the ONLY permitted UPDATE in this file
        conn.execute(
            "UPDATE ledger_entries SET payload_json = ? WHERE id = ?",
            (json.dumps(payload), row["id"]),
        )
        conn.commit()
        return row["id"]
    finally:
        conn.close()


def restore_demo() -> int:
    """DEMO TOOL: simulates someone editing the database directly.

    Removes the "_tampered" key from every payload_json that has it and
    re-serialises with canonical() so the original byte string is restored.
    Returns count of restored rows.
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, payload_json FROM ledger_entries WHERE payload_json LIKE '%_tampered%'"
        ).fetchall()

        count = 0
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                continue
            if "_tampered" not in payload:
                continue
            del payload["_tampered"]
            # Re-serialise with canonical() — restores the original byte string exactly
            # DEMO TOOL: raw UPDATE — the ONLY permitted UPDATE in this file
            conn.execute(
                "UPDATE ledger_entries SET payload_json = ? WHERE id = ?",
                (canonical(payload), row["id"]),
            )
            count += 1

        conn.commit()
        return count
    finally:
        conn.close()


def reset_for_demo() -> None:
    """DEMO TOOL: reset ledger for demo mode.

    Deletes all ledger rows and re-runs ensure_genesis().
    The ONLY permitted DELETE on ledger_entries in the entire codebase.
    """
    if not demo_mode():
        raise PermissionError("Demo mode disabled")
    conn = get_conn()
    try:
        conn.execute("DELETE FROM ledger_entries")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'ledger_entries'")
        conn.commit()
    finally:
        conn.close()
    ensure_genesis()
