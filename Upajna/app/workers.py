"""In-process background queues for tailoring and applying (one at a time, survive restarts via DB status)."""
from __future__ import annotations

import asyncio
import logging

from . import db, roles
from .ai import tailor_job
from .apply import apply_one
from .config import get_settings
from .push import notify
from .search.adzuna import fetch_full_description

log = logging.getLogger("upajna.workers")


class Queue:
    def __init__(self, name: str, handler, on_idle=None):
        self.name, self.handler, self.on_idle = name, handler, on_idle
        self.q: asyncio.Queue[str] = asyncio.Queue()
        self.pending: set[str] = set()
        self.task: asyncio.Task | None = None
        self.results: list[str] = []

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run(), name=self.name)

    def put(self, job_id: str) -> None:
        if job_id not in self.pending:
            self.pending.add(job_id)
            self.q.put_nowait(job_id)
        self.start()

    async def _run(self) -> None:
        while True:
            job_id = await self.q.get()
            try:
                self.results.append(await self.handler(job_id))
            except Exception as e:
                log.exception("%s failed for %s", self.name, job_id)
                await self._fail(job_id, e)
            finally:
                self.pending.discard(job_id)
                self.q.task_done()
            if self.q.empty() and self.on_idle:
                results, self.results = self.results, []
                await self.on_idle(results)

    async def _fail(self, job_id: str, e: Exception) -> None:
        if self.name == "tailor":
            db.patch_job(job_id, status="new", error=f"Tailoring failed: {str(e)[:160]}")
        else:
            db.patch_job(job_id, status="needs_you", note=f"Something went wrong while applying: {str(e)[:160]}")
            self.results.append("needs_you")


# ---------- tailoring ----------
async def _tailor(job_id: str) -> str:
    job = db.get_job(job_id)
    if not job:
        return "missing"
    profile = db.get_setting("profile") or {}
    resume, role = roles.resume_for(job)
    if len(resume) < roles.MIN_RESUME:
        raise ValueError(f"Add your {(role or {}).get('name', 'master')} resume in Settings first.")
    # Adzuna gives short descriptions; try the full posting first.
    if job.get("jdShort") and job.get("url") and not get_settings().mock_external:
        text, final_url = await fetch_full_description(job["url"])
        if len(text) > len(job.get("jd", "")) + 300:
            job = db.patch_job(job_id, jd=text, jdShort=False, applyUrl=final_url or job.get("applyUrl"))
    result = (await tailor_job(job, profile, resume)).model_dump()
    fit = job.get("fit") or {}
    db.patch_job(
        job_id, status="review", result=result, tailoredAt=db.now_iso(), error="", role=(role or {}).get("id", job.get("role", "")),
        title=job.get("title") or result["role"], company=job.get("company") or result["company"],
        location=job.get("location") or result["location"],
        fit=fit if fit.get("score") else {"score": result["fit"]["score"], "level": result["fit"]["level"], "reason": result["fit"]["reason"]},
    )
    return "review"


async def _applied(results: list[str]) -> None:
    submitted, needs = results.count("submitted"), results.count("needs_you")
    if submitted or needs:
        title = f"Submitted {submitted} application{'s' if submitted != 1 else ''}" if submitted else "Applications need you"
        body = ", ".join(x for x in (f"{submitted} submitted" if submitted else "", f"{needs} need{'s' if needs == 1 else ''} you" if needs else "") if x)
        await notify(title, body, "/#tracker")


tailor_queue = Queue("tailor", _tailor)
apply_queue = Queue("apply", apply_one, on_idle=_applied)


def enqueue_tailor(ids: list[str]) -> None:
    for i in ids:
        db.patch_job(i, status="tailoring", error="")
        tailor_queue.put(i)


def enqueue_apply(ids: list[str]) -> None:
    for i in ids:
        apply_queue.put(i)


def resume_queues() -> None:
    """After a restart, pick up anything that was in flight."""
    for j in db.list_jobs(["tailoring"]):
        tailor_queue.put(j["id"])
    for j in db.list_jobs(["applying"]):
        db.patch_job(j["id"], status="ready")
    for j in db.list_jobs(["ready"]):
        apply_queue.put(j["id"])
