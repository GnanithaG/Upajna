"""Typed schemas for everything Claude returns. Every response is validated before the app uses it."""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

FitLevel = Literal["Strong", "Moderate", "Stretch"]


def _level(v: str) -> str:
    v = (v or "").strip().capitalize()
    return v if v in ("Strong", "Moderate", "Stretch") else "Moderate"


# ---------- job scoring (search pipeline) ----------
class JobScore(BaseModel):
    id: str
    score: int = Field(ge=0, le=100)
    level: FitLevel = "Moderate"
    reason: str = ""
    exclude_reason: str = Field("", alias="excludeReason")

    model_config = {"populate_by_name": True}
    _norm = field_validator("level", mode="before")(_level)

    @field_validator("score", mode="before")
    @classmethod
    def clamp(cls, v):
        return max(0, min(100, int(float(v or 0))))


class JobScores(BaseModel):
    jobs: list[JobScore]


# ---------- tailoring ----------
class Fit(BaseModel):
    level: FitLevel = "Moderate"
    score: int = Field(0, ge=0, le=100)
    reason: str = ""
    strengths: list[str] = []
    gaps: list[str] = []
    _norm = field_validator("level", mode="before")(_level)


class Keyword(BaseModel):
    term: str
    found: bool = False


class Ats(BaseModel):
    score: int = Field(0, ge=0, le=100)
    missing: list[str] = []


class SkillGroup(BaseModel):
    group: str
    items: list[str] = []


class Experience(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    dates: str = ""
    bullets: list[str] = []


class Education(BaseModel):
    degree: str = ""
    school: str = ""
    dates: str = ""
    details: str = ""


class ExtraSection(BaseModel):
    heading: str = ""
    items: list[str] = []


class Resume(BaseModel):
    name: str = ""
    headline: str = ""
    contact: list[str] = []
    summary: str = ""
    skills: list[SkillGroup] = []
    experience: list[Experience] = []
    education: list[Education] = []
    extra: list[ExtraSection] = []


class Answer(BaseModel):
    question: str
    answer: str


class TailorResult(BaseModel):
    company: str = ""
    role: str = ""
    location: str = ""
    fit: Fit = Fit()
    keywords: list[Keyword] = []
    ats: Ats = Ats()
    resume: Resume
    coverLetter: str = ""
    answers: list[Answer] = []
    changes: list[str] = []
    fileBase: str = ""


# ---------- filling application forms ----------
FieldValue = Union[str, bool, None]


class FormFill(BaseModel):
    values: dict[str, FieldValue] = {}
    missing: list[str] = []
