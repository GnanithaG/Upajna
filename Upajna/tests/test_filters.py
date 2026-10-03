import pytest

from app.search.filters import blocks_sponsorship, dedupe_key, matches_excludes, title_fits

BLOCKED = [
    "We do not provide visa sponsorship for this role.",
    "Unable to sponsor H-1B at this time.",
    "Candidates must be a US citizen.",
    "US Citizens only.",
    "USC/GC only",
    "Active Secret clearance required.",
    "Sponsorship is not available.",
    "Must be authorized to work in the US without sponsorship.",
]
ALLOWED = ["We sponsor H-1B visas.", "Visa sponsorship available for the right candidate.", "Experience with SQL and UAT."]


@pytest.mark.parametrize("text", BLOCKED)
def test_blocks_no_sponsorship_postings(text):
    assert blocks_sponsorship(text)


@pytest.mark.parametrize("text", ALLOWED)
def test_allows_other_postings(text):
    assert blocks_sponsorship(text) is None


def test_dedupe_same_job_across_boards():
    a = {"company": "Acme, Inc.", "title": "Senior Business Analyst"}
    b = {"company": "ACME Inc", "title": "Senior Business Analyst "}
    assert dedupe_key(a) == dedupe_key(b)


def test_title_and_excludes():
    titles = ["Business Analyst"]
    assert title_fits("Sr. Business Analyst II", titles)
    assert title_fits("IT Systems Analyst", titles)
    assert not title_fits("Software Engineer", titles)
    assert matches_excludes("Requires Salesforce CPQ", "salesforce, sap") == "salesforce"
