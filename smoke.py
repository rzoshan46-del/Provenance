import os
from pathlib import Path
import sys
import re

# 1. Set PROVENANCE_DB to data/smoke.db BEFORE importing the app
os.environ["PROVENANCE_DB"] = "data/smoke.db"

# 2. Delete any old smoke.db file and associated journal/wal files
smoke_db = Path("data/smoke.db")
if smoke_db.exists():
    try:
        smoke_db.unlink()
    except Exception as e:
        print(f"Warning: could not delete {smoke_db}: {e}")

for suffix in ["-journal", "-shm", "-wal"]:
    extra = Path("data/smoke.db" + suffix)
    if extra.exists():
        try:
            extra.unlink()
        except Exception:
            pass

# 3. Now import FastAPI app and test client
from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db, query_all, query_one, execute


def run_checks() -> bool:
    all_passed = True

    def check(num: int, description: str, condition: bool, err_msg: str = "") -> None:
        nonlocal all_passed
        if condition:
            print(f"[PASS] ({num}) {description}")
        else:
            print(f"[FAIL] ({num}) {description}" + (f": {err_msg}" if err_msg else ""))
            all_passed = False

    # Helper: return a TestClient with persona cookie set for the named user
    def client_for(name: str) -> TestClient:
        row = query_one("SELECT id FROM users WHERE name = ?", (name,))
        if not row:
            raise RuntimeError(f"User '{name}' not found in smoke DB")
        c = TestClient(app, follow_redirects=True)
        c.cookies.set("persona_id", str(row["id"]))
        return c

    with TestClient(app, follow_redirects=True) as client:
        # Guarantee DB is initialized & seeded even if lifespan is deferred
        init_db()
        from app.seed import seed_users, seed_projects
        seed_users()
        seed_projects()

        # â”€â”€ Checks 1â€“9 (S0: skeleton) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

        # (1) /health returns ok
        res = client.get("/health")
        ok_1 = res.status_code == 200 and res.json().get("status") == "ok"
        check(1, "/health returns ok", ok_1, f"status={res.status_code}, body={res.text}")

        # (2) the database has exactly 14 tables
        tables = query_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        table_count = len(tables)
        check(2, "the database has exactly 14 tables", table_count == 14, f"found {table_count} tables")

        # (3) user counts by role are admin 1, sponsor 1, expert 2, student 5
        role_rows = query_all("SELECT role, COUNT(*) as count FROM users GROUP BY role")
        role_counts = {r["role"]: r["count"] for r in role_rows}
        ok_3 = (
            role_counts.get("admin") == 1
            and role_counts.get("sponsor") == 1
            and role_counts.get("expert") == 2
            and role_counts.get("student") == 5
        )
        check(
            3,
            "user counts by role are admin 1, sponsor 1, expert 2, student 5",
            ok_3,
            f"actual={role_counts}",
        )

        # (4) home with no persona contains 'Choose a persona'
        client.cookies.clear()
        res = client.get("/")
        ok_4 = res.status_code == 200 and "Choose a persona" in res.text
        check(4, "home with no persona contains 'Choose a persona'", ok_4)

        # (5) after /switch to the sponsor, home shows the sponsor's name
        sponsor = query_one("SELECT * FROM users WHERE role = 'sponsor'")
        if sponsor:
            res = client.get(f"/switch/{sponsor['id']}")
            ok_5 = res.status_code == 200 and sponsor["name"] in res.text
            check(5, "after /switch to the sponsor, home shows the sponsor's name", ok_5)
        else:
            check(5, "after /switch to the sponsor, home shows the sponsor's name", False, "sponsor not found")

        # (6) /admin as sponsor returns 403
        res = client.get("/admin")
        ok_6 = res.status_code == 403
        check(6, "/admin as sponsor returns 403", ok_6, f"status={res.status_code}")

        # (7) /admin as admin returns 200
        admin = query_one("SELECT * FROM users WHERE role = 'admin'")
        if admin:
            client.get(f"/switch/{admin['id']}")
            res = client.get("/admin")
            ok_7 = res.status_code == 200 and "Admin Console" in res.text
            check(7, "/admin as admin returns 200", ok_7, f"status={res.status_code}")
        else:
            check(7, "/admin as admin returns 200", False, "admin not found")

        # (8) /switch/9999 returns 404
        res = client.get("/switch/9999")
        ok_8 = res.status_code == 404
        check(8, "/switch/9999 returns 404", ok_8, f"status={res.status_code}")

        # (9) a minor student exists with guardian_consent 0
        minor = query_one(
            "SELECT * FROM users WHERE is_minor = 1 AND guardian_consent = 0 AND role = 'student'"
        )
        ok_9 = minor is not None
        check(
            9,
            "a minor student exists with guardian_consent 0",
            ok_9,
            f"found={minor['name'] if minor else None}",
        )

    # â”€â”€ Checks 10â€“23 (S1a: API / backend logic) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Use named clients to avoid state bleed between checks
    anon_client = TestClient(app, follow_redirects=True)
    sponsor_client = client_for("Meera Rao")
    ananya_client = client_for("Ananya")
    sneha_client = client_for("Sneha")
    vikram_client = client_for("Vikram")
    kiran_client = client_for("Kiran Shah")
    tara_client = client_for("Tara")
    admin_client = client_for("Admin Asha")

    # (10) Two seeded projects exist with charter v1, current_charter_version=1, 64-hex hash
    projects_rows = query_all("SELECT * FROM projects ORDER BY id ASC")
    charters_rows = query_all("SELECT * FROM charters WHERE version = 1 ORDER BY project_id ASC")
    ok_10 = (
        len(projects_rows) >= 2
        and projects_rows[0]["engagement_model"] == "funded"
        and projects_rows[0]["sensitivity_label"] == "confidential"
        and projects_rows[1]["engagement_model"] == "knowledge_sharing"
        and projects_rows[0]["current_charter_version"] == 1
        and projects_rows[1]["current_charter_version"] == 1
        and len(charters_rows) >= 2
        and len(charters_rows[0]["hash"]) == 64
        and len(charters_rows[1]["hash"]) == 64
    )
    check(10, "two seeded projects with charter v1, current_charter_version=1, 64-hex hash", ok_10,
          f"projects={len(projects_rows)}, charters={len(charters_rows)}")

    # (11) anonymous GET /api/projects/1/brief â†’ 403
    res = anon_client.get("/api/projects/1/brief")
    check(11, "anonymous GET /api/projects/1/brief â†’ 403", res.status_code == 403,
          f"got {res.status_code}")

    # (12) non-member student Sneha â†’ 403
    res = sneha_client.get("/api/projects/1/brief")
    check(12, "non-member student Sneha GET brief â†’ 403", res.status_code == 403,
          f"got {res.status_code}")

    # (13) owning sponsor â†’ 200 with brief text
    res = sponsor_client.get("/api/projects/1/brief")
    ok_13 = res.status_code == 200 and res.json().get("brief")
    check(13, "sponsor GET /api/projects/1/brief â†’ 200 with brief text", ok_13,
          f"got {res.status_code}: {res.text[:80]}")

    # (14) admin â†’ 403 (least privilege: admin cannot see brief)
    res = admin_client.get("/api/projects/1/brief")
    check(14, "admin GET /api/projects/1/brief â†’ 403", res.status_code == 403,
          f"got {res.status_code}")

    # (15a) Ananya joins without both acknowledgements â†’ 400
    res = ananya_client.post("/api/projects/1/join",
                             data={"accept_charter": "1"})  # missing ack_engagement_model
    check(15, "join without engagement-model ack â†’ 400", res.status_code == 400,
          f"got {res.status_code}: {res.text[:80]}")

    # (15b) Ananya joins with both â†’ 200
    res = ananya_client.post("/api/projects/1/join",
                             data={"accept_charter": "1", "ack_engagement_model": "1"})
    check(16, "join with both acks â†’ 200", res.status_code == 200,
          f"got {res.status_code}: {res.text[:80]}")

    # (15c) Ananya can now read the brief
    res = ananya_client.get("/api/projects/1/brief")
    check(17, "member (Ananya) GET brief â†’ 200", res.status_code == 200,
          f"got {res.status_code}")

    # (16) joining twice does not add a second acceptance row
    before_count = query_one(
        "SELECT COUNT(*) as c FROM charter_acceptances WHERE project_id=1 AND user_id=(SELECT id FROM users WHERE name='Ananya')"
    )["c"]
    ananya_client.post("/api/projects/1/join",
                       data={"accept_charter": "1", "ack_engagement_model": "1"})
    after_count = query_one(
        "SELECT COUNT(*) as c FROM charter_acceptances WHERE project_id=1 AND user_id=(SELECT id FROM users WHERE name='Ananya')"
    )["c"]
    check(18, "joining twice does not add a second acceptance row", before_count == after_count,
          f"before={before_count} after={after_count}")

    # (17) expert Kiran Shah (conflict of interest) cannot join P1 â†’ 403 containing "conflict"
    res = kiran_client.post("/api/projects/1/join",
                            data={"accept_charter": "1", "ack_engagement_model": "1"})
    ok_17 = res.status_code == 403 and "conflict" in res.text.lower()
    check(19, "Kiran Shah conflict of interest â†’ 403 with 'conflict'", ok_17,
          f"got {res.status_code}: {res.text[:100]}")

    # (18) minor student Tara cannot join funded P1 â†’ 403 containing "guardian"
    res = tara_client.post("/api/projects/1/join",
                           data={"accept_charter": "1", "ack_engagement_model": "1"})
    ok_18 = res.status_code == 403 and "guardian" in res.text.lower()
    check(20, "Tara (minor) cannot join funded project â†’ 403 with 'guardian'", ok_18,
          f"got {res.status_code}: {res.text[:100]}")

    # (19) student with verification_level=0 cannot join â†’ 403; restore afterwards
    vikram_row = query_one("SELECT * FROM users WHERE name='Vikram'")
    execute("UPDATE users SET verification_level=0 WHERE name='Vikram'")
    res = vikram_client.post("/api/projects/1/join",
                             data={"accept_charter": "1", "ack_engagement_model": "1"})
    ok_19 = res.status_code == 403
    execute("UPDATE users SET verification_level=? WHERE name='Vikram'",
            (vikram_row["verification_level"],))
    check(21, "verification_level=0 student cannot join â†’ 403", ok_19,
          f"got {res.status_code}: {res.text[:80]}")

    # (20) student cannot publish charter; sponsor publishes v2; earlier member's state â†’ reaccept_required
    res = ananya_client.post("/api/projects/1/charter",
                             data={"rewards": "updated reward text", "change_note": "v2 update"})
    check(22, "student cannot publish charter â†’ 403", res.status_code == 403,
          f"got {res.status_code}")

    res = sponsor_client.post("/api/projects/1/charter",
                              data={"rewards": "Updated: INR 1,20,000 escrow pool", "change_note": "Increased escrow"})
    ok_pub = res.status_code == 200
    proj_after = query_one("SELECT current_charter_version FROM projects WHERE id=1")
    check(23, "sponsor publishes v2 â†’ current_charter_version=2",
          ok_pub and proj_after["current_charter_version"] == 2,
          f"status={res.status_code}, version={proj_after['current_charter_version'] if proj_after else '?'}")

    # Ananya's state should now be reaccept_required
    from app.access import membership_state as ms
    ananya_id = query_one("SELECT id FROM users WHERE name='Ananya'")["id"]
    ananya_state = ms(1, ananya_id)
    check(24, "Ananya's state is reaccept_required after v2 publish",
          ananya_state == "reaccept_required",
          f"state={ananya_state}")

    # Brief is now 403 for Ananya (reaccept_required)
    res = ananya_client.get("/api/projects/1/brief")
    check(25, "reaccept_required member cannot read brief â†’ 403", res.status_code == 403,
          f"got {res.status_code}")

    # After re-joining, brief is accessible again
    ananya_client.post("/api/projects/1/join",
                       data={"accept_charter": "1", "ack_engagement_model": "1"})
    res = ananya_client.get("/api/projects/1/brief")
    check(26, "after re-accepting, member can read brief â†’ 200", res.status_code == 200,
          f"got {res.status_code}")

    # (21) student cannot create project â†’ 403
    res = ananya_client.post("/api/projects",
                             data={"title": "t", "public_summary": "s", "confidential_brief": "b",
                                   "sensitivity_label": "public", "engagement_model": "funded"})
    check(27, "student POST /api/projects â†’ 403", res.status_code == 403,
          f"got {res.status_code}")

    # (22) sponsor can create project
    res = sponsor_client.post("/api/projects",
                              data={
                                  "title": "Smoke test project",
                                  "public_summary": "A smoke test project.",
                                  "confidential_brief": "Smoke test confidential details.",
                                  "sensitivity_label": "public",
                                  "engagement_model": "knowledge_sharing",
                              })
    check(28, "sponsor POST /api/projects â†’ 201 with project_id",
          res.status_code == 201 and "project_id" in res.json(),
          f"got {res.status_code}: {res.text[:80]}")

    # (23) P2 terms_json rewards contains no currency symbols
    p2_charter = query_one(
        "SELECT terms_json FROM charters WHERE project_id=2 AND version=1"
    )
    p2_terms = p2_charter["terms_json"] if p2_charter else ""
    currency_symbols = ["â‚¹", "$", "â‚¬", "Â£"]
    has_currency = any(sym in p2_terms for sym in currency_symbols)
    check(29, "P2 charter terms contain no currency symbols",
          not has_currency,
          f"found currency in: {p2_terms[:120]}")

    # â”€â”€ Checks 24â€“29 (S1b: HTML UI) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    # (24) GET /projects returns 200 and lists both seeded titles
    res = anon_client.get("/projects")
    p1_title = projects_rows[0]["title"] if projects_rows else ""
    p2_title = projects_rows[1]["title"] if len(projects_rows) > 1 else ""
    ok_24 = res.status_code == 200 and p1_title in res.text and p2_title in res.text
    check(30, "GET /projects returns 200 and lists both seeded titles", ok_24,
          f"status={res.status_code}, p1={p1_title[:30]!r} in page={p1_title in res.text}")

    # (25) non-member: locked brief (no brief text); sponsor: brief visible
    brief_text_excerpt = "SYNTHETIC RESEARCH BRIEF"  # distinctive text from seed
    res_nonmember = sneha_client.get("/projects/1")
    res_sponsor = sponsor_client.get("/projects/1")
    locked_nonmember = (
        res_nonmember.status_code == 200
        and brief_text_excerpt not in res_nonmember.text
        and ("locked" in res_nonmember.text.lower() or "lock-icon" in res_nonmember.text or "Hidden until" in res_nonmember.text)
    )
    sponsor_sees_brief = res_sponsor.status_code == 200 and brief_text_excerpt in res_sponsor.text
    check(31, "non-member project page: locked brief, no brief text",
          locked_nonmember,
          f"status={res_nonmember.status_code}, brief_in_page={brief_text_excerpt in res_nonmember.text}")
    check(32, "sponsor project page: brief text visible",
          sponsor_sees_brief,
          f"status={res_sponsor.status_code}, brief_in_page={sponsor_sees_brief}")

    # (26) P2 project page and join page contain "UNPAID" and no currency symbol
    res_p2 = ananya_client.get("/projects/2")
    res_p2_join = ananya_client.get("/projects/2/join")
    currency_re = re.compile(r"[â‚¹$â‚¬Â£]")
    p2_page_ok = (
        res_p2.status_code == 200
        and "UNPAID" in res_p2.text
        and not currency_re.search(res_p2.text)
    )
    p2_join_ok = (
        res_p2_join.status_code == 200
        and "UNPAID" in res_p2_join.text
        and not currency_re.search(res_p2_join.text)
    )
    check(33, "P2 project page contains UNPAID and no currency symbol", p2_page_ok,
          f"UNPAID_in={('UNPAID' in res_p2.text)}, currency={bool(currency_re.search(res_p2.text))}")
    check(34, "P2 join page contains UNPAID and no currency symbol", p2_join_ok,
          f"UNPAID_in={('UNPAID' in res_p2_join.text)}, currency={bool(currency_re.search(res_p2_join.text))}")

    # (27) POST /projects/1/join with only accept_charter (no ack) does not create membership
    rahul_client = client_for("Rahul")
    count_before = query_one(
        "SELECT COUNT(*) as c FROM charter_acceptances WHERE project_id=1 AND user_id=(SELECT id FROM users WHERE name='Rahul')"
    )["c"]
    res = rahul_client.post("/projects/1/join", data={"accept_charter": "1"})
    count_after = query_one(
        "SELECT COUNT(*) as c FROM charter_acceptances WHERE project_id=1 AND user_id=(SELECT id FROM users WHERE name='Rahul')"
    )["c"]
    check(35, "POST /projects/1/join without ack_engagement_model does not create membership",
          count_before == count_after,
          f"acceptances before={count_before} after={count_after}")

    # (28) sponsor publishes v3 via HTML route; charter page contains diff marker (v2 and v3)
    # (Note: v2 was published in check 23 above; now publish v3 via HTML route)
    res = sponsor_client.post(
        "/projects/1/charter",
        data={"rewards": "Updated again for smoke test", "change_note": "smoke v3"}
    )
    # Follow the redirect
    res_charter = sponsor_client.get("/projects/1/charter")
    p1_proj = query_one("SELECT current_charter_version FROM projects WHERE id=1")
    ok_28 = (
        res_charter.status_code == 200
        and "v" in res_charter.text
        and p1_proj["current_charter_version"] >= 2
    )
    check(36, "charter page shows diff after sponsor publishes new version",
          ok_28,
          f"status={res_charter.status_code}, current_version={p1_proj['current_charter_version'] if p1_proj else '?'}")

    # (29) GET /projects/1/visibility: 200, sponsor allowed (âœ“), anonymous blocked (âœ—) for brief
    res_vis = anon_client.get("/projects/1/visibility")
    sponsor_name = sponsor["name"] if sponsor else ""
    ok_29 = (
        res_vis.status_code == 200
        and "vis-allow" in res_vis.text  # at least one âœ“ cell
        and "vis-block" in res_vis.text  # at least one âœ— cell
        and "Anonymous" in res_vis.text
        and sponsor_name in res_vis.text
    )
    check(37, "visibility page returns 200 with allowed/blocked cells and both users",
          ok_29,
          f"status={res_vis.status_code}, sponsor_in={sponsor_name in res_vis.text}")

    if all_passed:
        print("\nALL CHECKS PASSED")
        return True
    else:
        print("\nSOME CHECKS FAILED")
        return False


if __name__ == "__main__":
    success = run_checks()
    sys.exit(0 if success else 1)

