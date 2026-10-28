"""
app/demo.py — Demo reset and orchestrator support.

DEMO TOOL: reset() resets database and ledger to clean initial state.
"""
from typing import Any, Dict
from app.db import get_conn, query_one
import app.ledger as ledger
from app.seed import seed_projects, seed_users


def reset() -> Dict[str, Any]:
    """DEMO TOOL: empties all 14 tables, then runs seed_users, ledger.ensure_genesis and seed_projects.

    Ledger rows may only be deleted by ledger.reset_for_demo() inside app/ledger.py.
    """
    if not ledger.demo_mode():
        raise PermissionError("Demo mode disabled")

    # 1. Clear 13 non-ledger tables with foreign keys disabled
    tables = [
        "credentials",
        "ai_calls",
        "disputes",
        "reviews",
        "payouts",
        "escrows",
        "contributions",
        "agents",
        "milestones",
        "charter_acceptances",
        "charters",
        "projects",
        "users",
    ]
    conn = get_conn()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in tables:
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM sqlite_sequence")
        conn.commit()
    finally:
        conn.close()

    # 2. Reset ledger via clearly-labelled helper in app/ledger.py
    ledger.reset_for_demo()

    # 3. Seed users, then seed projects (seed_projects also logs project_posted to ledger)
    seed_users()
    seed_projects()

    user_count = query_one("SELECT COUNT(*) AS c FROM users")["c"]
    project_count = query_one("SELECT COUNT(*) AS c FROM projects")["c"]
    ledger_count = query_one("SELECT COUNT(*) AS c FROM ledger_entries")["c"]

    return {
        "status": "ok",
        "users": user_count,
        "projects": project_count,
        "ledger_entries": ledger_count,
        "user_count": user_count,
        "project_count": project_count,
        "ledger_count": ledger_count,
    }
