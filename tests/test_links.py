"""Reading a job from a link: each site's format, and the add-by-link flow."""
import time

import pytest

from app.search.links import (LinkError, clean_url, linkedin_id, parse_ashby, parse_generic, parse_greenhouse,
                              parse_lever, parse_linkedin)

DESC = "<p>We are looking for a Business Analyst to gather requirements and run UAT.</p>" + "<li>Write user stories</li>" * 30

LINKEDIN_EXTERNAL = f"""
<section class="top-card-layout"><h2 class="top-card-layout__title font-sans">Senior Business Analyst</h2>
<a class="topcard__org-name-link topcard__flavor--black-link" href="#">  Acme Health </a>
<span class="topcard__flavor topcard__flavor--bullet">Irvine, CA</span>
<code id="applyUrl" style="display: none"><!--"https://www.linkedin.com/jobs/view/externalApply/4012345678?url=https%3A%2F%2Fboards%2Egreenhouse%2Eio%2Facme%2Fjobs%2F5551234&amp;urlHash=abc"--></code>
</section>
<div class="show-more-less-html__markup show-more-less-html__markup--clamp-after-5">{DESC}</div>
<h3 class="description__job-criteria-subheader">Employment type</h3>
<span class="description__job-criteria-text">Full-time</span>
"""
LINKEDIN_NO_CODE = LINKEDIN_EXTERNAL.split("<code")[0] + f'<div class="show-more-less-html__markup">{DESC}</div>'
LINKEDIN_EASY = LINKEDIN_NO_CODE + '<button data-tracking-control-name="public_jobs_apply-link-onsite">Easy Apply</button>'
LINKEDIN_OFFSITE_HIDDEN = LINKEDIN_NO_CODE + '<a data-tracking-control-name="public_jobs_apply-link-offsite_sign-up-modal">Apply</a>'


def test_linkedin_ids_from_every_url_shape():
    assert linkedin_id("https://www.linkedin.com/jobs/view/4012345678/") == "4012345678"
    assert linkedin_id("https://www.linkedin.com/jobs/view/senior-business-analyst-at-acme-4012345678?trk=abc") == "4012345678"
    assert linkedin_id("https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4012345678") == "4012345678"
    assert linkedin_id("https://www.linkedin.com/jobs/search/?keywords=analyst") is None
    assert linkedin_id("https://example.com/jobs/view/4012345678") is None


def test_clean_url_from_shared_text():
    shared = "Check out this job at Acme: Senior Business Analyst https://www.linkedin.com/jobs/view/4012345678."
    assert clean_url(shared) == "https://www.linkedin.com/jobs/view/4012345678"
    with pytest.raises(LinkError):
        clean_url("no link here")


def test_linkedin_company_site_job():
    j = parse_linkedin(LINKEDIN_EXTERNAL, "4012345678")
    assert (j.title, j.company, j.location, j.jobType) == ("Senior Business Analyst", "Acme Health", "Irvine, CA", "Full-time")
    assert j.applyVia == "company_site" and j.applyUrl == "https://boards.greenhouse.io/acme/jobs/5551234"
    assert "user stories" in j.jd and j.url == "https://www.linkedin.com/jobs/view/4012345678/"


def test_linkedin_easy_apply_job():
    j = parse_linkedin(LINKEDIN_EASY, "4012345678")
    assert j.applyVia == "easy_apply" and "linkedin.com" in j.applyUrl


def test_linkedin_company_site_with_hidden_address_is_not_easy_apply():
    # Real case: the Wingstop job showed "Apply ↗" on LinkedIn but the address was hidden.
    j = parse_linkedin(LINKEDIN_OFFSITE_HIDDEN, "4012345678")
    assert j.applyVia == "company_site" and "linkedin.com" in j.applyUrl
    unknown = parse_linkedin(LINKEDIN_NO_CODE, "4012345678")
    assert unknown.applyVia == ""          # can't tell: never guess Easy Apply


def test_finding_the_original_posting():
    from app.search.jsearch import pick_original
    jobs = [
        {"employer_name": "Wingstop", "job_title": "Data Engineer", "apply_options": [{"apply_link": "https://www.linkedin.com/jobs/view/1"}]},
        {"employer_name": "Other Co", "job_title": "Data Engineer", "apply_options": [{"apply_link": "https://boards.greenhouse.io/other/jobs/9"}]},
        {"employer_name": "Wingstop Restaurants Inc.", "job_title": "Data Engineer II",
         "apply_options": [{"apply_link": "https://wingstop.wd1.myworkdayjobs.com/en-US/careers/job/Dallas/Data-Engineer_R123"}]},
    ]
    assert pick_original(jobs, "Data Engineer", "Wingstop Restaurants Inc.").startswith("https://wingstop.wd1.myworkdayjobs.com")
    assert pick_original(jobs, "Product Manager", "Wingstop Restaurants Inc.") == ""


def test_linkedin_blocked_page_asks_for_text():
    with pytest.raises(LinkError, match="Paste"):
        parse_linkedin("<html><body>Sign in to see this job</body></html>", "1")


def test_greenhouse_lever_ashby_apis():
    gh = parse_greenhouse({"title": "Data Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                           "location": {"name": "Remote"}, "content": "&lt;p&gt;Build pipelines&lt;/p&gt;"}, "acme")
    assert gh.title == "Data Engineer" and gh.jd == "Build pipelines" and gh.company == "Acme"
    lv = parse_lever({"text": "ML Engineer", "hostedUrl": "https://jobs.lever.co/acme/x", "applyUrl": "https://jobs.lever.co/acme/x/apply",
                      "categories": {"location": "Remote", "commitment": "Full-time"}, "descriptionPlain": "Train models",
                      "lists": [{"text": "You have", "content": "<li>Python</li>"}]}, "acme")
    assert lv.applyUrl.endswith("/apply") and "Python" in lv.jd and lv.remote
    ab = parse_ashby({"jobs": [{"id": "abc", "title": "AI Engineer", "jobUrl": "https://jobs.ashbyhq.com/acme/abc",
                                "applyUrl": "https://jobs.ashbyhq.com/acme/abc/application", "descriptionPlain": "LLM apps", "isRemote": True}]},
                     "acme", "abc")
    assert ab.title == "AI Engineer" and ab.remote
    with pytest.raises(LinkError):
        parse_ashby({"jobs": []}, "acme", "gone")


def test_any_careers_page_with_structured_data():
    raw = """<html><head><script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",
      "title":"Business Systems Analyst","hiringOrganization":{"@type":"Organization","name":"Globex"},
      "jobLocation":{"@type":"Place","address":{"addressLocality":"Dallas","addressRegion":"TX"}},
      "employmentType":"FULL_TIME","datePosted":"2026-10-01",
      "description":"&lt;p&gt;""" + ("Own requirements and UAT. " * 20) + """&lt;/p&gt;"}</script></head><body></body></html>"""
    j = parse_generic(raw, "https://careers.globex.com/jobs/42")
    assert (j.title, j.company, j.location) == ("Business Systems Analyst", "Globex", "Dallas, TX")
    assert j.applyVia == "company_site" and j.source == "careers.globex.com"


def wait_for(fn, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("timed out")


def setup(client):
    client.post("/api/login", json={"password": "test-pass"})
    roles = client.get("/api/roles").json()
    roles[0]["resume"] = "Business Analyst requirements UAT " * 20
    client.put("/api/roles", json=roles)


def test_add_linkedin_link_then_easy_apply_comes_back_to_you(client):
    setup(client)
    r = client.post("/api/jobs", json={"url": "Look at this job https://www.linkedin.com/jobs/view/4000000001/"})
    assert r.status_code == 201
    job = r.json()
    assert job["source"] == "LinkedIn" and job["applyVia"] == "easy_apply" and job["role"] == "ba"

    job = wait_for(lambda: (j := client.get(f"/api/jobs/{job['id']}").json())["status"] == "review" and j)
    client.post(f"/api/jobs/{job['id']}/approve", json={"answers": [{"question": "Sponsorship?", "answer": "Yes"}]})
    job = wait_for(lambda: (j := client.get(f"/api/jobs/{job['id']}").json())["status"] == "needs_you" and j)
    assert "Easy Apply" in job["note"]

    # Sending the same link again doesn't add a second copy.
    again = client.post("/api/jobs", json={"url": "https://www.linkedin.com/jobs/view/4000000001"})
    assert again.status_code == 200 and again.json()["duplicate"]


def test_linkedin_job_that_applies_on_company_site(client):
    setup(client)
    job = client.post("/api/jobs", json={"url": "https://www.linkedin.com/jobs/view/4000000002/"}).json()
    assert job["applyVia"] == "company_site" and job["ats"] == "greenhouse"


def test_no_sponsorship_link_is_flagged_but_can_be_forced(client):
    setup(client)
    r = client.post("/api/jobs", json={"url": "https://www.linkedin.com/jobs/view/4000000002/?nosponsor=1"})
    assert r.status_code == 409 and "sponsor" in r.json()["error"]
    r = client.post("/api/jobs", json={"url": "https://www.linkedin.com/jobs/view/4000000002/?nosponsor=1", "force": True})
    assert r.status_code == 201


def test_unreadable_link_asks_for_description(client, monkeypatch):
    setup(client)
    import app.main as m

    async def boom(_):
        raise LinkError("LinkedIn didn't show this job to Upajna. Paste the job description below and it will carry on.")
    monkeypatch.setattr(m, "read_job_link", boom)
    r = client.post("/api/jobs", json={"url": "https://www.linkedin.com/jobs/view/4000000009/"})
    assert r.status_code == 422 and r.json()["needsText"]
    r = client.post("/api/jobs", json={"url": "https://www.linkedin.com/jobs/view/4000000009/", "jd": "Business Analyst. " * 20})
    assert r.status_code == 201


def test_hidden_company_link_is_looked_up_then_can_be_pasted(client, monkeypatch):
    setup(client)
    import app.main as m

    async def found(title, company):
        return "https://boards.greenhouse.io/wingstop/jobs/555"
    monkeypatch.setattr(m.jsearch, "find_original", found)
    job = client.post("/api/jobs", json={"url": "https://www.linkedin.com/jobs/view/4000000003/", "role": "ba"}).json()
    assert job["applyVia"] == "company_site" and job["ats"] == "greenhouse"



def test_hidden_company_link_not_found_asks_you_to_paste_it(client, monkeypatch):
    # Not found by search: after approving, Tracker asks for the link, and pasting it lets Upajna fill the form.
    setup(client)
    import app.main as m

    async def nothing(title, company):
        return ""
    monkeypatch.setattr(m.jsearch, "find_original", nothing)
    job = client.post("/api/jobs", json={"url": "https://www.linkedin.com/jobs/view/4000000013/", "role": "ba"}).json()
    assert job["ats"] == "linkedin" and job["applyVia"] == "company_site"
    job = wait_for(lambda: (j := client.get(f"/api/jobs/{job['id']}").json())["status"] == "review" and j)
    client.post(f"/api/jobs/{job['id']}/approve", json={"answers": [{"question": "Sponsorship?", "answer": "Yes"}]})
    job = wait_for(lambda: (j := client.get(f"/api/jobs/{job['id']}").json())["status"] == "needs_you" and j)
    assert "own website" in job["note"] and "Easy Apply" not in job["note"]

    assert client.patch(f"/api/jobs/{job['id']}", json={"applyUrl": "https://www.linkedin.com/jobs/view/1"}).status_code == 400
    j = client.patch(f"/api/jobs/{job['id']}", json={"applyUrl": "https://boards.greenhouse.io/wingstop/jobs/555"}).json()
    assert j["ats"] == "greenhouse"
    client.post(f"/api/jobs/{job['id']}/retry")
    job = wait_for(lambda: (j := client.get(f"/api/jobs/{job['id']}").json())["status"] == "needs_you" and "Dry run" in j.get("note", "") and j)
