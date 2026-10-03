"""Adzuna: free official API with broad US coverage. Descriptions are shortened, so we
fetch the full posting text before tailoring (fetch_full_description)."""
import html
import math
import re

import httpx

from ..config import get_settings

_TAG = re.compile(r"<[^>]+>")


def normalize(j: dict) -> dict:
    lo, hi = j.get("salary_min"), j.get("salary_max")
    salary = ("–".join(f"${round(n / 1000)}k" for n in (lo, hi) if n) + "/yr") if (lo or hi) else ""
    loc = (j.get("location") or {}).get("display_name") or "United States"
    title = _TAG.sub("", j.get("title") or "")
    return {
        "id": f"az-{j.get('id')}",
        "source": "Adzuna",
        "title": title,
        "company": (j.get("company") or {}).get("display_name") or "",
        "location": loc,
        "remote": "remote" in f"{title} {loc}".lower(),
        "jobType": ", ".join(x for x in (j.get("contract_time"), j.get("contract_type")) if x).replace("_", " "),
        "salary": salary,
        "postedAt": j.get("created") or "",
        "url": j.get("redirect_url") or "",
        "applyUrl": j.get("redirect_url") or "",
        "jd": _TAG.sub("", j.get("description") or ""),
        "jdShort": True,
    }


async def search(title: str, hours: int = 24) -> list[dict]:
    s = get_settings()
    if not (s.adzuna_app_id and s.adzuna_app_key):
        return []
    params = {"app_id": s.adzuna_app_id, "app_key": s.adzuna_app_key, "what_phrase": title,
              "max_days_old": max(1, math.ceil(hours / 24)), "results_per_page": 30, "sort_by": "date"}
    async with httpx.AsyncClient(timeout=40) as c:
        r = await c.get("https://api.adzuna.com/v1/api/jobs/us/search/1", params=params)
        r.raise_for_status()
        return [normalize(j) for j in r.json().get("results") or []]


def html_to_text(raw: str) -> str:
    t = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", raw, flags=re.I)
    t = re.sub(r"<(br|/p|/li|/h\d|/div)>", "\n", t, flags=re.I)
    t = html.unescape(_TAG.sub(" ", t))
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


async def fetch_full_description(url: str) -> tuple[str, str]:
    """Best effort: follow the link and return (text, final_url)."""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 Upajna"}) as c:
            r = await c.get(url)
            if r.status_code >= 400:
                return "", url
            return html_to_text(r.text)[:9000], str(r.url)
    except httpx.HTTPError:
        return "", url
