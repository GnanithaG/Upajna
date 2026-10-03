"""Rules that drop postings before they reach the inbox."""
import re
from typing import Optional

_NO_SPONSOR = [re.compile(p, re.I) for p in [
    r"\b(no|not|unable to|cannot|can ?not|won'?t|will not|do not|does not|don'?t|doesn'?t|are not able to|is not able to)\s+(currently\s+)?(provide|offer|support|consider)?\s*(any\s+)?(h-?1b\s+|visa\s+|work\s+visa\s+|employment\s+)?sponsor",
    r"\bsponsorship\s+(is\s+)?(not\s+(available|offered|provided)|unavailable)",
    r"\bwithout\s+(the\s+need\s+for\s+)?(current\s+or\s+future\s+)?(visa\s+)?sponsorship",
    r"\b(u\.?s\.?|united states)\s+citizens?\s+(only|required)",
    r"\bmust\s+be\s+(a\s+)?(u\.?s\.?|united states)\s+citizen",
    r"\b(only\s+)?(usc|us citizens?)\s*(/|and|or|,)\s*(gc|green card)(\s+holders?)?\s+only",
    r"\bgreen\s*card\s+holders?\s+only",
    r"\b(active\s+)?(secret|top secret|ts/sci|public trust|security)\s+clearance\s+(is\s+)?(required|needed|must)",
    r"\bmust\s+(have|hold|possess)\s+(an?\s+)?(active\s+)?(secret|top secret|ts/sci|security)\s+clearance",
]]


def blocks_sponsorship(text: str) -> Optional[str]:
    """Return the phrase that rules out candidates needing sponsorship, or None."""
    for rx in _NO_SPONSOR:
        m = rx.search(text or "")
        if m:
            return m.group(0).strip()
    return None


def matches_excludes(text: str, excludes: str) -> Optional[str]:
    t = (text or "").lower()
    for w in (excludes or "").split(","):
        w = w.strip().lower()
        if w and w in t:
            return w
    return None


def dedupe_key(job: dict) -> str:
    """Same company + same title = same job, even across boards."""
    def norm(s: str) -> str:
        s = re.sub(r"\b(inc|llc|corp|corporation|ltd|co)\b\.?", "", (s or "").lower())
        return re.sub(r"[^a-z0-9]+", " ", s).strip()
    return f"{norm(job.get('company', ''))}|{norm(job.get('title', ''))}"


_STOP = {"senior", "sr", "junior", "jr", "lead", "staff", "principal", "i", "ii", "iii", "iv", "and", "of"}


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9+#]+", (s or "").lower()) if w not in _STOP}


def title_fits(job_title: str, titles: list[str]) -> bool:
    """Does a posting's title match one of the titles you search for?

    "Data Engineer" matches "Senior Data Platform Engineer" (all its words are there),
    but not "Data Analyst".
    """
    t, tw = (job_title or "").lower(), _words(job_title)
    for x in titles:
        xw = _words(x)
        if x.lower() in t or (xw and xw <= tw):
            return True
    if any("analyst" in x.lower() for x in titles):
        return bool(re.search(r"\b(business|systems?|it|technical|functional|agile)\b.*\banalyst\b", t))
    return False
