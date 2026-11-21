import datetime
import ipaddress
import json
import re
import sqlite3
import urllib.parse
from typing import Any, Dict, List, Optional
from app.db import execute, query_all, query_one

RESERVED_HANDLES = {
    "admin", "api", "login", "logout", "u", "settings", "verify", "static", "help",
    "about", "me", "profile", "projects", "story", "terms", "privacy", "health",
    "metrics", "dashboard", "cohorts", "copilot", "auth", "home", "search", "app",
    "certificate", "certificates", "user", "users", "root", "system"
}


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


def get_initials_svg(name: Optional[str], size: int = 40) -> str:
    """Generate safe inline SVG initials avatar (no image uploads permitted)."""
    initials = get_initials(name)
    radius = size // 2
    font_size = max(10, size // 2 - 2)
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" class="avatar-initials-svg">'
        f'<rect width="{size}" height="{size}" rx="{radius}" fill="#3b82f6"/>'
        f'<text x="50%" y="50%" dominant-baseline="central" text-anchor="middle" fill="#ffffff" font-family="system-ui, sans-serif" font-size="{font_size}" font-weight="600">{initials}</text>'
        f'</svg>'
    )


def ensure_user_profiles_table() -> None:
    """Ensure user_profiles, handle_history, account_events, and notifications tables exist on demand."""
    from app.db import get_conn, has_postgres_url
    conn = get_conn()
    try:
        if has_postgres_url():
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_profiles (
                        user_id INTEGER PRIMARY KEY REFERENCES users(id),
                        display_name TEXT DEFAULT '',
                        handle TEXT UNIQUE,
                        handle_changed_at TEXT,
                        location TEXT DEFAULT '',
                        skills TEXT DEFAULT '[]',
                        instagram_url TEXT DEFAULT '',
                        x_url TEXT DEFAULT '',
                        youtube_url TEXT DEFAULT '',
                        scholar_url TEXT DEFAULT '',
                        orcid_url TEXT DEFAULT '',
                        pinned_contributions TEXT DEFAULT '[]',
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
                    CREATE TABLE IF NOT EXISTS handle_history (
                        old_handle TEXT NOT NULL,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        until TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS account_events (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        event TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS notifications (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        read INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        payload_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS profiles (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        role TEXT NOT NULL DEFAULT 'student',
                        public_profile INTEGER NOT NULL DEFAULT 1,
                        show_institution INTEGER NOT NULL DEFAULT 1,
                        show_credentials INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.commit()
            return

        # SQLite mode
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id),
                    display_name TEXT DEFAULT '',
                    handle TEXT UNIQUE COLLATE NOCASE,
                    handle_changed_at TEXT,
                    location TEXT DEFAULT '',
                    skills TEXT DEFAULT '[]',
                    instagram_url TEXT DEFAULT '',
                    x_url TEXT DEFAULT '',
                    youtube_url TEXT DEFAULT '',
                    scholar_url TEXT DEFAULT '',
                    orcid_url TEXT DEFAULT '',
                    pinned_contributions TEXT DEFAULT '[]',
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
                CREATE TABLE IF NOT EXISTS handle_history (
                    old_handle TEXT NOT NULL,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    until TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    event TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    read INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    role TEXT NOT NULL DEFAULT 'student',
                    public_profile INTEGER NOT NULL DEFAULT 1,
                    show_institution INTEGER NOT NULL DEFAULT 1,
                    show_credentials INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
            """)

            cols = {row[1] for row in conn.execute("PRAGMA table_info(user_profiles)").fetchall()}
            new_cols = {
                "display_name": "TEXT DEFAULT ''",
                "handle": "TEXT",
                "handle_changed_at": "TEXT",
                "location": "TEXT DEFAULT ''",
                "skills": "TEXT DEFAULT '[]'",
                "instagram_url": "TEXT DEFAULT ''",
                "x_url": "TEXT DEFAULT ''",
                "youtube_url": "TEXT DEFAULT ''",
                "scholar_url": "TEXT DEFAULT ''",
                "orcid_url": "TEXT DEFAULT ''",
                "pinned_contributions": "TEXT DEFAULT '[]'",
            }
            for col_name, col_type in new_cols.items():
                if col_name not in cols:
                    try:
                        conn.execute(f"ALTER TABLE user_profiles ADD COLUMN {col_name} {col_type}")
                    except Exception:
                        pass
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_profiles_handle ON user_profiles(lower(handle))")
    finally:
        conn.close()


def generate_default_handle(user_id: int, name: str) -> str:
    """Generate a clean, reserved-safe unique handle for a user."""
    base = re.sub(r"[^a-z0-9_]", "", (name or "").strip().lower().replace(" ", "_"))
    if len(base) < 3:
        base = f"user_{user_id}"
    elif len(base) > 20:
        base = base[:20]
    if base in RESERVED_HANDLES:
        base = f"{base}_{user_id}"

    candidate = base
    suffix = 1
    while True:
        existing = query_one(
            "SELECT user_id FROM user_profiles WHERE lower(handle) = ? AND user_id != ?",
            (candidate, user_id),
        )
        if not existing:
            return candidate
        candidate = f"{base[:18]}_{suffix}"
        suffix += 1


def get_or_create_profile(user_id: int) -> Dict[str, Any]:
    """Retrieve user_profiles row or create default if not present."""
    ensure_user_profiles_table()
    row = query_one("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    if row:
        d = dict(row)
        if not d.get("handle"):
            user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
            name = user["name"] if user else ""
            h = generate_default_handle(user_id, name)
            disp = d.get("display_name") or name
            execute(
                "UPDATE user_profiles SET handle = ?, display_name = ? WHERE user_id = ?",
                (h, disp, user_id),
            )
            d["handle"] = h
            d["display_name"] = disp
        return d

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    is_seeded = bool(user and user["verification_level"] >= 1 and user["institution"])
    name = user["name"] if user else ""
    h = generate_default_handle(user_id, name)

    execute(
        """
        INSERT OR IGNORE INTO user_profiles
            (user_id, display_name, handle, headline, bio, institution, location, skills,
             github_url, linkedin_url, portfolio_url, instagram_url, x_url, youtube_url, scholar_url, orcid_url,
             pinned_contributions, is_public, show_institution, show_credentials, onboarding_completed, updated_at)
        VALUES (?, ?, ?, '', '', ?, '', '[]', '', '', '', '', '', '', '', '', '[]', 1, 1, 1, ?, ?)
        """,
        (user_id, name, h, user["institution"] if user else "", 1 if is_seeded else 0, now),
    )
    row = query_one("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    return dict(row) if row else {
        "user_id": user_id,
        "display_name": name,
        "handle": h,
        "headline": "",
        "bio": "",
        "location": "",
        "skills": "[]",
        "institution": user["institution"] if user else "",
        "github_url": "",
        "linkedin_url": "",
        "portfolio_url": "",
        "instagram_url": "",
        "x_url": "",
        "youtube_url": "",
        "scholar_url": "",
        "orcid_url": "",
        "pinned_contributions": "[]",
        "is_public": 1,
        "show_institution": 1,
        "show_credentials": 1,
        "onboarding_completed": 1 if is_seeded else 0,
    }


get_profile = get_or_create_profile


def complete_onboarding(user_id: int, role: str, institution: str = "") -> Dict[str, Any]:
    """Assign role after Google sign-in. Admin is NEVER allowed to be self-selected."""
    role = (role or "").strip().lower()
    if role == "admin":
        raise ValueError("Admin role cannot be self-selected.")
    if role not in ("student", "expert", "sponsor"):
        raise ValueError(f"Invalid role: {role}. Must be student, expert, or sponsor.")

    v_level = 1 if role == "student" else 1
    ensure_user_profiles_table()

    execute(
        "UPDATE users SET role = ?, verification_level = ?, institution = ? WHERE id = ?",
        (role, v_level, institution.strip(), user_id),
    )
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
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


def validate_url(field: str, value: Optional[str]) -> str:
    """Validate external profile links: HTTPS only, host allowlist, max 200 chars."""
    if not value or not str(value).strip():
        return ""
    val = str(value).strip()
    if len(val) > 200:
        raise ValueError(f"URL exceeds 200 characters (length: {len(val)})")

    parsed = urllib.parse.urlparse(val)
    if parsed.scheme.lower() != "https":
        raise ValueError(f"Invalid URL scheme '{parsed.scheme}': only https:// URLs are allowed.")

    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("Invalid URL: missing host.")

    allowlists = {
        "github_url": {"github.com", "www.github.com"},
        "linkedin_url": {"linkedin.com", "www.linkedin.com"},
        "instagram_url": {"instagram.com", "www.instagram.com"},
        "x_url": {"x.com", "www.x.com", "twitter.com", "www.twitter.com"},
        "youtube_url": {"youtube.com", "www.youtube.com", "youtu.be"},
        "scholar_url": {"scholar.google.com"},
        "orcid_url": {"orcid.org", "www.orcid.org"},
    }

    if field in allowlists:
        allowed = allowlists[field]
        if host not in allowed:
            raise ValueError(f"Host '{host}' is not permitted for {field}. Allowed: {', '.join(sorted(allowed))}")
    elif field == "portfolio_url":
        if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost"):
            raise ValueError("Localhost is not allowed for portfolio URL.")
        try:
            ipaddress.ip_address(host)
            raise ValueError("IP addresses are not allowed for portfolio URL.")
        except ValueError as e:
            if "not allowed" in str(e):
                raise
            pass
        if "." not in host:
            raise ValueError("Invalid domain name for portfolio URL.")

    return val


def validate_handle(handle: str, current_user_id: Optional[int] = None) -> str:
    """Validate user handle: 3-24 chars, a-z0-9_, non-reserved, unique."""
    if not handle or not isinstance(handle, str):
        raise ValueError("Handle is required.")
    h = handle.strip().lower()
    if not re.match(r"^[a-z0-9_]{3,24}$", h):
        raise ValueError("Handle must be 3-24 characters containing only lowercase letters, numbers, and underscores.")
    if h in RESERVED_HANDLES:
        raise ValueError(f"'{h}' is a reserved system handle.")

    ensure_user_profiles_table()
    row = query_one(
        "SELECT user_id FROM user_profiles WHERE lower(handle) = ? AND user_id != ?",
        (h, current_user_id or 0),
    )
    if row:
        raise ValueError(f"Handle '{h}' is already taken.")

    hist = query_one(
        "SELECT user_id FROM handle_history WHERE lower(old_handle) = ? AND user_id != ? AND until > datetime('now')",
        (h, current_user_id or 0),
    )
    if hist:
        raise ValueError(f"Handle '{h}' was recently used by another account and is temporarily reserved.")

    return h


def record_account_event(user_id: int, event: str) -> None:
    """Record an audit trail event without PII or tokens."""
    ensure_user_profiles_table()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    execute(
        "INSERT INTO account_events (user_id, event, created_at) VALUES (?, ?, ?)",
        (user_id, event, now_iso),
    )


def update_handle(user_id: int, new_handle: str, auth_at: Optional[str] = None) -> str:
    """Update user handle with fresh-login check, 14-day cooldown, and 30-day alias history."""
    if not auth_at:
        raise ValueError("Fresh login within the last 10 minutes is required to change handle.")
    try:
        dt = datetime.datetime.fromisoformat(auth_at.replace("Z", "+00:00"))
        if datetime.datetime.now(datetime.timezone.utc) - dt > datetime.timedelta(minutes=10):
            raise ValueError("Login session expired (must be within last 10 minutes). Please re-authenticate.")
    except Exception:
        raise ValueError("Login session expired (must be within last 10 minutes). Please re-authenticate.")

    prof = get_or_create_profile(user_id)
    current_handle = (prof.get("handle") or "").lower()
    val_handle = validate_handle(new_handle, current_user_id=user_id)
    if val_handle == current_handle:
        return val_handle

    changed_at = prof.get("handle_changed_at")
    if changed_at:
        try:
            cdt = datetime.datetime.fromisoformat(changed_at.replace("Z", "+00:00"))
            if datetime.datetime.now(datetime.timezone.utc) - cdt < datetime.timedelta(days=14):
                raise ValueError("Handle can only be changed once every 14 days.")
        except ValueError as ve:
            if "14 days" in str(ve):
                raise
            pass

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    until_iso = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)).isoformat()

    if current_handle:
        execute(
            "INSERT INTO handle_history (old_handle, user_id, until) VALUES (?, ?, ?)",
            (current_handle, user_id, until_iso),
        )

    execute(
        "UPDATE user_profiles SET handle = ?, handle_changed_at = ?, updated_at = ? WHERE user_id = ?",
        (val_handle, now_iso, now_iso, user_id),
    )
    record_account_event(user_id, "handle_change")
    return val_handle


def get_profile_by_handle(handle_or_id: str) -> Optional[Dict[str, Any]]:
    """Look up a user profile by current handle, previous handle alias, or user_id."""
    ensure_user_profiles_table()
    h = str(handle_or_id).strip().lower()

    # 1. By active handle
    row = query_one("SELECT * FROM user_profiles WHERE lower(handle) = ?", (h,))
    if row:
        return dict(row)

    # 2. By redirect history
    hist = query_one(
        "SELECT user_id FROM handle_history WHERE lower(old_handle) = ? AND until > datetime('now')",
        (h,),
    )
    if hist:
        r2 = query_one("SELECT * FROM user_profiles WHERE user_id = ?", (hist["user_id"],))
        if r2:
            d = dict(r2)
            d["_redirect_from"] = h
            return d

    # 3. Numeric ID fallback
    if h.isdigit():
        r3 = query_one("SELECT * FROM user_profiles WHERE user_id = ?", (int(h),))
        if r3:
            return dict(r3)

    return None


def get_ai_transparency_stats(user_id: int) -> Dict[str, Any]:
    """Calculate the share of human / ai_assisted / agent_generated contributions."""
    rows = query_all(
        "SELECT ai_declaration, count(*) as count FROM contributions WHERE author_id = ? GROUP BY ai_declaration",
        (user_id,),
    )
    counts = {"human": 0, "ai_assisted": 0, "agent_generated": 0}
    total = 0
    for r in rows:
        dec = r["ai_declaration"]
        cnt = r["count"]
        if dec in counts:
            counts[dec] = cnt
            total += cnt

    return {
        "human_pct": round((counts["human"] / total) * 100, 1) if total > 0 else 0.0,
        "ai_assisted_pct": round((counts["ai_assisted"] / total) * 100, 1) if total > 0 else 0.0,
        "agent_generated_pct": round((counts["agent_generated"] / total) * 100, 1) if total > 0 else 0.0,
        "human_count": counts["human"],
        "ai_assisted_count": counts["ai_assisted"],
        "agent_generated_count": counts["agent_generated"],
        "total": total,
    }


def get_profile_completeness(prof: Dict[str, Any]) -> int:
    """Calculate profile completeness meter percentage (settings only)."""
    score = 0
    if prof.get("display_name") or prof.get("headline"):
        score += 20
    if prof.get("handle"):
        score += 20
    if prof.get("bio"):
        score += 20
    if prof.get("location") or prof.get("institution"):
        score += 15
    links = [
        "github_url", "linkedin_url", "portfolio_url", "instagram_url",
        "x_url", "youtube_url", "scholar_url", "orcid_url",
    ]
    if any(prof.get(k) for k in links):
        score += 15
    try:
        sk = json.loads(prof.get("skills") or "[]")
        if sk:
            score += 10
    except Exception:
        pass
    return min(100, score)


def export_user_data(user_id: int) -> Dict[str, Any]:
    """Export ONLY the authenticated caller's own data as JSON."""
    ensure_user_profiles_table()
    user = query_one(
        "SELECT id, name, email, role, verification_level, institution, is_minor, skills, bio FROM users WHERE id = ?",
        (user_id,),
    )
    prof = get_or_create_profile(user_id)
    conts = query_all(
        "SELECT id, milestone_id, author_id, artefact_title, artefact_text, artefact_hash, ai_declaration, similarity_score, review_status, impact_weight, created_at FROM contributions WHERE author_id = ?",
        (user_id,),
    )
    revs = query_all(
        "SELECT id, contribution_id, reviewer_id, decision, reasons, criteria_ref, created_at FROM reviews WHERE reviewer_id = ?",
        (user_id,),
    )
    creds = query_all(
        "SELECT id, project_id, user_id, kind, issued_at, credential_hash FROM credentials WHERE user_id = ?",
        (user_id,),
    )
    notes = query_all(
        "SELECT id, read, created_at, payload_json FROM notifications WHERE user_id = ?",
        (user_id,),
    )
    events = query_all(
        "SELECT id, event, created_at FROM account_events WHERE user_id = ?",
        (user_id,),
    )

    record_account_event(user_id, "data_export")

    return {
        "user": dict(user) if user else {},
        "profile": prof,
        "contributions": [dict(c) for c in conts],
        "reviews": [dict(r) for r in revs],
        "credentials": [dict(cr) for cr in creds],
        "notifications": [dict(n) for n in notes],
        "account_events": [dict(e) for e in events],
    }


def delete_account(user_id: int, confirmed_handle: str, auth_at: Optional[str] = None) -> None:
    """Anonymize user profile, keeping ledger integrity, blocked by active escrows."""
    if not auth_at:
        raise ValueError("Fresh login within the last 10 minutes is required to delete account.")
    try:
        dt = datetime.datetime.fromisoformat(auth_at.replace("Z", "+00:00"))
        if datetime.datetime.now(datetime.timezone.utc) - dt > datetime.timedelta(minutes=10):
            raise ValueError("Fresh login within the last 10 minutes is required to delete account.")
    except Exception:
        raise ValueError("Fresh login within the last 10 minutes is required to delete account.")

    prof = get_or_create_profile(user_id)
    curr_handle = (prof.get("handle") or "").strip().lower()
    if confirmed_handle.strip().lower() != curr_handle:
        raise ValueError("Confirmed handle does not match your active handle.")

    active_escrows = query_all(
        """
        SELECT e.id FROM escrows e
        JOIN milestones m ON m.id = e.milestone_id
        JOIN projects p ON p.id = m.project_id
        WHERE (p.sponsor_id = ? OR m.id IN (SELECT milestone_id FROM contributions WHERE author_id = ?))
          AND e.state NOT IN ('released', 'refunded')
        """,
        (user_id, user_id),
    )
    if active_escrows:
        raise ValueError("Active escrow obligations pending. Cannot delete account while escrows are unsettled.")

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    execute(
        """
        UPDATE user_profiles SET
            display_name = 'Deleted User',
            handle = NULL,
            headline = '',
            bio = '',
            location = '',
            skills = '[]',
            instagram_url = '',
            x_url = '',
            youtube_url = '',
            scholar_url = '',
            orcid_url = '',
            github_url = '',
            linkedin_url = '',
            portfolio_url = '',
            pinned_contributions = '[]',
            is_public = 0,
            updated_at = ?
        WHERE user_id = ?
        """,
        (now_iso, user_id),
    )
    execute(
        "UPDATE users SET name = 'Deleted User', email = ?, bio = '', institution = '', skills = '[]' WHERE id = ?",
        (f"deleted_{user_id}@critx.local", user_id),
    )
    record_account_event(user_id, "account_deleted")


def get_unread_notification_count(user_id: int) -> int:
    """Return number of unread notifications for a user."""
    ensure_user_profiles_table()
    row = query_one(
        "SELECT count(*) as count FROM notifications WHERE user_id = ? AND read = 0",
        (user_id,),
    )
    return int(row["count"]) if row else 0


def get_user_notifications(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve notifications for user."""
    ensure_user_profiles_table()
    rows = query_all(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    )
    return [dict(r) for r in rows]


def add_notification(user_id: int, payload: Dict[str, Any]) -> int:
    """Create a new notification row."""
    ensure_user_profiles_table()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return execute(
        "INSERT INTO notifications (user_id, read, created_at, payload_json) VALUES (?, 0, ?, ?)",
        (user_id, now_iso, json.dumps(payload)),
    )


def mark_notifications_read(user_id: int) -> None:
    """Mark all unread notifications as read."""
    ensure_user_profiles_table()
    execute("UPDATE notifications SET read = 1 WHERE user_id = ? AND read = 0", (user_id,))


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
    display_name: str = "",
    location: str = "",
    instagram_url: str = "",
    x_url: str = "",
    youtube_url: str = "",
    scholar_url: str = "",
    orcid_url: str = "",
    pinned_contributions: str = "[]",
) -> None:
    """Save extended profile fields & privacy toggles."""
    skills_list: List[str] = []
    if skills_raw:
        skills_list = [s.strip().lower() for s in skills_raw.replace(";", ",").split(",") if s.strip()]

    # Validate URLs
    v_github = validate_url("github_url", github_url)
    v_linkedin = validate_url("linkedin_url", linkedin_url)
    v_portfolio = validate_url("portfolio_url", portfolio_url)
    v_instagram = validate_url("instagram_url", instagram_url)
    v_x = validate_url("x_url", x_url)
    v_youtube = validate_url("youtube_url", youtube_url)
    v_scholar = validate_url("scholar_url", scholar_url)
    v_orcid = validate_url("orcid_url", orcid_url)

    # Validate pinned contributions (max 3 JSON list)
    pinned_list = []
    try:
        if isinstance(pinned_contributions, str):
            pinned_list = json.loads(pinned_contributions or "[]")
        elif isinstance(pinned_contributions, list):
            pinned_list = pinned_contributions
    except Exception:
        pinned_list = []
    pinned_list = [int(x) for x in pinned_list[:3] if str(x).isdigit()]

    disp = display_name.strip() if display_name else name.strip()

    execute(
        "UPDATE users SET name = ?, bio = ?, institution = ?, skills = ? WHERE id = ?",
        (name.strip(), bio.strip(), institution.strip(), json.dumps(skills_list), user_id),
    )

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    ensure_user_profiles_table()
    execute(
        """
        INSERT INTO user_profiles
            (user_id, display_name, headline, bio, institution, location, skills,
             github_url, linkedin_url, portfolio_url, instagram_url, x_url, youtube_url, scholar_url, orcid_url,
             pinned_contributions, is_public, show_institution, show_credentials, onboarding_completed, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            display_name = excluded.display_name,
            headline = excluded.headline,
            bio = excluded.bio,
            institution = excluded.institution,
            location = excluded.location,
            skills = excluded.skills,
            github_url = excluded.github_url,
            linkedin_url = excluded.linkedin_url,
            portfolio_url = excluded.portfolio_url,
            instagram_url = excluded.instagram_url,
            x_url = excluded.x_url,
            youtube_url = excluded.youtube_url,
            scholar_url = excluded.scholar_url,
            orcid_url = excluded.orcid_url,
            pinned_contributions = excluded.pinned_contributions,
            is_public = excluded.is_public,
            show_institution = excluded.show_institution,
            show_credentials = excluded.show_credentials,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            disp,
            headline.strip(),
            bio.strip(),
            institution.strip(),
            location.strip(),
            json.dumps(skills_list),
            v_github,
            v_linkedin,
            v_portfolio,
            v_instagram,
            v_x,
            v_youtube,
            v_scholar,
            v_orcid,
            json.dumps(pinned_list),
            1 if is_public else 0,
            1 if show_institution else 0,
            1 if show_credentials else 0,
            now,
        ),
    )
    record_account_event(user_id, "profile_update")
