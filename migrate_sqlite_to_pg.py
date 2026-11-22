"""
migrate_sqlite_to_pg.py — Safely migrate existing SQLite data to PostgreSQL.
Usage:
    PROVENANCE_DATABASE_URL="postgresql://user:pass@host/db" python migrate_sqlite_to_pg.py
"""

import json
import os
import sqlite3
import sys

from app.db import get_conn, has_postgres_url, init_db

TABLES_IN_ORDER = [
    "users",
    "projects",
    "charters",
    "charter_acceptances",
    "milestones",
    "agents",
    "contributions",
    "ledger_entries",
    "escrows",
    "payouts",
    "reviews",
    "disputes",
    "ai_calls",
    "credentials",
    "credential_revocations",
    "project_reviews",
]


def migrate():
    if not has_postgres_url():
        print("[ERROR] PROVENANCE_DATABASE_URL environment variable must be set to a PostgreSQL URL.")
        sys.exit(1)

    sqlite_path = os.environ.get("PROVENANCE_DB", "data/app.db")
    if not os.path.exists(sqlite_path):
        print(f"[ERROR] Source SQLite database '{sqlite_path}' does not exist.")
        sys.exit(1)

    print(f"[1/4] Reading data from source SQLite database: {sqlite_path}")
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    print("[2/4] Initializing target PostgreSQL schema...")
    init_db()

    pg_conn = get_conn()
    print("[3/4] Migrating table rows in dependency order...")

    total_records = 0
    with pg_conn:
        with pg_conn.cursor() as pg_cur:
            for table in TABLES_IN_ORDER:
                # Check if table exists in sqlite
                table_check = sqlite_conn.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()[0]
                if not table_check:
                    continue

                rows = sqlite_conn.execute(f"SELECT * FROM {table} ORDER BY id ASC").fetchall()
                if not rows:
                    continue

                col_names = [col[0] for col in sqlite_conn.execute(f"SELECT * FROM {table} LIMIT 1").description]
                placeholders = ", ".join(["%s"] * len(col_names))
                cols_str = ", ".join(col_names)

                insert_sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

                inserted = 0
                for r in rows:
                    values = [r[col] for col in col_names]
                    pg_cur.execute(insert_sql, values)
                    inserted += 1

                # Reset sequence for PostgreSQL serial column
                pg_cur.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(max(id), 1), true) FROM {table}"
                )

                print(f"  -> {table}: {inserted} rows migrated.")
                total_records += inserted

    sqlite_conn.close()
    pg_conn.close()
    print(f"[4/4] Migration complete! Successfully transferred {total_records} records to PostgreSQL.")


if __name__ == "__main__":
    migrate()
