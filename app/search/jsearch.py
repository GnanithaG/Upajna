"""JSearch (RapidAPI): aggregates LinkedIn, Indeed, ZipRecruiter, Glassdoor and company career sites."""
import re

import httpx

from ..config import get_settings

ATS = re.compile(r"(greenhouse\.io|lever\.co|ashbyhq\.com|myworkdayjobs\.com|smartrecruiters\.com|icims\.com|workable\.com)", re.I)
PUBLISHERS = ["LinkedIn", "Indeed", "ZipRecruiter", "Glassdoor", "Monster", "Dice"]


def _apply_link(j: dict) -> str:
    opts = j.get("apply_options") or []
    best = next((o for o in opts if ATS.search(o.get("apply_link", ""))), None) or next((o for o in opts if o.get("is_direct")), None)
    return (best or {}).get("apply_link") or j.get("job_apply_link") or (opts[0].get("apply_link") if opts else "")


def _salary(j: dict) -> str:
    lo, hi = j.get("job_min_salary"), j.get("job_max_salary")
    if not lo and not hi:
        return ""
    f = lambda n: f"${round(n / 1000)}k" if n >= 1000 else f"${n}"
    per = {"YEAR": "/yr", "HOUR": "/hr", "MONTH": "/mo"}.get(j.get("job_salary_period") or "", "")
    return "–".join(f(n) for n in (lo, hi) if n) + per


def normalize(j: dict) -> dict:
    pub = j.get("job_publisher") or ""
    source = next((p for p in PUBLISHERS if p.lower() in pub.lower()), pub or "JSearch")
    apply_url = _apply_link(j)
    return {
        "id": "js-" + re.sub(r"[^A-Za-z0-9_-]", "", str(j.get("job_id", "")))[:60],
        "source": source,
        "title": j.get("job_title") or "",
        "company": j.get("employer_name") or "",
        "location": ", ".join(x for x in (j.get("job_city"), j.get("job_state")) if x) or j.get("job_country") or "United States",
        "remote": bool(j.get("job_is_remote")),
        "jobType": j.get("job_employment_type") or "",
        "salary": _salary(j),
        "postedAt": j.get("job_posted_at_datetime_utc") or "",
        "url": j.get("job_google_link") or j.get("job_apply_link") or apply_url,
        "applyUrl": apply_url,
        "jd": (j.get("job_description") or "")[:9000],
    }


async def search(title: str, hours: int = 24) -> list[dict]:
    s = get_settings()
    if not s.jsearch_api_key:
        return []
    date_posted = "today" if hours <= 24 else "3days" if hours <= 72 else "week"
    params = {"query": f"{title} in USA", "page": "1", "num_pages": "1", "country": "us",
              "date_posted": date_posted, "employment_types": "FULLTIME,CONTRACTOR,PARTTIME"}
    headers = {"X-RapidAPI-Key": s.jsearch_api_key, "X-RapidAPI-Host": s.jsearch_host}
    async with httpx.AsyncClient(timeout=40) as c:
        r = await c.get(f"https://{s.jsearch_host}/search", params=params, headers=headers)
        r.raise_for_status()
        return [normalize(j) for j in r.json().get("data") or []]
