"""Roles: each job is matched to the right role, and uses that role's resume."""
import time

from app.roles import DEFAULT_ROLES, classify
from app.search.filters import title_fits

ROLES = [{**r, "resume": ""} for r in DEFAULT_ROLES]


def test_classify_by_title():
    assert classify("Senior Business Systems Analyst", ROLES) == "ba"
    assert classify("Data Engineer II", ROLES) == "data"
    assert classify("Senior Data Platform Engineer", ROLES) == "data"
    assert classify("Machine Learning Engineer, Ads", ROLES) == "swe"
    assert classify("Software Engineer - Backend", ROLES) == "swe"
    assert classify("ETL Developer (Contract)", ROLES) == "data"


def test_vague_title_uses_description_then_hint():
    assert classify("New job", ROLES, text="We need a Data Engineer to build pipelines. The Data Engineer will...") == "data"
    assert classify("Associate", ROLES, hint="swe") == "swe"


def test_title_fits_each_role():
    titles = [t for r in DEFAULT_ROLES for t in r["titles"]]
    assert title_fits("Senior Data Platform Engineer", titles)
    assert title_fits("AI Engineer, LLM Apps", titles)
    assert not title_fits("Registered Nurse", titles)
    assert not title_fits("Data Analyst", ["Data Engineer"])


def wait_for(fn, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("timed out")


def test_each_role_searches_and_tailors_from_its_own_resume(client):
    client.post("/api/login", json={"password": "test-pass"})
    roles = client.get("/api/roles").json()
    roles[0]["resume"] = "BA RESUME. Business Analyst requirements UAT " * 20
    roles[1]["resume"] = "DATA RESUME. Data Engineer pipelines Spark SQL " * 20
    client.put("/api/roles", json=roles)  # swe has no resume, so it is not searched

    client.post("/api/search/run")
    jobs = wait_for(lambda: (not client.get("/api/status").json()["searching"]) and client.get("/api/jobs").json())
    found = {j["role"] for j in jobs}
    assert found == {"ba", "data"}
    assert "until it has a resume" in client.get("/api/status").json()["searchState"]["lastRunNote"]

    data_job = next(j for j in jobs if j["role"] == "data")
    client.post("/api/jobs/tailor", json={"ids": [data_job["id"]]})
    job = wait_for(lambda: (j := client.get(f"/api/jobs/{data_job['id']}").json())["status"] == "review" and j)
    assert job["role"] == "data"

    # Moving a job to a role without a resume is refused at tailoring time, with a clear message.
    client.patch(f"/api/jobs/{data_job['id']}", json={"role": "swe"})
    r = client.post("/api/jobs/tailor", json={"ids": [data_job["id"]]})
    assert r.status_code == 400 and "Software / AI-ML Engineer" in r.json()["error"]


def test_old_single_resume_becomes_business_analyst_role(client):
    from app import db
    db.set_setting("resume", {"text": "OLD RESUME " * 30, "fileName": "old.pdf"})
    db.set_setting("search", {"titles": ["Business Analyst", "Product Owner"]})
    client.post("/api/login", json={"password": "test-pass"})
    ba = client.get("/api/roles").json()[0]
    assert ba["id"] == "ba" and ba["ready"] and ba["fileName"] == "old.pdf" and "Product Owner" in ba["titles"]
