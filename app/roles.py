"""Roles: each role has its own search titles and its own master resume.

A job is tagged with the role it belongs to (`job["role"]`), and everything downstream
(scoring, tailoring, filling forms) uses that role's resume.
"""
from __future__ import annotations

import re
from typing import Optional

from . import db

MAX_ROLES = 5
MIN_RESUME = 200

DEFAULT_ROLES = [
    {"id": "ba", "name": "Business Analyst",
     "titles": ["Business Analyst", "Business Systems Analyst", "IT Business Analyst", "Technical Business Analyst", "Agile Business Analyst"]},
    {"id": "data", "name": "Data Engineer",
     "titles": ["Data Engineer", "Analytics Engineer", "Big Data Engineer", "Cloud Data Engineer", "ETL Developer"]},
    {"id": "swe", "name": "Software / AI-ML Engineer",
     "titles": ["Software Engineer", "Python Developer", "Backend Engineer", "Machine Learning Engineer", "AI Engineer"]},
]

_STOP = {"senior", "sr", "junior", "jr", "lead", "staff", "principal", "i", "ii", "iii", "iv", "the", "and", "of", "/", "-"}


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#]+", (s or "").lower()) if w not in _STOP}


def _blank(r: dict) -> dict:
    return {"id": r["id"], "name": r["name"], "titles": list(r["titles"]), "resume": "", "fileName": "", "updatedAt": ""}


def get_roles() -> list[dict]:
    """Saved roles. The first time, build them from the old single resume and title list."""
    roles = db.get_setting("roles")
    if isinstance(roles, list) and roles:
        return roles
    old_resume = db.get_setting("resume") or {}
    old_titles = (db.get_setting("search") or {}).get("titles")
    roles = [_blank(r) for r in DEFAULT_ROLES]
    if old_titles:
        roles[0]["titles"] = list(old_titles)
    if old_resume.get("text"):
        roles[0].update(resume=old_resume["text"], fileName=old_resume.get("fileName", ""), updatedAt=old_resume.get("updatedAt", ""))
    return roles


def save_roles(roles: list[dict]) -> list[dict]:
    return db.set_setting("roles", roles)


def active_roles(roles: Optional[list[dict]] = None) -> list[dict]:
    """Roles that can be searched: they have titles and a real resume."""
    return [r for r in (roles if roles is not None else get_roles()) if r.get("titles") and len(r.get("resume", "")) >= MIN_RESUME]


def classify(title: str, roles: list[dict], hint: Optional[str] = None, text: str = "") -> str:
    """Pick the role a job belongs to from its title (and, if the title is vague, its description)."""
    if not roles:
        return hint or ""
    t, tw = (title or "").lower(), _words(title)
    best, best_score = None, 0.0
    for r in roles:
        score = 0.0
        for x in r.get("titles") or []:
            xw = _words(x)
            if not xw:
                continue
            if x.lower() in t:
                score = max(score, 2.0 + len(xw) / 10)  # exact phrase wins; longer phrase is more specific
            else:
                score = max(score, len(xw & tw) / len(xw))
        if score > best_score:
            best, best_score = r, score
    if best and best_score >= 0.99:
        return best["id"]
    if text:  # vague title like "New job": count title phrases in the description
        low = text.lower()
        counts = [(sum(low.count(x.lower()) for x in r.get("titles") or []), r) for r in roles]
        n, r = max(counts, key=lambda c: c[0])
        if n:
            return r["id"]
    ids = [r["id"] for r in roles]
    if hint in ids:
        return hint
    return best["id"] if best and best_score >= 0.5 else ids[0]


def role_of(job: dict, roles: Optional[list[dict]] = None) -> Optional[dict]:
    roles = roles if roles is not None else get_roles()
    rid = job.get("role")
    match = next((r for r in roles if r["id"] == rid), None)
    if match:
        return match
    rid = classify(job.get("title", ""), roles, text=job.get("jd", ""))
    return next((r for r in roles if r["id"] == rid), None)


def resume_for(job: dict) -> tuple[str, Optional[dict]]:
    """The resume text to use for this job, and the role it came from."""
    role = role_of(job)
    return (role or {}).get("resume", ""), role
