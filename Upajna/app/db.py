"""Database: Postgres in production (DATABASE_URL), SQLite locally. Jobs are stored as JSON documents."""
from __future__ import annotations

import copy
import os
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import JSON, DateTime, String, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import get_settings

JsonType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow().isoformat()


class Base(DeclarativeBase):
    pass


class SettingRow(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JsonType)


class JobRow(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    data: Mapped[dict] = mapped_column(JsonType)


class PushSubRow(Base):
    __tablename__ = "push_subs"
    endpoint: Mapped[str] = mapped_column(String(1024), primary_key=True)
    sub: Mapped[dict] = mapped_column(JsonType)


_engine = None
_Session: sessionmaker | None = None


def init_db(url: str | None = None) -> None:
    global _engine, _Session
    url = url or get_settings().sqlalchemy_url
    if url.startswith("sqlite:///"):
        path = url.replace("sqlite:///", "", 1)
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    _engine = create_engine(url, **kwargs)
    Base.metadata.create_all(_engine)
    _Session = sessionmaker(_engine, expire_on_commit=False)


def session() -> Session:
    assert _Session is not None, "init_db() first"
    return _Session()


# ---------- settings ----------
def get_setting(key: str, default: Any = None) -> Any:
    with session() as s:
        row = s.get(SettingRow, key)
        return copy.deepcopy(row.value) if row else default


def set_setting(key: str, value: Any) -> Any:
    with session() as s:
        row = s.get(SettingRow, key)
        if row:
            row.value = value
        else:
            s.add(SettingRow(key=key, value=value))
        s.commit()
    return value


# ---------- jobs ----------
def list_jobs(statuses: Iterable[str] | None = None) -> list[dict]:
    with session() as s:
        q = select(JobRow).order_by(JobRow.found_at.desc())
        if statuses:
            q = q.where(JobRow.status.in_(list(statuses)))
        return [copy.deepcopy(r.data) for r in s.scalars(q)]


def job_ids() -> set[str]:
    with session() as s:
        return set(s.scalars(select(JobRow.id)))


def get_job(job_id: str) -> dict | None:
    with session() as s:
        row = s.get(JobRow, job_id)
        return copy.deepcopy(row.data) if row else None


def put_job(job: dict) -> dict:
    found = job.get("foundAt") or now_iso()
    job = {**job, "foundAt": found}
    with session() as s:
        row = s.get(JobRow, job["id"])
        if row:
            row.status, row.data = job["status"], job
        else:
            s.add(JobRow(id=job["id"], status=job["status"], found_at=datetime.fromisoformat(found.replace("Z", "+00:00")), data=job))
        s.commit()
    return job


def patch_job(job_id: str, **patch: Any) -> dict | None:
    job = get_job(job_id)
    if job is None:
        return None
    job.update(patch)
    job["updatedAt"] = now_iso()
    return put_job(job)


# ---------- push subscriptions ----------
def add_push_sub(sub: dict) -> None:
    with session() as s:
        row = s.get(PushSubRow, sub["endpoint"])
        if row:
            row.sub = sub
        else:
            s.add(PushSubRow(endpoint=sub["endpoint"], sub=sub))
        s.commit()


def list_push_subs() -> list[dict]:
    with session() as s:
        return [r.sub for r in s.scalars(select(PushSubRow))]


def remove_push_sub(endpoint: str) -> None:
    with session() as s:
        row = s.get(PushSubRow, endpoint)
        if row:
            s.delete(row)
            s.commit()
