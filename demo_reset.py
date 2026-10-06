import os
from pathlib import Path
from app.db import get_db_path, init_db, query_one
from app.seed import seed_users


def reset() -> None:
    """Delete data/app.db if present, run init_db() and seed_users(), and print a one-line summary."""
    db_path = get_db_path()
    if db_path.exists():
        try:
            db_path.unlink()
        except Exception as e:
            print(f"Warning: could not delete {db_path}: {e}")

    for suffix in ["-journal", "-shm", "-wal"]:
        extra = Path(str(db_path) + suffix)
        if extra.exists():
            try:
                extra.unlink()
            except Exception:
                pass

    init_db()
    seed_users()

    table_row = query_one(
        "SELECT count(*) as count FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    user_row = query_one("SELECT count(*) as count FROM users")
    table_count = table_row["count"] if table_row else 0
    user_count = user_row["count"] if user_row else 0

    print(f"[OK] Database reset: {table_count} tables initialized, {user_count} synthetic users seeded in {db_path}")


if __name__ == "__main__":
    reset()
