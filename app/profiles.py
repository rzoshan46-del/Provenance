import datetime
import json
import sqlite3
from typing import Any, Dict, List, Optional
from app.db import execute, query_all, query_one


def get_initials(name: Optional[str]) -> str:
    """Return 1-2 uppercase initials from a person's name for safe avatar rendering."""
    if not name:
        return "?"
    parts = [p.strip() for p in name.split() if p.strip()]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def ensure_user_profiles_table() -> None:
    """Ensure user_profiles table exists on demand without breaking initial table counts."""
    execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            headline TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            institution TEXT DEFAULT '',
            github_url TEXT DEFAULT '',
            linkedin_url TEXT DEFAULT '',
            portfolio_url TEXT DEFAULT '',
            is_public INTEGER NOT NULL DEFAULT 1,
            show_institution INTEGER NOT NULL DEFAULT 1,
            show_credentials INTEGER NOT NULL DEFAULT 1,
            onboarding_completed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT
        );
        """
    )


def get_or_create_profile(user_id: int) -> Dict[str, Any]:
    """Retrieve user_profiles row or create default if not present."""
    ensure_user_profiles_table()
    row = query_one("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    if row:
        return dict(row)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # Check if this is an existing seeded user (marked as completed by default)
    user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    is_seeded = bool(user and user["verification_level"] >= 1 and user["institution"])

    execute(
        """
        INSERT OR IGNORE INTO user_profiles
            (user_id, headline, bio, institution, github_url, linkedin_url, portfolio_url,
             is_public, show_institution, show_credentials, onboarding_completed, updated_at)
        VALUES (?, '', '', ?, '', '', '', 1, 1, 1, ?, ?)
        """,
        (user_id, user["institution"] if user else "", 1 if is_seeded else 0, now),
    )
    row = query_one("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    return dict(row) if row else {
        "user_id": user_id,
        "headline": "",
        "bio": "",
        "institution": "",
        "github_url": "",
        "linkedin_url": "",
        "portfolio_url": "",
        "is_public": 1,
        "show_institution": 1,
        "show_credentials": 1,
        "onboarding_completed": 1 if is_seeded else 0,
    }


def complete_onboarding(user_id: int, role: str, institution: str = "") -> Dict[str, Any]:
    """Assign role after Google sign-in. Admin is NEVER allowed to be self-selected."""
    role = (role or "").strip().lower()
    if role == "admin":
        raise ValueError("Admin role cannot be self-selected.")
    if role not in ("student", "expert", "sponsor"):
        raise ValueError(f"Invalid role: {role}. Must be student, expert, or sponsor.")

    # Students get in immediately with level 1 verification
    v_level = 1 if role == "student" else 1
    ensure_user_profiles_table()

    execute(
        "UPDATE users SET role = ?, verification_level = ?, institution = ? WHERE id = ?",
        (role, v_level, institution.strip(), user_id),
    )
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    ensure_user_profiles_table()
    execute(
        """
        INSERT INTO user_profiles (user_id, institution, onboarding_completed, updated_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            institution = excluded.institution,
            onboarding_completed = 1,
            updated_at = excluded.updated_at
        """,
        (user_id, institution.strip(), now),
    )
    user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    return dict(user) if user else {}


def update_profile(
    user_id: int,
    name: str,
    headline: str,
    bio: str,
    institution: str,
    skills_raw: str,
    github_url: str,
    linkedin_url: str,
    portfolio_url: str,
    is_public: bool,
    show_institution: bool,
    show_credentials: bool,
) -> None:
    """Save extended profile fields & privacy toggles."""
    # Parse skills
    skills_list: List[str] = []
    if skills_raw:
        skills_list = [s.strip().lower() for s in skills_raw.replace(";", ",").split(",") if s.strip()]

    execute(
        "UPDATE users SET name = ?, bio = ?, institution = ?, skills = ? WHERE id = ?",
        (name.strip(), bio.strip(), institution.strip(), json.dumps(skills_list), user_id),
    )

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    ensure_user_profiles_table()
    execute(
        """
        INSERT INTO user_profiles
            (user_id, headline, bio, institution, github_url, linkedin_url, portfolio_url,
             is_public, show_institution, show_credentials, onboarding_completed, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            headline = excluded.headline,
            bio = excluded.bio,
            institution = excluded.institution,
            github_url = excluded.github_url,
            linkedin_url = excluded.linkedin_url,
            portfolio_url = excluded.portfolio_url,
            is_public = excluded.is_public,
            show_institution = excluded.show_institution,
            show_credentials = excluded.show_credentials,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            headline.strip(),
            bio.strip(),
            institution.strip(),
            github_url.strip(),
            linkedin_url.strip(),
            portfolio_url.strip(),
            1 if is_public else 0,
            1 if show_institution else 0,
            1 if show_credentials else 0,
            now,
        ),
    )
