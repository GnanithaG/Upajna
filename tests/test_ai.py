"""The AI layer validates every Claude response; these check parsing and the retry-on-bad-output path."""
import asyncio
from types import SimpleNamespace

import pytest

from app.ai import client as ai_client
from app.ai.client import extract_json
from app.ai.schemas import JobScores, TailorResult


def test_extract_json_variants():
    assert extract_json('{"a":1}') == {"a": 1}
    assert extract_json('Sure!\n```json\n{"a":2}\n```') == {"a": 2}
    assert extract_json('Here: [{"id":"x"}] done') == [{"id": "x"}]


def test_score_schema_normalizes_level_and_clamps():
    s = JobScores.model_validate({"jobs": [{"id": "a", "score": 140, "level": "strong", "reason": "r"}]})
    assert s.jobs[0].score == 100 and s.jobs[0].level == "Strong"


def test_tailor_schema_requires_resume():
    with pytest.raises(Exception):
        TailorResult.model_validate({"company": "x"})


class FakeMessages:
    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), []

    async def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.outputs.pop(0))])


def test_ask_retries_once_with_validation_error(monkeypatch):
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    fake = FakeMessages(['{"jobs":[{"id":"a","score":"not a number"}]}', '[{"id":"a","score":77,"level":"Moderate"}]'])
    monkeypatch.setattr(ai_client, "client", lambda: SimpleNamespace(messages=fake))
    out = asyncio.run(ai_client.ask("p", JobScores, wrap_list_as="jobs"))
    assert out.jobs[0].score == 77
    assert len(fake.calls) == 2 and "didn't match" in fake.calls[1]["messages"][-1]["content"]
    get_settings.cache_clear()


def test_prompts_render_without_leftover_placeholders():
    p = ai_client.render("tailor_resume", profile="P", resume="R", title="T", company="C", location="L", jd="J")
    assert "$profile" not in p and "$jd" not in p and '{"company"' in p


def test_confirmed_skills_reach_the_prompt_and_are_never_missing(client):
    from app.ai.client import render
    from app.ai.tailoring import profile_lines

    lines = profile_lines({"name": "A", "confirmed": ["Redshift", "Tableau"]})
    assert "confirmed they have: Redshift, Tableau" in lines
    assert "CONFIRMED SKILLS" in render("tailor_resume", profile=lines, resume="r", title="t", company="c", location="l", jd="j")

    # The mock tailoring reports "Tableau" as missing; once confirmed, it must not be.
    import time
    client.post("/api/login", json={"password": "test-pass"})
    roles = client.get("/api/roles").json(); roles[0]["resume"] = "Business Analyst " * 30
    client.put("/api/roles", json=roles)
    job = client.post("/api/jobs", json={"jd": "Business Analyst role. " * 20, "title": "Business Analyst"}).json()
    get = lambda: client.get(f"/api/jobs/{job['id']}").json()
    for _ in range(100):
        if get()["status"] == "review": break
        time.sleep(0.05)
    assert "Tableau" in get()["result"]["ats"]["missing"]
    client.put("/api/settings/profile", json={"confirmed": ["tableau"]})
    client.post("/api/jobs/tailor", json={"ids": [job["id"]]})
    for _ in range(100):
        j = get()
        if j["status"] == "review" and "Tableau" not in j["result"]["ats"]["missing"]: break
        time.sleep(0.05)
    assert "Tableau" not in get()["result"]["ats"]["missing"]
