"""Tailor the master resume to one job: honest ATS optimization, cover letter, and application answers."""
import re

from .client import ask, render
from .schemas import TailorResult

PROFILE_FIELDS = [
    ("Name", "name"), ("Email", "email"), ("Phone", "phone"), ("Location", "location"), ("LinkedIn", "linkedin"),
    ("Portfolio", "portfolio"), ("Work authorization", "auth"), ("Sponsorship needed", "sponsor"),
    ("Desired salary", "salary"), ("Start date", "start"), ("Relocation", "relocate"), ("Work preference", "workpref"),
    ("Years of experience", "years"), ("EEO questions", "eeo"), ("Standard answers", "answers"),
]


def profile_lines(p: dict) -> str:
    lines = [f"{label}: {p[key]}" for label, key in PROFILE_FIELDS if p.get(key)]
    if p.get("confirmed"):
        lines.append("Additional skills the candidate confirmed they have: " + ", ".join(p["confirmed"]))
    return "\n".join(lines) or "(none)"


def file_base(name: str, company: str, role: str) -> str:
    clean = lambda s: re.sub(r"^_|_$", "", re.sub(r"[^A-Za-z0-9]+", "_", s or ""))[:28]
    person = re.sub(r"\s+", "_", (name or "Resume").strip())
    return f"{person}_Resume_{clean(company)}_{clean(role)}"


def _mock(job: dict, profile: dict) -> dict:
    return {
        "company": job.get("company", ""), "role": job.get("title", ""), "location": job.get("location", ""),
        "fit": {"level": "Strong", "score": 88, "reason": "Mock result for testing.", "strengths": ["Requirements workshops"], "gaps": []},
        "keywords": [{"term": "UAT", "found": True}, {"term": "Jira", "found": True}], "ats": {"score": 91, "missing": ["Tableau"]},
        "resume": {"name": profile.get("name") or "Test Person", "headline": job.get("title", ""), "contact": [profile.get("email") or "test@example.com"],
                   "summary": "Business Analyst with 6+ years.", "skills": [{"group": "Analysis", "items": ["Requirements", "UAT"]}],
                   "experience": [{"title": "Business Analyst", "company": "Cencora", "dates": "2025 – 2026", "bullets": ["Facilitated workshops."]}],
                   "education": [{"degree": "MS Computer Science", "school": "California State University", "dates": "2026"}]},
        "coverLetter": "Dear Hiring Team,\n\nMock letter.\n\nSincerely,\nTest",
        "answers": [{"question": "Will you require sponsorship?", "answer": profile.get("sponsor") or "ASK ME: sponsorship"}],
        "changes": ["Mock"],
    }


async def tailor_job(job: dict, profile: dict, resume_text: str) -> TailorResult:
    prompt = render(
        "tailor_resume",
        profile=profile_lines(profile), resume=resume_text,
        title=job.get("title", ""), company=job.get("company", ""), location=job.get("location", ""), jd=job.get("jd", ""),
    )
    result = await ask(prompt, TailorResult, max_tokens=12000, mock=lambda: _mock(job, profile))
    result.fileBase = file_base(profile.get("name") or result.resume.name, result.company or job.get("company", ""), result.role or job.get("title", ""))
    return result
