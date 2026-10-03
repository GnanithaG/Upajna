"""Score a batch of jobs against the candidate's resume with a fast model."""
import json

from ..config import get_settings
from .client import ask, render
from .schemas import JobScore, JobScores


def _mock(jobs: list[dict]) -> dict:
    return {"jobs": [
        {"id": j["id"], "score": 0 if "sponsor" in j.get("jd", "").lower() else 82, "level": "Strong",
         "reason": "Requirements, UAT and SQL validation match your last two roles.",
         "excludeReason": "No sponsorship" if "sponsor" in j.get("jd", "").lower() else ""}
        for j in jobs]}


async def score_jobs(jobs: list[dict], resume_text: str, search: dict) -> list[JobScore]:
    needs = search.get("sponsorship") == "needs"
    payload = [{"id": j["id"], "title": j["title"], "company": j["company"], "location": j["location"],
                "type": j.get("jobType", ""), "text": j.get("jd", "")[:1800]} for j in jobs]
    prompt = render(
        "score_jobs",
        level=search.get("level", "Mid-Senior"),
        sponsorship_line="NEEDS visa sponsorship now or in the future" if needs else "does not need sponsorship",
        job_types=", ".join(search.get("jobTypes") or []) or "any",
        sponsor_rule=("the posting says no visa sponsorship, US citizens / green card holders only, or requires a security clearance;"
                      if needs else "the posting requires a security clearance;"),
        resume=resume_text[:6000],
        jobs=json.dumps(payload),
    )
    result = await ask(prompt, JobScores, model=get_settings().claude_quick_model, max_tokens=4000,
                       wrap_list_as="jobs", mock=lambda: _mock(jobs))
    return result.jobs
