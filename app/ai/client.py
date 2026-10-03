"""Claude client: call the Messages API, parse JSON, validate it against a Pydantic schema,
and retry once with the validation error if the model's output doesn't fit."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from string import Template
from typing import Callable, Optional, Type, TypeVar

from anthropic import AsyncAnthropic, APIError
from pydantic import BaseModel, ValidationError

from ..config import get_settings

log = logging.getLogger("upajna.ai")
T = TypeVar("T", bound=BaseModel)
PROMPTS = Path(__file__).parent / "prompts"
_client: Optional[AsyncAnthropic] = None


def client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=get_settings().anthropic_api_key, max_retries=3)
    return _client


def render(name: str, **vars: str) -> str:
    """Load prompts/<name>.md and fill $placeholders (string.Template, so JSON braces are safe)."""
    return Template((PROMPTS / f"{name}.md").read_text()).safe_substitute(**vars)


def extract_json(text: str):
    s = (text or "").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    start = min([i for i in (s.find("{"), s.find("[")) if i >= 0], default=-1)
    end = max(s.rfind("}"), s.rfind("]"))
    if start >= 0 and end > start:
        return json.loads(s[start : end + 1])
    raise ValueError("Claude did not return JSON")


async def ask(
    prompt: str,
    schema: Type[T],
    *,
    model: Optional[str] = None,
    max_tokens: int = 8000,
    wrap_list_as: Optional[str] = None,
    mock: Optional[Callable[[], dict]] = None,
) -> T:
    """Ask Claude for JSON matching `schema`. If Claude returns a bare list and the schema
    wraps it (e.g. {"jobs": [...]}), pass wrap_list_as="jobs"."""
    settings = get_settings()
    if settings.mock_external:
        return schema.model_validate(mock() if mock else {})

    messages = [{"role": "user", "content": prompt}]
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            msg = await client().messages.create(
                model=model or settings.claude_model,
                max_tokens=max_tokens,
                system="You return only valid JSON that matches the requested shape, with no commentary.",
                messages=messages,
            )
        except APIError as e:
            raise RuntimeError(f"Claude API error: {e}") from e
        text = "".join(b.text for b in msg.content if b.type == "text")
        try:
            data = extract_json(text)
            if wrap_list_as and isinstance(data, list):
                data = {wrap_list_as: data}
            return schema.model_validate(data)
        except (ValueError, ValidationError) as e:
            last_err = e
            log.warning("Claude output failed validation (attempt %d): %s", attempt + 1, str(e)[:300])
            messages += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"That JSON didn't match the required shape: {str(e)[:800]}\nReturn the corrected JSON only."},
            ]
    raise RuntimeError(f"Claude returned invalid output: {last_err}")
