"""
apply_certificate_patch.py — makes the three small edits the certificate feature needs.

Run it ONCE from the project root (the folder that contains `app/`):
    python apply_certificate_patch.py

It is safe to run twice (it skips edits that are already applied), keeps Windows (CRLF)
or Linux (LF) line endings as they are, and saves a backup next to each file it changes
(for example app/main.py.bak_cert).
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(path: Path) -> bytes:
    return path.read_bytes()


def nl(data: bytes) -> bytes:
    return b"\r\n" if b"\r\n" in data else b"\n"


def backup(path: Path) -> None:
    b = path.with_name(path.name + ".bak_cert")
    if not b.exists():
        shutil.copy2(path, b)


def patch_main() -> str:
    path = ROOT / "app" / "main.py"
    data = read(path)
    if b"app.certificates" in data:
        return "app/main.py: already patched, skipped"
    anchor = b'templates.env.globals["demo_mode"] = _ledger_mod.demo_mode'
    if data.count(anchor) != 1:
        raise SystemExit(
            "ERROR: could not find the line\n  " + anchor.decode()
            + "\nexactly once in app/main.py. Nothing was changed. Use the manual steps instead."
        )
    n = nl(data)
    addition = (
        n
        + b"# Public certificates: /verify, /certificate, QR code (app/certificates.py)" + n
        + b"from app.certificates import build_router as _build_cert_router" + n
        + b"app.include_router(_build_cert_router(templates))"
    )
    backup(path)
    path.write_bytes(data.replace(anchor, anchor + addition, 1))
    return "app/main.py: patched"


def patch_credentials_html() -> str:
    path = ROOT / "app" / "templates" / "credentials.html"
    data = read(path)
    if b"Certificate &amp; QR" in data:
        return "app/templates/credentials.html: already patched, skipped"
    anchor = b'<div id="result-cred-{{ cred.id }}"></div>'
    if data.count(anchor) != 1:
        raise SystemExit(
            "ERROR: could not find the line\n  " + anchor.decode()
            + "\nexactly once in app/templates/credentials.html. Nothing was changed there."
        )
    n = nl(data)
    link = (
        b'<a class="btn btn-secondary" href="/verify/{{ cred.credential_hash }}" '
        b'style="font-size:0.78rem;padding:0.3rem 0.75rem">Certificate &amp; QR</a>'
    )
    backup(path)
    path.write_bytes(data.replace(anchor, anchor + n + b" " * 20 + link, 1))
    return "app/templates/credentials.html: patched"


def patch_requirements() -> str:
    path = ROOT / "requirements.txt"
    data = read(path)
    if b"qrcode" in data.lower():
        return "requirements.txt: already lists qrcode, skipped"
    n = nl(data)
    backup(path)
    if not data.endswith(b"\n"):
        data += n
    path.write_bytes(data + b"qrcode==8.2" + n)
    return "requirements.txt: added qrcode==8.2"


def main() -> None:
    needed = [
        ROOT / "app" / "main.py",
        ROOT / "app" / "certificates.py",
        ROOT / "app" / "templates" / "verify.html",
        ROOT / "app" / "templates" / "certificate.html",
        ROOT / "app" / "templates" / "credentials.html",
        ROOT / "requirements.txt",
    ]
    missing = [str(p.relative_to(ROOT)) for p in needed if not p.exists()]
    if missing:
        raise SystemExit(
            "ERROR: these files are missing, so nothing was changed:\n  "
            + "\n  ".join(missing)
            + "\nRun this script from the project root and copy the new files in first."
        )
    for step in (patch_main, patch_credentials_html, patch_requirements):
        print(step())
    print("\nDone. Next: pip install -r requirements.txt  then  python smoke_certificates.py")


if __name__ == "__main__":
    sys.exit(main())
