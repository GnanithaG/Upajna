"""Job search pipeline: fetch → filter → score with Claude → save to inbox → notify."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .. import db, roles as roles_mod
from ..ai import score_jobs
from ..config import get_settings
from ..push import notify
from . import adzuna, jsearch
from .filters import blocks_sponsorship, dedupe_key, matches_excludes, title_fits

log = logging.getLogger("upajna.search")

DEFAULT_SEARCH = {
    "level": "Mid-Senior",
    "jobTypes": ["Full-time", "Contract (W2)", "Contract-to-hire"],
    "sponsorship": "needs",
    "excludes": "",
    "postedWithinHours": 24,
    "maxPerRun": 20,  # per role
    "minScore": 55,
}

_lock = asyncio.Lock()


def is_running() -> bool:
    return _lock.locked()


def _mock_jobs(title: str) -> list[dict]:
    stamp = int(datetime.now().timestamp() * 1000) % 100000
    out = []
    for n in (1, 2, 3):
        out.append({
            "id": f"mock-{''.join(c for c in title if c.isalnum())}-{n}-{stamp}",
            "source": ["LinkedIn", "Indeed", "ZipRecruiter"][n - 1], "title": ("Senior " if n == 3 else "") + title,
            "company": f"Example Co {n}", "location": "Remote", "remote": True, "jobType": "Full-time", "salary": "$95k–$115k/yr",
            "postedAt": db.now_iso(), "url": "https://example.com/job", "applyUrl": f"https://boards.greenhouse.io/example/jobs/{1000 + n}",
            "jd": "Business analyst role. We do not provide visa sponsorship." if n == 2 else
                  "Gather requirements, write user stories and acceptance criteria, run UAT, SQL data validation, Azure DevOps, Visio process maps.",
        })
    return out


async def run_search(reason: str = "scheduled") -> dict:
    if _lock.locked():
        return {"skipped": "already running"}
    async with _lock:
        settings = get_settings()
        search = {**DEFAULT_SEARCH, **(db.get_setting("search") or {})}
        all_roles = roles_mod.get_roles()
        active = roles_mod.active_roles(all_roles)
        state = db.get_setting("searchState") or {"titleIndex": 0}
        if not active:
            raise ValueError("Add a resume and job titles for at least one role in Settings.")
        # Every (title, role) pair we search for, across all roles that have a resume.
        pairs = [(t, r["id"]) for r in active for t in r["titles"]]
        titles = [t for t, _ in pairs]
        hours = int(search.get("postedWithinHours") or 24)
        notes: list[str] = []
        idle = [r["name"] for r in all_roles if r not in active]
        if idle:
            notes.append("Not searching for " + ", ".join(idle) + " until it has a resume")

        # Rotate JSearch titles to stay inside the API plan's monthly request limit.
        n = min(settings.jsearch_queries_per_run, len(pairs))
        start = int(state.get("titleIndex", 0)) % len(pairs)
        js_pairs = [pairs[(start + i) % len(pairs)] for i in range(n)]
        state["titleIndex"] = (start + n) % len(pairs)

        found: list[dict] = []  # each job remembers which role's title found it ("hint")
        if settings.mock_external:
            for r in active:
                found += [{**j, "hint": r["id"]} for j in _mock_jobs(r["titles"][0])]
        else:
            calls = [("JSearch", t, rid, jsearch.search(t, hours)) for t, rid in js_pairs] + \
                    [("Adzuna", t, rid, adzuna.search(t, hours)) for t, rid in pairs]
            results = await asyncio.gather(*(c[3] for c in calls), return_exceptions=True)
            errors = set()
            for (src, t, rid, _), res in zip(calls, results):
                if isinstance(res, Exception):
                    errors.add(f"{src} ({str(res)[:60]})")
                else:
                    found += [{**j, "hint": rid} for j in res]
            if settings.jsearch_api_key:
                notes.append("JSearch: " + ", ".join(t for t, _ in js_pairs))
            if errors:
                notes.append("Errors: " + "; ".join(sorted(errors)))

        # Filter and dedupe.
        existing_ids = db.job_ids()
        seen = {j.get("dedupeKey") or dedupe_key(j) for j in db.list_jobs()}
        dropped = {"dup": 0, "off": 0, "sponsor": 0}
        fresh = []
        for j in found:
            key = dedupe_key(j)
            if j["id"] in existing_ids or key in seen:
                dropped["dup"] += 1
            elif not title_fits(j["title"], titles) or matches_excludes(f"{j['title']} {j['jd']}", search.get("excludes", "")):
                dropped["off"] += 1
            elif search.get("sponsorship") == "needs" and blocks_sponsorship(j["jd"]):
                dropped["sponsor"] += 1
            else:
                seen.add(key)
                hint = j.pop("hint", None)
                fresh.append({**j, "dedupeKey": key, "role": roles_mod.classify(j["title"], active, hint=hint)})

        # Score with Claude in small batches, each job against its own role's resume.
        scored = []
        for role in active:
            mine = [j for j in fresh if j["role"] == role["id"]]
            for i in range(0, len(mine), 15):
                batch = mine[i : i + 15]
                try:
                    by_id = {s.id: s for s in await score_jobs(batch, role["resume"], search)}
                except Exception as e:  # keep going; one bad batch shouldn't sink the run
                    notes.append(f"Scoring error: {str(e)[:80]}")
                    continue
                for j in batch:
                    s = by_id.get(j["id"])
                    if not s:
                        continue
                    if s.exclude_reason:
                        dropped["sponsor"] += 1
                        continue
                    scored.append({**j, "fit": {"score": s.score, "level": s.level, "reason": s.reason}})

        # Keep the best matches, up to the cap for each role.
        cap, floor = int(search.get("maxPerRun") or 20), int(search.get("minScore") or 55)
        keep = []
        for role in active:
            mine = sorted((j for j in scored if j["role"] == role["id"] and j["fit"]["score"] >= floor), key=lambda j: -j["fit"]["score"])
            keep += mine[:cap]
        keep.sort(key=lambda j: -j["fit"]["score"])
        now = db.now_iso()
        for j in keep:
            db.put_job({**j, "foundAt": now, "status": "new"})

        notes.append(f"Skipped {dropped['dup']} duplicates, {dropped['sponsor']} without sponsorship, {dropped['off']} off-target")
        summary = {"lastRunAt": now, "lastRunFound": len(keep), "lastRunReason": reason, "lastRunNote": ". ".join(notes)}
        db.set_setting("searchState", {**state, **summary})
        if keep:
            top = keep[0]
            await notify(f"{len(keep)} new job{'s' if len(keep) > 1 else ''} to review",
                         f"Top match: {top['title']} at {top['company']} ({top['fit']['score']}%)", "/#inbox")
        log.info("search done: %s", summary)
        return summary
