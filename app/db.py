"""Database connection and query execution utilities."""
import os
import sqlite3
from pathlib import Path
from typing import Any, List, Optional, Sequence

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None

DB_DEFAULT_PATH = "data/app.db"


def get_db_path() -> Path:
    """Return the database Path configured via PROVENANCE_DB env var."""
    default_path = (
        "/tmp/app.db"
        if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        else DB_DEFAULT_PATH
    )
    raw_path = os.environ.get("PROVENANCE_DB", default_path)
    path = Path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_postgres_url() -> str:
    return (
        os.environ.get("PROVENANCE_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    ).strip()


def has_postgres_url() -> bool:
    url = get_postgres_url()
    return bool(url and url.startswith(("postgresql://", "postgres://")))


def get_conn() -> Any:
    """Return a SQLite connection by default, or a Postgres connection when DATABASE_URL is configured."""
    if has_postgres_url():
        if psycopg is None:
            raise RuntimeError(
                "psycopg is required when DATABASE_URL or PROVENANCE_DATABASE_URL is configured"
            )
        return psycopg.connect(get_postgres_url())

    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _postgres_query(query: str) -> str:
    """Convert SQLite-style positional placeholders and common SQL for psycopg."""
    parts = query.split("?")
    if len(parts) == 1:
        return query
    return "%s".join(parts)


def get_database_status() -> dict:
    conn = get_conn()
    try:
        if has_postgres_url():
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT COUNT(*) AS count FROM users")
                users = cursor.fetchone()["count"]
                cursor.execute(
                    "SELECT COUNT(*) AS count FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
                tables = cursor.fetchone()["count"]
            return {"status": "ok", "database": "postgresql", "tables": tables, "users": users}
        cursor = conn.cursor()
        cursor.execute(
            "SELECT count(*) as count FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) as count FROM users")
        users = cursor.fetchone()[0]
        return {"status": "ok", "database": "sqlite", "tables": tables, "users": users}
    finally:
        conn.close()


def init_db() -> None:
    """Create all 14 tables as specified in SPEC.md section 5 if they do not exist."""
    conn = get_conn()
    try:
        with conn:
            if has_postgres_url():
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL,
                        password_hash TEXT, role TEXT NOT NULL,
                        verification_level INTEGER NOT NULL DEFAULT 0, institution TEXT,
                        is_minor INTEGER NOT NULL DEFAULT 0, guardian_consent INTEGER NOT NULL DEFAULT 0,
                        conflict_orgs TEXT NOT NULL DEFAULT '[]', skills TEXT NOT NULL DEFAULT '[]', bio TEXT,
                        session_epoch INTEGER NOT NULL DEFAULT 0, session_auth_at TEXT
                    )
                """)
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique ON users(lower(email))")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS projects (
                        id SERIAL PRIMARY KEY, sponsor_id INTEGER NOT NULL REFERENCES users(id),
                        title TEXT NOT NULL, public_summary TEXT NOT NULL, confidential_brief TEXT NOT NULL,
                        sensitivity_label TEXT NOT NULL, engagement_model TEXT NOT NULL, status TEXT NOT NULL,
                        current_charter_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS charters (
                        id SERIAL PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
                        version INTEGER NOT NULL, terms_json TEXT NOT NULL, hash TEXT NOT NULL, published_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS charter_acceptances (
                        id SERIAL PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
                        user_id INTEGER NOT NULL REFERENCES users(id), charter_version INTEGER NOT NULL,
                        engagement_model_ack INTEGER NOT NULL DEFAULT 0, accepted_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS milestones (
                        id SERIAL PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
                        title TEXT NOT NULL, deliverables TEXT NOT NULL, acceptance_criteria TEXT NOT NULL,
                        required_skills TEXT NOT NULL DEFAULT '[]', amount_inr INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL, acceptance_window_days INTEGER NOT NULL DEFAULT 7, created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS agents (
                        id SERIAL PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                        human_owner_id INTEGER NOT NULL REFERENCES users(id),
                        project_id INTEGER REFERENCES projects(id), allowed_tools TEXT NOT NULL DEFAULT '[]'
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS contributions (
                        id SERIAL PRIMARY KEY, milestone_id INTEGER NOT NULL REFERENCES milestones(id),
                        author_id INTEGER NOT NULL REFERENCES users(id), agent_id INTEGER REFERENCES agents(id),
                        artefact_title TEXT NOT NULL, artefact_text TEXT NOT NULL, artefact_hash TEXT NOT NULL,
                        ai_declaration TEXT NOT NULL, similarity_score REAL NOT NULL DEFAULT 0.0,
                        review_status TEXT NOT NULL, impact_weight REAL NOT NULL DEFAULT 1.0, created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS ledger_entries (
                        id SERIAL PRIMARY KEY, prev_hash TEXT NOT NULL, entry_hash TEXT NOT NULL,
                        timestamp TEXT NOT NULL, actor_id INTEGER, actor_type TEXT NOT NULL,
                        human_owner_id INTEGER, action TEXT NOT NULL, project_id INTEGER REFERENCES projects(id),
                        payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, charter_version INTEGER
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS escrows (
                        id SERIAL PRIMARY KEY, milestone_id INTEGER NOT NULL REFERENCES milestones(id),
                        amount_inr INTEGER NOT NULL, state TEXT NOT NULL, updated_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS payouts (
                        id SERIAL PRIMARY KEY, escrow_id INTEGER NOT NULL REFERENCES escrows(id),
                        user_id INTEGER NOT NULL REFERENCES users(id), amount_inr INTEGER NOT NULL,
                        role TEXT NOT NULL, rationale_json TEXT NOT NULL, receipt_hash TEXT NOT NULL, created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS reviews (
                        id SERIAL PRIMARY KEY, contribution_id INTEGER NOT NULL REFERENCES contributions(id),
                        reviewer_id INTEGER NOT NULL REFERENCES users(id), decision TEXT NOT NULL,
                        reasons TEXT NOT NULL, criteria_ref TEXT, created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS disputes (
                        id SERIAL PRIMARY KEY, milestone_id INTEGER NOT NULL REFERENCES milestones(id),
                        raised_by INTEGER NOT NULL REFERENCES users(id), status TEXT NOT NULL,
                        evidence_json TEXT NOT NULL, resolution TEXT, created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS ai_calls (
                        id SERIAL PRIMARY KEY, agent_id INTEGER REFERENCES agents(id),
                        human_owner_id INTEGER NOT NULL REFERENCES users(id), project_id INTEGER REFERENCES projects(id),
                        sensitivity_label TEXT NOT NULL, model_route TEXT NOT NULL, prompt_summary TEXT NOT NULL,
                        response_summary TEXT NOT NULL, approved_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS credentials (
                        id SERIAL PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
                        user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
                        issued_at TEXT NOT NULL, credential_hash TEXT NOT NULL
                    )
                """)

                return
            conn.executescript(
                """
                -- 1. users
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    password_hash TEXT,
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
            columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            if "password_hash" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
            if "session_epoch" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0")
            if "session_auth_at" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN session_auth_at TEXT")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique ON users(email)")
    finally:
        conn.close()


def query_one(query: str, params: Sequence[Any] = ()) -> Optional[sqlite3.Row]:
    """Execute a parameterised SELECT query and return the first row or None."""
    conn = get_conn()
    try:
        if has_postgres_url():
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(_postgres_query(query), params)
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
                cursor.execute(_postgres_query(query), params)
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
                pg_query = _postgres_query(query)
                if pg_query.strip().upper().startswith("INSERT") and "RETURNING " not in pg_query.upper():
                    pg_query = pg_query.rstrip().rstrip(";") + " RETURNING id"
                cursor.execute(pg_query, params)
                if cursor.description:
                    row = cursor.fetchone()
                    if row:
                        conn.commit()
                        return int(row[0])
                conn.commit()
                return 0
        with conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.lastrowid
    finally:
        conn.close()
