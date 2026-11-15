"""
smoke_certificates.py — checks for the certificate / QR / verify feature.

Run from the project root:   python smoke_certificates.py
Uses its own throw-away database (data/smoke_cert.db); your real data is not touched.
"""
import os
import re
import sys
from pathlib import Path

os.environ["PROVENANCE_LLM"] = "canned"
os.environ["PROVENANCE_DB"] = "data/smoke_cert.db"
os.environ.setdefault("PROVENANCE_DEMO", "1")
os.environ.pop("PROVENANCE_DATABASE_URL", None)

for suffix in ["", "-journal", "-shm", "-wal"]:
    f = Path("data/smoke_cert.db" + suffix)
    if f.exists():
        try:
            f.unlink()
        except Exception:
            pass

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db import init_db, query_all, query_one  # noqa: E402
from app.certificates import _display_name, HASH_RE  # noqa: E402
import app.ledger as ledger  # noqa: E402
import app.story as story  # noqa: E402

PASSED = True


def check(num, description, condition, err=""):
    global PASSED
    if condition:
        print(f"[PASS] ({num}) {description}")
    else:
        print(f"[FAIL] ({num}) {description}" + (f": {err}" if err else ""))
        PASSED = False


def main():
    anon = TestClient(app, follow_redirects=True)

    # Fresh database with the demo personas and projects.
    init_db()
    if anon.post("/api/demo/reset").status_code != 200:
        print("Could not reset the demo database (is PROVENANCE_DEMO set to 0?)")
        return False

    # Build realistic data with the project's own story mode (post -> ... -> accept).
    for key in story.STEP_KEYS[: story.STEP_KEYS.index("accept") + 1]:
        res = anon.post(f"/api/story/run/{key}")
        if res.status_code != 200:
            print(f"Story step '{key}' failed: {res.status_code} {res.text[:200]}")
            return False

    creds = [dict(r) for r in query_all("SELECT * FROM credentials ORDER BY id ASC")]
    check(1, "story mode issued at least one credential", len(creds) >= 1, f"found {len(creds)}")
    if not creds:
        return False
    cred = creds[0]
    h = cred["credential_hash"]
    holder = query_one("SELECT * FROM users WHERE id = ?", (cred["user_id"],))
    all_emails = [r["email"] for r in query_all("SELECT email FROM users") if r["email"]]

    # --- public verify page ---
    r = anon.get(f"/verify/{h}")
    check(2, "GET /verify/<hash> is public (no login) and returns 200", r.status_code == 200, str(r.status_code))
    check(3, "page shows the holder's name, 'Verified' and the QR image link",
          holder["name"] in r.text and "Verified" in r.text and f"/certificate/{h}/qr.svg" in r.text)
    check(4, "page contains Open Graph tags for link previews", 'property="og:title"' in r.text)
    check(5, "page never shows any user's email address",
          not any(e in r.text for e in all_emails) and "mailto:" not in r.text
          and "@" not in re.sub(r"<[^>]+>", "", re.sub(r"(?is)<(style|script).*?</\1>", "", r.text)))
    check(6, "authorship declaration section is present when there are approved contributions",
          ("Authorship declaration" in r.text) or ("Approved contributions</div><div class=\"v\">0" in r.text))

    # --- QR ---
    q = anon.get(f"/certificate/{h}/qr.svg")
    check(7, "QR endpoint returns an SVG image", q.status_code == 200 and q.headers.get("content-type", "").startswith("image/svg+xml") and b"<svg" in q.content)
    check(8, "QR for an unknown (but well-formed) hash returns 404", anon.get(f"/certificate/{'a'*64}/qr.svg").status_code == 404)

    # --- print view ---
    p = anon.get(f"/certificate/{h}")
    check(9, "print-ready certificate returns 200 and contains the QR and certificate id",
          p.status_code == 200 and f"/certificate/{h}/qr.svg" in p.text and "PRV-" in p.text)

    # --- JSON ---
    j = anon.get(f"/api/verify/{h}")
    jd = j.json() if j.status_code == 200 else {}
    check(10, "JSON API says valid with a ledger entry id and an intact chain",
          j.status_code == 200 and jd.get("valid") is True and jd.get("ledger", {}).get("entry_id") and jd.get("chain_ok") is True)
    check(11, "JSON API does not leak emails", not any(e in j.text for e in all_emails))

    # --- bad input ---
    check(12, "malformed hash gives 404 (page)", anon.get("/verify/not-a-hash").status_code == 404)
    check(13, "unknown hash gives 404 (page and JSON)",
          anon.get(f"/verify/{'b'*64}").status_code == 404 and anon.get(f"/api/verify/{'b'*64}").status_code == 404)
    check(14, "SQL-style input in the hash is rejected safely",
          anon.get("/verify/' OR 1=1 --").status_code == 404 and anon.get("/api/verify/%27%20OR%201%3D1%20--").status_code == 404)
    check(15, "hash format check accepts only 64 lowercase hex characters",
          bool(HASH_RE.match(h)) and not HASH_RE.match(h.upper()) and not HASH_RE.match(h[:-1]))

    # --- privacy for minors ---
    check(16, "minors are shown as 'First L.' only", _display_name("Asha Verma", 1) == "Asha V." and _display_name("Asha Verma", 0) == "Asha Verma")

    # --- tamper demo makes the certificate fail, restore fixes it ---
    t = anon.post("/api/ledger/tamper")
    check(17, "ledger tamper demo works", t.status_code == 200, f"{t.status_code} {t.text[:120]}")
    from app import certificates as cert_mod
    cert_mod._chain_cache["v"] = None
    bad = anon.get(f"/api/verify/{h}").json()
    check(18, "after tampering the certificate is NOT reported as valid", bad.get("valid") is False and bad.get("status") == "unverified", str(bad.get("status")))
    check(19, "the page warns 'Could not be verified' while the chain is broken", "Could not be verified" in anon.get(f"/verify/{h}").text)
    rs = anon.post("/api/ledger/restore")
    check(20, "ledger restore works", rs.status_code == 200, f"{rs.status_code} {rs.text[:120]}")
    cert_mod._chain_cache["v"] = None
    check(21, "after restore the certificate is valid again", anon.get(f"/api/verify/{h}").json().get("status") == "valid")

    # --- revocation ---
    student = TestClient(app, follow_redirects=True)
    student.cookies.set("persona_id", str(holder["id"]))
    rv = student.post(f"/api/credentials/{h}/revoke", json={"reason_code": "error"})
    check(22, "a non-admin cannot revoke (403)", rv.status_code == 403, str(rv.status_code))
    check(23, "anonymous cannot revoke (403)", anon.post(f"/api/credentials/{h}/revoke", json={"reason_code": "error"}).status_code == 403)

    admin_row = query_one("SELECT id FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1")
    admin = TestClient(app, follow_redirects=True)
    admin.cookies.set("persona_id", str(admin_row["id"]))
    check(24, "admin sees the revoke control on the verify page", 'id="btn-revoke"' in admin.get(f"/verify/{h}").text and 'id="btn-revoke"' not in anon.get(f"/verify/{h}").text)
    check(25, "an invalid reason code is rejected (400)", admin.post(f"/api/credentials/{h}/revoke", json={"reason_code": "bogus"}).status_code == 400)
    ok = admin.post(f"/api/credentials/{h}/revoke", json={"reason_code": "plagiarism", "note": "demo"})
    check(26, "admin can revoke (200)", ok.status_code == 200 and ok.json().get("status") == "revoked", f"{ok.status_code} {ok.text[:120]}")
    check(27, "revoking twice gives 409", admin.post(f"/api/credentials/{h}/revoke", json={"reason_code": "error"}).status_code == 409)
    rp = anon.get(f"/verify/{h}")
    check(28, "verify page now shows REVOKED and the JSON says not valid", "Revoked" in rp.text and anon.get(f"/api/verify/{h}").json().get("valid") is False)
    check(29, "print view is stamped REVOKED", "REVOKED" in anon.get(f"/certificate/{h}").text)
    entry = query_one("SELECT * FROM ledger_entries WHERE action = 'credential_revoked' ORDER BY id DESC LIMIT 1")
    check(30, "a credential_revoked ledger entry exists and holds no free text", bool(entry) and "demo" not in entry["payload_json"] and h in entry["payload_json"])
    check(31, "ledger chain is still intact after revoking", ledger.verify().get("ok") is True)

    # --- existing features still work ---
    check(32, "existing /api/credentials/<hash> still works", anon.get(f"/api/credentials/{h}").status_code == 200)
    owner = TestClient(app, follow_redirects=True)
    owner.cookies.set("persona_id", str(cred["user_id"]))
    page = owner.get("/credentials")
    check(33, "the credentials page shows the new 'Certificate & QR' link", page.status_code == 200 and f"/verify/{h}" in page.text)
    return PASSED


if __name__ == "__main__":
    ok = main()
    print("\nALL CERTIFICATE CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
    sys.exit(0 if ok else 1)
