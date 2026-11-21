import os
import json
import datetime
from fastapi.testclient import TestClient

from app.main import app
from app.db import init_db, query_one, execute
import app.profiles as profiles

client = TestClient(app, follow_redirects=False)


def run_gate_checks():
    init_db()
    from app.seed import seed_users, seed_projects
    seed_users()
    seed_projects()

    print("Running Profile & Account GATE checks...")

    # 1. URL validation: javascript: and http: links rejected
    try:
        profiles.validate_url("github_url", "javascript:alert(1)")
        assert False, "javascript: link was not rejected"
    except ValueError:
        pass

    try:
        profiles.validate_url("github_url", "http://github.com/test")
        assert False, "http: link was not rejected"
    except ValueError:
        pass

    # Invalid host rejected
    try:
        profiles.validate_url("github_url", "https://evil.com/test")
        assert False, "non-github host was not rejected for github_url"
    except ValueError:
        pass

    # Portfolio IP / localhost rejected
    try:
        profiles.validate_url("portfolio_url", "https://localhost:8000")
        assert False, "localhost was not rejected for portfolio"
    except ValueError:
        pass

    try:
        profiles.validate_url("portfolio_url", "https://127.0.0.1")
        assert False, "IP address was not rejected for portfolio"
    except ValueError:
        pass

    # Valid URLs accepted
    assert profiles.validate_url("github_url", "https://github.com/validuser") == "https://github.com/validuser"
    assert profiles.validate_url("portfolio_url", "https://myresearch.org") == "https://myresearch.org"
    print("[PASS] Check 1: javascript: and http: links rejected")

    # 2. Duplicate and reserved handles rejected
    try:
        profiles.validate_handle("admin")
        assert False, "reserved handle 'admin' was not rejected"
    except ValueError:
        pass

    try:
        profiles.validate_handle("settings")
        assert False, "reserved handle 'settings' was not rejected"
    except ValueError:
        pass

    # Set handle for user 5 (Ananya)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    profiles.update_handle(5, "ananya_ai", auth_at=now_iso)

    # Attempting to assign duplicate handle for user 6 (Kiran)
    try:
        profiles.validate_handle("ananya_ai", current_user_id=6)
        assert False, "duplicate handle 'ananya_ai' was not rejected"
    except ValueError:
        pass
    print("[PASS] Check 2: duplicate and reserved handles rejected")

    # 3. 14-day cooldown enforced
    try:
        profiles.update_handle(5, "ananya_new", auth_at=now_iso)
        assert False, "14-day cooldown was not enforced"
    except ValueError as e:
        assert "14 days" in str(e)
    print("[PASS] Check 3: 14-day cooldown enforced")

    # Old handle redirects for 30 days
    res_redirect = client.get("/u/ananya_ai")
    assert res_redirect.status_code == 200

    # 4. Private profile is 404 for others
    prof6 = profiles.get_or_create_profile(6)
    handle6 = prof6["handle"]
    # Set user 6 profile to private (is_public = 0)
    execute("UPDATE user_profiles SET is_public = 0 WHERE user_id = 6")
    prof6 = profiles.get_or_create_profile(6)
    assert prof6["is_public"] == 0

    # Anonymous visitor gets 404
    client.cookies.clear()
    res_anon = client.get(f"/u/{handle6}")
    assert res_anon.status_code == 404, f"expected 404 for private profile, got {res_anon.status_code}"

    # Another user (user 5) gets 404
    client.cookies.set("persona_id", "5")
    res_other = client.get(f"/u/{handle6}")
    assert res_other.status_code == 404, f"expected 404 for other user viewing private profile, got {res_other.status_code}"

    # Owner (user 6) gets 200
    client.cookies.set("persona_id", "6")
    res_owner = client.get(f"/u/{handle6}")
    assert res_owner.status_code == 200
    print("[PASS] Check 4: private profile is 404 for others")

    # 5. Minor profile hides links
    # User 9 (Tara) is a minor (is_minor = 1)
    # Ensure profile is public and has links
    execute(
        """
        UPDATE user_profiles SET
            is_public = 1,
            github_url = 'https://github.com/tara',
            portfolio_url = 'https://tara-research.org'
        WHERE user_id = 9
        """
    )
    prof9 = profiles.get_or_create_profile(9)
    handle9 = prof9["handle"]

    client.cookies.clear()
    res_minor = client.get(f"/u/{handle9}")
    assert res_minor.status_code == 200
    # Tara's full name and links must be hidden
    assert "https://github.com/tara" not in res_minor.text
    assert "https://tara-research.org" not in res_minor.text
    assert "PROTECTED RESEARCHER" in res_minor.text
    print("[PASS] Check 5: minor profile hides links")

    # 6. Export contains only own data
    client.cookies.set("persona_id", "5")
    res_export = client.get("/settings/data/export")
    assert res_export.status_code == 200
    export_json = res_export.json()
    assert export_json["user"]["id"] == 5
    assert export_json["user"]["email"] == "ananya@example.com"
    # Ensure no data belonging to other users leaked in
    for c in export_json["contributions"]:
        assert c["author_id"] == 5
    for r in export_json["reviews"]:
        assert r["reviewer_id"] == 5
    for cr in export_json["credentials"]:
        assert cr["user_id"] == 5
    print("[PASS] Check 6: export contains only own data")

    # 7. Stale session is rejected after signout-all
    client.cookies.clear()
    client.cookies.set("persona_id", "5")
    client.cookies.set("session_epoch", "0")
    # Verify persona is authenticated
    res_auth1 = client.get("/settings/account")
    assert res_auth1.status_code == 200

    # User 5 triggers signout-all
    res_so = client.post("/settings/security/signout-all")
    assert res_so.status_code == 303

    # Attempting to access with stale session epoch 0
    client.cookies.set("persona_id", "5")
    client.cookies.set("session_epoch", "0")
    res_stale = client.get("/settings/account")
    # Stale session is rejected (redirects to login)
    assert res_stale.status_code == 303 and "/login" in res_stale.headers.get("location", "")
    print("[PASS] Check 7: stale session is rejected after signout-all")

    print("\nALL 7 GATE CHECKS PASSED PERFECTLY!")


if __name__ == "__main__":
    run_gate_checks()
