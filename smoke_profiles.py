import os
import sqlite3
from fastapi.testclient import TestClient

# Ensure test DB
os.environ["PROVENANCE_DB"] = "data/critx.db"
from app.main import app
from app.db import init_db, query_one, execute
import app.profiles as profiles

client = TestClient(app)

def test_profiles_and_onboarding():
    init_db()

    # 1. Test initials helper
    assert profiles.get_initials("John Doe") == "JD"
    assert profiles.get_initials("Alice") == "AL"
    assert profiles.get_initials("Single") == "SI"
    assert profiles.get_initials("Dr. Arvind Nair") == "DN"

    # 2. Test Admin role cannot be self-selected on onboarding
    client.cookies.set("persona_id", "5") # Ananya (student)
    res_admin = client.post("/onboarding", data={"role": "admin", "institution": "Gov"}, follow_redirects=False)
    assert res_admin.status_code == 400
    assert "Admin" in res_admin.text or "admin" in res_admin.text.lower()

    # 3. Test Student onboarding (immediate access, level 1)
    res_student = client.post("/onboarding", data={"role": "student", "institution": "MIT"}, follow_redirects=False)
    assert res_student.status_code == 303
    u5 = query_one("SELECT * FROM users WHERE id = 5")
    assert u5["role"] == "student"
    assert u5["verification_level"] >= 1
    prof5 = profiles.get_or_create_profile(5)
    assert prof5["onboarding_completed"] == 1

    # 4. Test Edit Profile: name, headline, bio, institution, skills, social links
    edit_data = {
        "name": "Ananya Sharma",
        "headline": "Lead AI Researcher",
        "bio": "Specializing in edge medical imaging and quantized networks.",
        "institution": "MIT Media Lab",
        "skills": "python, pytorch, computer vision",
        "github_url": "https://github.com/ananya",
        "linkedin_url": "https://linkedin.com/in/ananya",
        "portfolio_url": "https://ananya.ai",
        "is_public": "1",
        "show_institution": "1",
        "show_credentials": "1",
    }
    res_edit = client.post("/profile/edit", data=edit_data, follow_redirects=False)
    assert res_edit.status_code == 303
    prof5_updated = profiles.get_or_create_profile(5)
    assert prof5_updated["headline"] == "Lead AI Researcher"
    assert prof5_updated["github_url"] == "https://github.com/ananya"
    assert prof5_updated["is_public"] == 1
    assert prof5_updated["show_institution"] == 1
    assert prof5_updated["show_credentials"] == 1

    # 5. Test Public Profile (/u/5) as anonymous visitor
    client.cookies.clear()
    res_u5 = client.get("/u/5")
    assert res_u5.status_code == 200
    assert "Ananya Sharma" in res_u5.text
    assert "Lead AI Researcher" in res_u5.text
    assert "MIT Media Lab" in res_u5.text
    assert "https://github.com/ananya" in res_u5.text
    assert "Earned Credits" in res_u5.text
    # STRICT PRIVACY: Email is NEVER shown
    assert "ananya@example.com" not in res_u5.text
    assert "@" not in res_u5.text or "ananya@" not in res_u5.text

    # 6. Test Minor Safety: Tara (id=9, is_minor=1) gets NO public profile
    res_minor = client.get("/u/9")
    assert res_minor.status_code == 404

    # 7. Test Privacy Toggle: is_public = 0
    client.cookies.set("persona_id", "5")
    edit_data["is_public"] = "" # Off
    client.post("/profile/edit", data=edit_data, follow_redirects=False)
    
    # Anonymous visitor now gets 404
    client.cookies.clear()
    res_private = client.get("/u/5")
    assert res_private.status_code == 404

    # But the user themselves can still see their own profile
    client.cookies.set("persona_id", "5")
    res_owner = client.get("/u/5")
    assert res_owner.status_code == 200

    # 8. Test Privacy Toggle: show_institution = 0
    client.cookies.set("persona_id", "5")
    edit_data["is_public"] = "1"
    edit_data["show_institution"] = "" # Off
    client.post("/profile/edit", data=edit_data, follow_redirects=False)

    client.cookies.clear()
    res_no_inst = client.get("/u/5")
    assert res_no_inst.status_code == 200
    assert "MIT Media Lab" not in res_no_inst.text

    # 9. Test Privacy Toggle: show_credentials = 0
    client.cookies.set("persona_id", "5")
    edit_data["show_institution"] = "1"
    edit_data["show_credentials"] = "" # Off
    client.post("/profile/edit", data=edit_data, follow_redirects=False)

    client.cookies.clear()
    res_no_creds = client.get("/u/5")
    assert res_no_creds.status_code == 200
    assert "Credentials hidden per researcher privacy settings" in res_no_creds.text

    print("\nALL PROFILE, ONBOARDING, AND PRIVACY CHECKS PASSED!")

if __name__ == "__main__":
    test_profiles_and_onboarding()
