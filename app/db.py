import os
from pathlib import Path
import sqlite3
from typing import Any, List, Optional, Sequence, Union

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None

DB_DEFAULT_PATH = "data/app.db"


def get_db_path() -> Path:
    """Return the database Path configured via PROVENANCE_DB env var."""
    raw_path = os.environ.get("PROVENANCE_DB", DB_DEFAULT_PATH)
    path = Path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def has_postgres_url() -> bool:
    url = os.environ.get("PROVENANCE_DATABASE_URL", "").strip()
    return bool(url and url.startswith(("postgresql://", "postgres://")))


def get_conn() -> Any:
    """Return a SQLite connection by default, or a Postgres connection when PROVENANCE_DATABASE_URL is set."""
    if has_postgres_url():
        if psycopg is None:
            raise RuntimeError("psycopg is required when PROVENANCE_DATABASE_URL is configured")
        return psycopg.connect(os.environ["PROVENANCE_DATABASE_URL"])

    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create all 14 tables as specified in SPEC.md section 5 if they do not exist."""
    conn = get_conn()
    try:
        with conn:
            conn.executescript(
                """
                -- 1. users
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('student', 'expert', 'sponsor', 'admin')),
                    verification_level INTEGER NOT NULL DEFAULT 0,
                    institution TEXT,
                    is_minor INTEGER NOT NULL DEFAULT 0,
                    guardian_consent INTEGER NOT NULL DEFAULT 0,
                    conflict_orgs TEXT NOT NULL DEFAULT '[]',
                    skills TEXT NOT NULL DEFAULT '[]',
                    bio TEXT
                );

                -- 2. projects
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sponsor_id INTEGER NOT NULL REFERENCES users(id),
                    title TEXT NOT NULL,
                    public_summary TEXT NOT NULL,
                    confidential_brief TEXT NOT NULL,
                    sensitivity_label TEXT NOT NULL CHECK(sensitivity_label IN ('public', 'internal', 'confidential')),
                    engagement_model TEXT NOT NULL CHECK(engagement_model IN ('funded', 'stipend', 'knowledge_sharing', 'institutional_credit')),
                    status TEXT NOT NULL,
                    current_charter_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                -- 3. charters
                CREATE TABLE IF NOT EXISTS charters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    version INTEGER NOT NULL,
                    terms_json TEXT NOT NULL,
                    hash TEXT NOT NULL,
                    published_at TEXT NOT NULL
                );

                -- 4. charter_acceptances
                CREATE TABLE IF NOT EXISTS charter_acceptances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    charter_version INTEGER NOT NULL,
                    engagement_model_ack INTEGER NOT NULL DEFAULT 0,
                    accepted_at TEXT NOT NULL
                );

                -- 5. milestones
                CREATE TABLE IF NOT EXISTS milestones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    title TEXT NOT NULL,
                    deliverables TEXT NOT NULL,
                    acceptance_criteria TEXT NOT NULL,
                    required_skills TEXT NOT NULL DEFAULT '[]',
                    amount_inr INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    acceptance_window_days INTEGER NOT NULL DEFAULT 7,
                    created_at TEXT NOT NULL
                );

                -- 6. agents (needed before contributions for foreign key reference)
                CREATE TABLE IF NOT EXISTS agents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('scoping', 'matching', 'workspace', 'integrity')),
                    human_owner_id INTEGER NOT NULL REFERENCES users(id),
                    project_id INTEGER REFERENCES projects(id),
                    allowed_tools TEXT NOT NULL DEFAULT '[]'
                );

                -- 7. contributions
                CREATE TABLE IF NOT EXISTS contributions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    milestone_id INTEGER NOT NULL REFERENCES milestones(id),
                    author_id INTEGER NOT NULL REFERENCES users(id),
                    agent_id INTEGER REFERENCES agents(id),
                    artefact_title TEXT NOT NULL,
                    artefact_text TEXT NOT NULL,
                    artefact_hash TEXT NOT NULL,
                    ai_declaration TEXT NOT NULL CHECK(ai_declaration IN ('human', 'ai_assisted', 'agent_generated')),
                    similarity_score REAL NOT NULL DEFAULT 0.0,
                    review_status TEXT NOT NULL CHECK(review_status IN ('pending', 'approved', 'rejected', 'flagged')),
                    impact_weight REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL
                );

                -- 8. ledger_entries
                CREATE TABLE IF NOT EXISTS ledger_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prev_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    actor_id INTEGER,
                    actor_type TEXT NOT NULL CHECK(actor_type IN ('human', 'agent', 'system')),
                    human_owner_id INTEGER,
                    action TEXT NOT NULL,
                    project_id INTEGER REFERENCES projects(id),
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    charter_version INTEGER
                );

                -- 9. escrows
                CREATE TABLE IF NOT EXISTS escrows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    milestone_id INTEGER NOT NULL REFERENCES milestones(id),
                    amount_inr INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('draft', 'funded', 'submitted', 'accepted', 'released', 'disputed', 'refunded')),
                    updated_at TEXT NOT NULL
                );

                -- 10. payouts
                CREATE TABLE IF NOT EXISTS payouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    escrow_id INTEGER NOT NULL REFERENCES escrows(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    amount_inr INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    rationale_json TEXT NOT NULL,
                    receipt_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                -- 11. reviews
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contribution_id INTEGER NOT NULL REFERENCES contributions(id),
                    reviewer_id INTEGER NOT NULL REFERENCES users(id),
                    decision TEXT NOT NULL,
                    reasons TEXT NOT NULL,
                    criteria_ref TEXT,
                    created_at TEXT NOT NULL
                );

                -- 12. disputes
                CREATE TABLE IF NOT EXISTS disputes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    milestone_id INTEGER NOT NULL REFERENCES milestones(id),
                    raised_by INTEGER NOT NULL REFERENCES users(id),
                    status TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    resolution TEXT,
                    created_at TEXT NOT NULL
                );

                -- 13. ai_calls
                CREATE TABLE IF NOT EXISTS ai_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER REFERENCES agents(id),
                    human_owner_id INTEGER NOT NULL REFERENCES users(id),
                    project_id INTEGER REFERENCES projects(id),
                    sensitivity_label TEXT NOT NULL,
                    model_route TEXT NOT NULL CHECK(model_route IN ('api', 'local', 'canned')),
                    prompt_summary TEXT NOT NULL,
                    response_summary TEXT NOT NULL,
                    approved_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL
                );

                -- 14. credentials
                CREATE TABLE IF NOT EXISTS credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    kind TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    credential_hash TEXT NOT NULL
                );
                """
            )
    finally:
        conn.close()


def query_one(query: str, params: Sequence[Any] = ()) -> Optional[sqlite3.Row]:
    """Execute a parameterised SELECT query and return the first row or None."""
    conn = get_conn()
    try:
        if has_postgres_url():
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, params)
                return cursor.fetchone()
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()
    finally:
        conn.close()


def query_all(query: str, params: Sequence[Any] = ()) -> List[sqlite3.Row]:
    """Execute a parameterised SELECT query and return all matching rows."""
    conn = get_conn()
    try:
        if has_postgres_url():
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        conn.close()


def execute(query: str, params: Sequence[Any] = ()) -> int:
    """Execute a parameterised DML statement, commit, and return lastrowid (or rowcount)."""
    conn = get_conn()
    try:
        if has_postgres_url():
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                conn.commit()
                return cursor.lastrowid or 0
        with conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.lastrowid
    finally:
        conn.close()
