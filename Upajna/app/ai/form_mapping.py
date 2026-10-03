"""Map the fields found on an application form to the candidate's approved answers."""
import json

from .client import ask, render
from .schemas import FormFill


async def map_form_fields(fields: list[dict], job: dict, profile: dict, resume_text: str) -> FormFill:
    result = job.get("result") or {}
    details = {k: v for k, v in profile.items() if k != "answers"}
    prompt = render(
        "fill_form",
        fields=json.dumps(fields),
        profile=json.dumps(details) + "\nStandard answers: " + (profile.get("answers") or ""),
        answers=json.dumps(result.get("answers") or []),
        has_cover="yes" if result.get("coverLetter") else "no",
        resume=json.dumps(result.get("resume") or {})[:5000] + "\n" + resume_text[:2000],
    )
    return await ask(prompt, FormFill, max_tokens=4000, mock=lambda: {"values": {}, "missing": []})
