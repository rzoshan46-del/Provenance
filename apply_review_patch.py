"""
apply_review_patch.py — wires the project review queue and admin console into the app.

Run it ONCE from the project root (the folder that contains `app/`):
    python apply_review_patch.py

What it changes (all small, all checked before anything is written):
  app/main.py              4 edits: install the review module, hide unreviewed projects from
                           /projects, send new web-form projects to review, optional API gate
  app/templates/base.html  2 nav links ("Review" for admins, "My submissions" for sponsors)

Safe to run twice. Keeps Windows (CRLF) or Linux (LF) line endings. If any edit cannot be
applied, NOTHING is changed and it tells you which one. Backups: *.bak_review
"""
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "app" / "main.py"
BASE = ROOT / "app" / "templates" / "base.html"


def nl(data: bytes) -> bytes:
    return b"\r\n" if b"\r\n" in data else b"\n"


def patch_main(data: bytes):
    notes = []
    n = nl(data)

    # 1) install the module (after the certificate lines if present, else after the demo_mode line)
    if b"_install_reviews(app, templates)" in data:
        notes.append("main.py: review module already installed, skipped")
    else:
        anchors = [
            b"app.include_router(_build_cert_router(templates))",
            b'templates.env.globals["demo_mode"] = _ledger_mod.demo_mode',
        ]
        anchor = next((a for a in anchors if data.count(a) == 1), None)
        if anchor is None:
            raise SystemExit(
                "ERROR: could not find the line\n  " + anchors[0].decode()
                + "\n(or\n  " + anchors[1].decode() + "\n) exactly once in app/main.py. Nothing was changed."
            )
        block = (
            n
            + b"# Project review queue + admin console (app/reviews.py, app/admin_console.py)" + n
            + b"from app.reviews import (" + n
            + b"    filter_listing as _filter_review_listing," + n
            + b"    install as _install_reviews," + n
            + b"    mark_pending as _mark_pending," + n
            + b"    mark_pending_api as _mark_pending_api," + n
            + b")" + n
            + b"_install_reviews(app, templates)"
        )
        data = data.replace(anchor, anchor + block, 1)
        notes.append("main.py: installed review module")

    # 2) hide not-yet-approved projects from the public list
    if b"_filter_review_listing(_project_list_rows(user), user)" in data:
        notes.append("main.py: project list filter already applied, skipped")
    else:
        anchor = b"projects = _project_list_rows(user)"
        if data.count(anchor) != 1:
            raise SystemExit(
                "ERROR: could not find the line\n  " + anchor.decode()
                + "\nexactly once in app/main.py. Nothing was changed."
            )
        data = data.replace(
            anchor, b"projects = _filter_review_listing(_project_list_rows(user), user)", 1
        )
        notes.append("main.py: project list now hides unreviewed projects")

    # 3) web-form submissions go to the review queue
    if b'_mark_pending(project_id, sponsor, "form")' in data:
        notes.append("main.py: web form hook already applied, skipped")
    else:
        pattern = re.compile(
            rb'(?P<i>[ \t]+)project_id = create_project\(sponsor, form_data\)(?P<nl>\r?\n)'
            rb'(?P=i)return RedirectResponse\(url=f"/projects/\{project_id\}", status_code=303\)'
        )
        matches = pattern.findall(data)
        if len(matches) != 1:
            raise SystemExit(
                "ERROR: could not find the 'project_id = create_project(sponsor, form_data)' lines followed by "
                "the redirect exactly once in app/main.py. Nothing was changed. Use the manual steps."
            )

        def repl(m):
            i, nlc = m.group("i"), m.group("nl")
            return (
                i + b"project_id = create_project(sponsor, form_data)" + nlc
                + i + b'_mark_pending(project_id, sponsor, "form")' + nlc
                + i + b'return RedirectResponse(url=f"/review?submitted={project_id}", status_code=303)'
            )

        data = pattern.sub(repl, data, count=1)
        notes.append("main.py: new web-form projects now go to review")

    # 4) optional gate for POST /api/projects (only active when REQUIRE_PROJECT_REVIEW=1)
    if b"_mark_pending_api(project_id, user)" in data:
        notes.append("main.py: API hook already applied, skipped")
    else:
        pattern = re.compile(rb"(?P<i>[ \t]+)project_id = create_project\(user, fields\)(?P<nl>\r?\n)")
        if len(pattern.findall(data)) != 1:
            raise SystemExit(
                "ERROR: could not find the line 'project_id = create_project(user, fields)' exactly once "
                "in app/main.py. Nothing was changed. Use the manual steps."
            )
        data = pattern.sub(
            lambda m: m.group("i") + b"project_id = create_project(user, fields)" + m.group("nl")
            + m.group("i") + b"_mark_pending_api(project_id, user)" + m.group("nl"),
            data,
            count=1,
        )
        notes.append("main.py: API gate hook added (off unless REQUIRE_PROJECT_REVIEW=1)")
    return data, notes


def patch_base(data: bytes):
    notes = []
    n = nl(data)

    if b'href="/review" class="nav-link">Review<' in data:
        notes.append("base.html: admin Review link already present, skipped")
    else:
        anchor = b'<a href="/admin" class="nav-link">Admin</a>'
        if data.count(anchor) != 1:
            raise SystemExit(
                "ERROR: could not find the Admin nav link exactly once in app/templates/base.html. "
                "Nothing was changed."
            )
        data = data.replace(
            anchor,
            b'<a href="/review" class="nav-link">Review</a>' + n + b" " * 12 + anchor,
            1,
        )
        notes.append("base.html: added Review link for admins")

    if b"My submissions</a>" in data:
        notes.append("base.html: sponsor link already present, skipped")
    else:
        anchor = b'<a href="/credentials" class="nav-link">Credentials</a>'
        if data.count(anchor) != 1:
            raise SystemExit(
                "ERROR: could not find the Credentials nav link exactly once in app/templates/base.html. "
                "Nothing was changed."
            )
        data = data.replace(
            anchor,
            anchor + n + b" " * 12
            + b"{% if user and user.role == 'sponsor' %}<a href=\"/review\" class=\"nav-link\">My submissions</a>{% endif %}",
            1,
        )
        notes.append("base.html: added My submissions link for sponsors")
    return data, notes


def main() -> None:
    needed = [
        MAIN,
        BASE,
        ROOT / "app" / "reviews.py",
        ROOT / "app" / "admin_console.py",
        ROOT / "app" / "templates" / "review.html",
        ROOT / "app" / "templates" / "admin_console.html",
    ]
    missing = [str(p.relative_to(ROOT)) for p in needed if not p.exists()]
    if missing:
        raise SystemExit(
            "ERROR: these files are missing, so nothing was changed:\n  "
            + "\n  ".join(missing)
            + "\nRun this script from the project root and copy the new files in first."
        )

    new_main, notes1 = patch_main(MAIN.read_bytes())
    new_base, notes2 = patch_base(BASE.read_bytes())

    # All edits are valid: write them (with backups).
    for path, content in ((MAIN, new_main), (BASE, new_base)):
        if content != path.read_bytes():
            bak = path.with_name(path.name + ".bak_review")
            if not bak.exists():
                shutil.copy2(path, bak)
            path.write_bytes(content)

    for line in notes1 + notes2:
        print(line)
    print("\nDone. Next: python smoke_reviews.py   then   python smoke.py")


if __name__ == "__main__":
    sys.exit(main())
