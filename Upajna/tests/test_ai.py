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
