import os
from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db, query_one, query_all
from app.seed import seed_users, seed_projects
import json

# Helper to get persona client
def client_for(name: str) -> TestClient:
    row = query_one("SELECT id FROM users WHERE name = ?", (name,))
    if not row:
        raise RuntimeError(f"User '{name}' not found in DB")
    c = TestClient(app, follow_redirects=True)
    c.cookies.set("persona_id", str(row["id"]))
    return c

# Initialize DB and seed data
init_db()
seed_users()
seed_projects()

PERSONAS = ["Admin Asha", "Meera Rao", "Ananya", "Sneha", "Vikram", "Kiran Shah", "Tara", "Student X", "Demo User"]

FAILURES = []

# Test all GET routes without path params
def test_get_routes():
    for route in app.routes:
        if not hasattr(route, "methods"):
            continue
        if "GET" not in route.methods:
            continue
        path = route.path
        # skip routes with path parameters
        if "{" in path:
            continue
        for persona in PERSONAS:
            client = client_for(persona)
            resp = client.get(path)
            if resp.status_code not in (200, 302, 303, 401, 403, 404):
                FAILURES.append({"persona": persona, "url": path, "status": resp.status_code, "error": resp.text[:200]})

# Test detail pages for seeded ids (project, contribution, certificate, profile)
def test_detail_pages():
    # Projects
    projects = query_all("SELECT id FROM projects")
    for p in projects:
        path = f"/projects/{p['id']}"
        for persona in PERSONAS:
            client = client_for(persona)
            resp = client.get(path)
            if resp.status_code not in (200, 302, 303, 401, 403, 404):
                FAILURES.append({"persona": persona, "url": path, "status": resp.status_code, "error": resp.text[:200]})
    # Contributions (assuming route /contributions/{id})
    contribs = query_all("SELECT id FROM contributions")
    for c in contribs:
        path = f"/contributions/{c['id']}"
        for persona in PERSONAS:
            client = client_for(persona)
            resp = client.get(path)
            if resp.status_code not in (200, 302, 303, 401, 403, 404):
                FAILURES.append({"persona": persona, "url": path, "status": resp.status_code, "error": resp.text[:200]})
    # Certificates (assuming /certificate/{hash})
    certs = query_all("SELECT credential_hash FROM certificates")
    for cert in certs:
        path = f"/certificate/{cert['credential_hash']}"
        for persona in PERSONAS:
            client = client_for(persona)
            resp = client.get(path)
            if resp.status_code not in (200, 302, 303, 401, 403, 404):
                FAILURES.append({"persona": persona, "url": path, "status": resp.status_code, "error": resp.text[:200]})
    # Profiles
    users = query_all("SELECT id FROM users")
    for u in users:
        path = f"/profile/{u['id']}"
        for persona in PERSONAS:
            client = client_for(persona)
            resp = client.get(path)
            if resp.status_code not in (200, 302, 303, 401, 403, 404):
                FAILURES.append({"persona": persona, "url": path, "status": resp.status_code, "error": resp.text[:200]})

if __name__ == "__main__":
    test_get_routes()
    test_detail_pages()
    if FAILURES:
        print("FAILURES:\tPersona\tURL\tStatus\tSnippet")
        for f in FAILURES[:25]:
            print(f"{f['persona']}\t{f['url']}\t{f['status']}\t{f['error'].replace('\n',' ')}")
        exit(1)
    else:
        print("All UI checks passed")
        exit(0)
