"""Read one job from a link you send.

How each site is read:
- Greenhouse, Lever, Ashby: their official public job APIs (made for exactly this).
- LinkedIn: the public job page for that one job, the same page anyone sees without signing in.
  Upajna never signs in to LinkedIn and never searches it on its own.
- Anything else: the page's structured job data (schema.org JobPosting) if it has it, else its text.

If a page can't be read, the caller asks you to paste the description instead.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from ..config import get_settings
from .adzuna import html_to_text

UA = {"User-Agent": "Mozilla/5.0 (compatible; Upajna/1.0; personal job assistant)", "Accept-Language": "en-US,en;q=0.9"}


class LinkError(Exception):
    """The link couldn't be read. The message is shown to you as-is."""


@dataclass
class LinkJob:
    url: str                      # where you found it (canonical)
    source: str                   # LinkedIn, Greenhouse, Lever, Ashby, or the site's name
    title: str = ""
    company: str = ""
    location: str = ""
    jd: str = ""
    applyUrl: str = ""            # where the application actually happens
    applyVia: str = ""            # "easy_apply", "company_site", or ""
    remote: bool = False
    jobType: str = ""
    postedAt: str = ""
    notes: list[str] = field(default_factory=list)

    def as_job(self) -> dict:
        d = asdict(self)
        d.pop("notes")
        return d


# ---------- recognising links ----------
def linkedin_id(url: str) -> Optional[str]:
    """LinkedIn job ids appear in several URL shapes; all lead to the same job."""
    u = urlparse(url)
    if "linkedin.com" not in u.netloc:
        return None
    q = parse_qs(u.query)
    for key in ("currentJobId", "jobId"):
        if q.get(key) and q[key][0].isdigit():
            return q[key][0]
    m = re.search(r"/jobs/view/(?:[^/?]*?-)?(\d{6,})", u.path)
    return m.group(1) if m else None


def _greenhouse(url: str) -> Optional[tuple[str, str]]:
    u = urlparse(url)
    m = re.match(r"/([^/]+)/jobs/(\d+)", u.path)
    if "greenhouse.io" in u.netloc and m:
        return m.group(1), m.group(2)
    q = parse_qs(u.query)
    if "greenhouse.io" in u.netloc and q.get("for") and q.get("token"):  # embed links
        return q["for"][0], q["token"][0]
    return None


def _lever(url: str) -> Optional[tuple[str, str]]:
    u = urlparse(url)
    m = re.match(r"/([^/]+)/([0-9a-f-]{36})", u.path)
    return (m.group(1), m.group(2)) if "lever.co" in u.netloc and m else None


def _ashby(url: str) -> Optional[tuple[str, str]]:
    u = urlparse(url)
    m = re.match(r"/([^/]+)/([0-9a-f-]{36})", u.path)
    return (unquote(m.group(1)), m.group(2)) if "ashbyhq.com" in u.netloc and m else None


def clean_url(text: str) -> str:
    """Pull the first link out of whatever was pasted or shared (phones often add text around it)."""
    m = re.search(r"https?://[^\s<>\"']+", text or "")
    if not m:
        raise LinkError("That doesn't look like a link. Copy the job's address and paste it here.")
    return m.group(0).rstrip(").,;")


# ---------- parsing (pure functions, easy to test) ----------
def _text(fragment: str) -> str:
    return html_to_text(html.unescape(fragment or "")).strip()


def _first(pattern: str, raw: str) -> str:
    m = re.search(pattern, raw, re.I | re.S)
    return _text(m.group(1)) if m else ""


def parse_linkedin(raw: str, job_id: str) -> LinkJob:
    """LinkedIn's public job page (no sign-in)."""
    job = LinkJob(url=f"https://www.linkedin.com/jobs/view/{job_id}/", source="LinkedIn")
    ld = parse_jsonld(raw)
    job.title = _first(r'class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h[12]>', raw) or (ld.title if ld else "")
    job.company = _first(r'class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>', raw) or (ld.company if ld else "")
    job.location = _first(r'class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>(.*?)</span>', raw) or (ld.location if ld else "")
    desc = re.search(r'class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', raw, re.I | re.S)
    job.jd = _text(desc.group(1)) if desc else (ld.jd if ld else "")
    job.jobType = _first(r"Employment type\s*</h3>\s*<span[^>]*>(.*?)</span>", raw)
    job.postedAt = ld.postedAt if ld else ""
    job.remote = "remote" in (job.location + " " + job.title).lower()

    # Jobs that apply on the company's own site carry that address in a hidden "applyUrl" block.
    m = re.search(r'<code[^>]*id="applyUrl"[^>]*>\s*<!--\s*"?(.*?)"?\s*-->', raw, re.S)
    if m:
        ext = html.unescape(m.group(1))
        target = parse_qs(urlparse(ext).query).get("url", [""])[0]
        job.applyUrl, job.applyVia = (unquote(target) if target else ext), "company_site"
    else:
        job.applyUrl, job.applyVia = job.url, "easy_apply"
    if not (job.title and job.jd):
        raise LinkError("LinkedIn didn't show this job to Upajna. Paste the job description below and it will carry on.")
    return job


def parse_jsonld(raw: str) -> Optional[LinkJob]:
    """Most career sites describe their jobs in a standard format (schema.org JobPosting) for Google."""
    for block in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', raw, re.I | re.S):
        try:
            data = json.loads(html.unescape(block.strip()))
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for it in items:
            if not isinstance(it, dict) or "JobPosting" not in str(it.get("@type")):
                continue
            org = it.get("hiringOrganization") or {}
            locs = it.get("jobLocation") or []
            locs = locs if isinstance(locs, list) else [locs]
            addr = [(l.get("address") or {}) for l in locs if isinstance(l, dict)]
            place = "; ".join(", ".join(x for x in (a.get("addressLocality"), a.get("addressRegion")) if x) for a in addr if isinstance(a, dict))
            et = it.get("employmentType") or ""
            return LinkJob(
                url="", source="", title=_text(it.get("title", "")), company=_text(org.get("name", "") if isinstance(org, dict) else str(org)),
                location=place, jd=_text(it.get("description", "")), postedAt=str(it.get("datePosted") or ""),
                jobType=", ".join(et) if isinstance(et, list) else str(et),
                remote=str(it.get("jobLocationType", "")).upper() == "TELECOMMUTE",
            )
    return None


def parse_greenhouse(data: dict, board: str) -> LinkJob:
    return LinkJob(url=data.get("absolute_url") or "", source="Greenhouse", title=data.get("title", ""),
                   company=data.get("company_name") or board.replace("-", " ").title(),
                   location=(data.get("location") or {}).get("name", ""), jd=_text(data.get("content", "")),
                   applyUrl=data.get("absolute_url") or "", applyVia="company_site", postedAt=data.get("updated_at") or "")


def parse_lever(data: dict, company: str) -> LinkJob:
    cat = data.get("categories") or {}
    parts = [data.get("descriptionPlain") or _text(data.get("description", ""))]
    for lst in data.get("lists") or []:
        parts.append(f"{lst.get('text', '')}\n{_text(lst.get('content', ''))}")
    parts.append(data.get("additionalPlain") or "")
    return LinkJob(url=data.get("hostedUrl") or "", source="Lever", title=data.get("text", ""), company=company.replace("-", " ").title(),
                   location=cat.get("location", ""), jobType=cat.get("commitment", ""), jd="\n\n".join(p for p in parts if p).strip(),
                   applyUrl=data.get("applyUrl") or data.get("hostedUrl") or "", applyVia="company_site",
                   remote="remote" in (cat.get("location", "") + data.get("workplaceType", "")).lower())


def parse_ashby(board: dict, org: str, job_id: str) -> LinkJob:
    it = next((j for j in board.get("jobs") or [] if j.get("id") == job_id), None)
    if not it:
        raise LinkError("That Ashby job is no longer open.")
    return LinkJob(url=it.get("jobUrl") or "", source="Ashby", title=it.get("title", ""), company=org.replace("-", " ").title(),
                   location=it.get("location", ""), jobType=it.get("employmentType", ""),
                   jd=it.get("descriptionPlain") or _text(it.get("descriptionHtml", "")),
                   applyUrl=it.get("applyUrl") or it.get("jobUrl") or "", applyVia="company_site",
                   remote=bool(it.get("isRemote")), postedAt=it.get("publishedAt") or "")


def parse_generic(raw: str, url: str) -> LinkJob:
    host = urlparse(url).netloc.replace("www.", "")
    job = parse_jsonld(raw) or LinkJob(url="", source="")
    job.url, job.source, job.applyUrl, job.applyVia = url, job.source or host, url, "company_site"
    if not job.title:
        job.title = _first(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', raw) or _first(r"<title>(.*?)</title>", raw)
    if len(job.jd) < 300:
        job.jd = html_to_text(raw)[:9000]
    if len(job.jd) < 300:
        raise LinkError("Couldn't read that page. Paste the job description below and Upajna will carry on.")
    return job


# ---------- fetching ----------
async def _get(c: httpx.AsyncClient, url: str):
    try:
        r = await c.get(url)
    except httpx.HTTPError:
        raise LinkError("Couldn't reach that site just now. Try again, or paste the job description below.")
    if r.status_code == 404:
        raise LinkError("That job is no longer posted.")
    if r.status_code >= 400:
        raise LinkError("That site wouldn't share the job with Upajna. Paste the job description below and it will carry on.")
    return r


def _mock(url: str) -> LinkJob:
    """Offline stand-in used by tests and MOCK_EXTERNAL=true."""
    jd = ("Gather requirements, write user stories and acceptance criteria, run UAT and validate data with SQL. "
          "Work with product and engineering in an Agile team. " * 4)
    if "nosponsor" in url:
        jd += " We are unable to provide visa sponsorship."
    lid = linkedin_id(url)
    if lid:
        easy = lid.endswith("1")
        return LinkJob(url=f"https://www.linkedin.com/jobs/view/{lid}/", source="LinkedIn", title="Business Analyst", company=f"Example Corp {lid[-2:]}",
                       location="Remote", remote=True, jd=jd, applyVia="easy_apply" if easy else "company_site",
                       applyUrl=f"https://www.linkedin.com/jobs/view/{lid}/" if easy else "https://boards.greenhouse.io/example/jobs/777")
    return LinkJob(url=url, source=urlparse(url).netloc, title="Data Engineer", company="Example Data", location="Austin, TX",
                   jd=jd.replace("requirements", "data pipelines"), applyUrl=url, applyVia="company_site")


async def read_job_link(text: str) -> LinkJob:
    url = clean_url(text)
    if get_settings().mock_external:
        return _mock(url)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=UA) as c:
        lid = linkedin_id(url)
        if lid:
            r = await _get(c, f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{lid}")
            return parse_linkedin(r.text, lid)
        if gh := _greenhouse(url):
            r = await _get(c, f"https://boards-api.greenhouse.io/v1/boards/{gh[0]}/jobs/{gh[1]}")
            return parse_greenhouse(r.json(), gh[0])
        if lv := _lever(url):
            r = await _get(c, f"https://api.lever.co/v0/postings/{lv[0]}/{lv[1]}")
            return parse_lever(r.json(), lv[0])
        if ab := _ashby(url):
            r = await _get(c, f"https://api.ashbyhq.com/posting-api/job-board/{ab[0]}?includeCompensation=true")
            return parse_ashby(r.json(), ab[0], ab[1])
        if "linkedin.com" in url:
            raise LinkError("That LinkedIn link doesn't point to a single job. Open the job and copy its link.")
        r = await _get(c, url)
        return parse_generic(r.text, str(r.url))
