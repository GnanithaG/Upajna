"""Upajna API server: phone app, REST API, scheduled job search, tailoring and apply workers."""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Body, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, db, push, roles, workers
from .ai import file_base
from .apply import detect_ats
from .config import get_settings
from .documents import letter_docx, read_resume, resume_docx
from .search import DEFAULT_SEARCH, is_running, run_search
from .search.filters import blocks_sponsorship, dedupe_key
from .search.links import LinkError, clean_url, read_job_link

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("upajna")
STATIC = Path(__file__).resolve().parent.parent / "static"
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    db.init_db()
    if s.missing():
        log.warning("Missing settings: %s", ", ".join(s.missing()))

    async def scheduled():
        try:
            await run_search("scheduled")
        except Exception:
            log.exception("scheduled search failed")

    scheduler.add_job(scheduled, CronTrigger.from_crontab(s.search_cron, timezone=s.tz_name), id="search", replace_existing=True)
    scheduler.start()
    workers.resume_queues()
    yield
    scheduler.shutdown(wait=False)


API_DESCRIPTION = """
The contract between Upajna's web page and its server.

Every screen in the app is built from these endpoints. Sign in with **POST /api/login** first:
it sets a session cookie, and every other `/api` endpoint needs that cookie (otherwise **401**).

Errors always come back as `{"error": "message"}`.
"""

TAGS = [
    {"name": "Auth", "description": "Sign in and out. The session is a signed cookie."},
    {"name": "Status & settings", "description": "What the server is doing, and your saved search filters and profile."},
    {"name": "Roles & resumes", "description": "The kinds of jobs you want, each with its own search titles and master resume."},
    {"name": "Jobs", "description": "The inbox: list, add, skip and tailor jobs."},
    {"name": "Review & apply", "description": "Edit answers, approve, retry and download tailored documents."},
    {"name": "Search & notifications", "description": "Run a search now and register a phone for push notifications."},
]

app = FastAPI(title="Upajna API", version="1.0", description=API_DESCRIPTION, openapi_tags=TAGS, lifespan=lifespan)
api = APIRouter(prefix="/api", dependencies=[Depends(auth.require_auth)])


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


def light(j: dict) -> dict:
    """Job without the heavy screenshot, plus which application system it uses."""
    out = {k: v for k, v in j.items() if k != "shot"}
    out["hasShot"] = bool(j.get("shot"))
    out["ats"] = detect_ats(j.get("applyUrl") or j.get("url") or "")
    return out


# ---------- auth ----------
class LoginBody(BaseModel):
    password: str = ""


@app.post("/api/login", tags=["Auth"], summary="Sign in and get a session cookie")
def login(body: LoginBody, request: Request, response: Response):
    auth.login(request, response, body.password)
    return {"ok": True}


@app.post("/api/logout", tags=["Auth"], summary="Sign out (clears the cookie)")
def logout(response: Response):
    auth.logout(response)
    return {"ok": True}


@app.get("/api/health", tags=["Status & settings"], summary="Is the server up? (no sign-in needed)")
def health():
    return {"ok": True}


# ---------- status & settings ----------
@api.get("/status", tags=["Status & settings"], summary="Search state, schedule, which keys are set")
def status():
    s = get_settings()
    return {
        "missing": s.missing(), "searching": is_running(), "searchState": db.get_setting("searchState") or {},
        "sources": {"jsearch": bool(s.jsearch_api_key), "adzuna": bool(s.adzuna_app_id and s.adzuna_app_key)},
        "applySubmit": s.apply_submit, "push": push.enabled(), "vapidPublic": s.vapid_public_key,
        "schedule": s.search_cron, "timezone": s.tz_name,
    }


SETTINGS = ("profile", "search")


@api.get("/settings", tags=["Status & settings"], summary="Get profile and search settings")
def get_settings_all():
    return {k: db.get_setting(k) or (DEFAULT_SEARCH if k == "search" else {}) for k in SETTINGS}


@api.put("/settings/{name}", tags=["Status & settings"], summary="Save one settings group (profile or search)")
def put_setting(name: str, body: dict[str, Any] = Body(...)):
    if name not in SETTINGS:
        raise HTTPException(404, "Unknown setting")
    nxt = {**(db.get_setting(name) or {}), **body, "updatedAt": db.now_iso()}
    return db.set_setting(name, nxt)


# ---------- roles & resumes ----------
class RoleIn(BaseModel):
    id: str = ""
    name: str
    titles: list[str] = []
    resume: str = ""


def _public_role(r: dict) -> dict:
    return {**r, "ready": len(r.get("resume", "")) >= roles.MIN_RESUME and bool(r.get("titles"))}


@api.get("/roles", tags=["Roles & resumes"], summary="Your roles, each with search titles and a master resume")
def get_roles():
    return [_public_role(r) for r in roles.get_roles()]


@api.put("/roles", tags=["Roles & resumes"], summary="Save all roles (add, rename, remove, edit titles or resume text)")
def put_roles(body: list[RoleIn]):
    if not body:
        raise HTTPException(400, "Keep at least one role.")
    if len(body) > roles.MAX_ROLES:
        raise HTTPException(400, f"You can have up to {roles.MAX_ROLES} roles.")
    old = {r["id"]: r for r in roles.get_roles()}
    out, used = [], set()
    for r in body:
        name = r.name.strip()
        if not name:
            raise HTTPException(400, "Every role needs a name.")
        rid = r.id or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "role"
        while rid in used:
            rid += "-2"
        used.add(rid)
        prev = old.get(rid, {})
        changed = r.resume != prev.get("resume", "")
        out.append({"id": rid, "name": name[:60], "titles": [t.strip() for t in r.titles if t.strip()][:12],
                    "resume": r.resume[:30000],
                    "fileName": "" if changed else prev.get("fileName", ""),
                    "updatedAt": db.now_iso() if changed else prev.get("updatedAt", "")})
    return [_public_role(r) for r in roles.save_roles(out)]


@api.post("/roles/{role_id}/resume", tags=["Roles & resumes"], summary="Upload a PDF, DOCX or TXT resume for one role")
async def upload_resume(role_id: str, file: UploadFile = File(...)):
    all_roles = roles.get_roles()
    role = next((r for r in all_roles if r["id"] == role_id), None)
    if not role:
        raise HTTPException(404, "Unknown role")
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "That file is over 5 MB.")
    text = read_resume(data, file.filename or "")
    if len(text) < roles.MIN_RESUME:
        raise HTTPException(422, "Couldn't read enough text from that file. If it's a scanned PDF, paste the text instead.")
    role.update(resume=text, fileName=file.filename or "", updatedAt=db.now_iso())
    roles.save_roles(all_roles)
    return _public_role(role)


# ---------- jobs ----------
@api.get("/jobs", tags=["Jobs"], summary="List jobs, optionally filtered by status")
def list_jobs(status: Optional[str] = None):
    statuses = status.split(",") if status else None
    return [light(j) for j in db.list_jobs(statuses) if statuses or j["status"] != "skipped"]


@api.get("/jobs/{job_id}", tags=["Jobs"], summary="One job with its full tailoring result")
def get_job(job_id: str):
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return {**j, "ats": detect_ats(j.get("applyUrl") or j.get("url") or "")}


class NewJob(BaseModel):
    url: str = ""          # a job link: LinkedIn, Greenhouse, Lever, Ashby or any careers page
    jd: str = ""           # optional; only needed when the link can't be read
    title: str = ""
    company: str = ""
    role: str = ""         # which resume to use; empty = pick automatically
    force: bool = False    # add it even if the posting says it won't sponsor


@api.post("/jobs", tags=["Jobs"], summary="Add a job from a link (or pasted description) and start tailoring it", status_code=201)
async def add_job(body: NewJob):
    found: dict[str, Any] = {}
    if body.url and len(body.jd) < 150:
        try:
            found = (await read_job_link(body.url)).as_job()
        except LinkError as e:
            # 422 + needsText tells the page to show the "paste the description" box.
            return JSONResponse({"error": str(e), "needsText": True}, status_code=422)
    elif len(body.jd) < 150:
        raise HTTPException(400, "Paste a job link, or the full job description.")
    try:
        url = found.get("url") or (clean_url(body.url) if body.url else "")
    except LinkError:
        url = ""
    job = {"source": "Added by you", "title": body.title or "New job", "company": body.company, "location": "",
           "url": url, "applyUrl": url, "jd": body.jd, **{k: v for k, v in found.items() if v not in ("", None)}}
    job["jd"] = job["jd"][:9000]

    # Same job already in Upajna? Don't add it twice.
    key = dedupe_key(job)
    dup = next((j for j in db.list_jobs() if (url and j.get("url") == url) or (job["company"] and j.get("dedupeKey") == key)), None)
    if dup:
        return JSONResponse({**light(dup), "duplicate": True}, status_code=200)

    search = {**DEFAULT_SEARCH, **(db.get_setting("search") or {})}
    blocked = blocks_sponsorship(job["jd"]) if search.get("sponsorship") == "needs" else None
    if blocked and not body.force:
        return JSONResponse({"error": f'This posting says "{blocked}", so it likely won\'t sponsor a visa.', "blocked": blocked}, status_code=409)

    all_roles = roles.get_roles()
    role = body.role if any(r["id"] == body.role for r in all_roles) else roles.classify(job["title"], all_roles, text=job["jd"])
    job_id = ("l-" if found else "m-") + format(int(db.utcnow().timestamp() * 1000), "x")
    job = db.put_job({**job, "id": job_id, "dedupeKey": key, "status": "new", "fit": {}, "role": role, "foundAt": db.now_iso()})
    workers.enqueue_tailor([job_id])
    return light(job)


class Ids(BaseModel):
    ids: list[str] = []


@api.post("/jobs/skip", tags=["Jobs"], summary="Skip jobs (hide them from the inbox)")
def skip(body: Ids):
    for i in body.ids:
        db.patch_job(i, status="skipped", jd="")
    return {"ok": True}


@api.post("/jobs/tailor", tags=["Jobs"], summary="Queue jobs for tailoring (runs in the background)", status_code=202)
async def tailor(body: Ids):
    missing = []
    for i in body.ids:
        job = db.get_job(i)
        if job:
            text, role = roles.resume_for(job)
            if len(text) < roles.MIN_RESUME:
                missing.append((role or {}).get("name", "this role"))
    if missing:
        raise HTTPException(400, f"Add your {sorted(set(missing))[0]} resume in Settings first.")
    workers.enqueue_tailor(body.ids)
    return {"ok": True}


class JobPatch(BaseModel):
    answers: Optional[list[dict]] = None
    coverLetter: Optional[str] = None
    trackerStatus: Optional[str] = None
    applyUrl: Optional[str] = None
    markSubmitted: bool = False
    status: Optional[str] = None
    role: Optional[str] = None


@api.patch("/jobs/{job_id}", tags=["Review & apply"], summary="Change answers, cover letter, tracker status or role")
def patch_job(job_id: str, body: JobPatch):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    patch: dict[str, Any] = {}
    if body.answers is not None or body.coverLetter is not None:
        result = dict(job.get("result") or {})
        if body.answers is not None:
            result["answers"] = body.answers
        if body.coverLetter is not None:
            result["coverLetter"] = body.coverLetter
        patch["result"] = result
    if body.trackerStatus:
        patch["trackerStatus"] = body.trackerStatus
    if body.applyUrl:
        patch["applyUrl"] = body.applyUrl
    if body.markSubmitted:
        patch.update(status="submitted", appliedAt=date.today().isoformat(), followUp=(date.today() + timedelta(days=7)).isoformat(), trackerStatus="Applied", note="")
    if body.status in ("new", "skipped"):
        patch["status"] = body.status
    if body.role:
        if not any(r["id"] == body.role for r in roles.get_roles()):
            raise HTTPException(400, "Unknown role")
        patch["role"] = body.role
    return light(db.patch_job(job_id, **patch))


class Approval(BaseModel):
    answers: Optional[list[dict]] = None
    coverLetter: Optional[str] = None


@api.post("/jobs/{job_id}/approve", tags=["Review & apply"], summary="Approve a tailored job and queue it to apply", status_code=202)
async def approve(job_id: str, body: Approval):
    job = db.get_job(job_id)
    if not job or not job.get("result"):
        raise HTTPException(400, "Tailor this job before approving it.")
    ats = detect_ats(job.get("applyUrl") or job.get("url") or "")
    if job["status"] in ("ready", "applying"):
        # Same request twice (double tap, retry on bad signal): already queued, so don't queue again.
        return {"ok": True, "ats": ats, "willSubmit": get_settings().apply_submit, "alreadyApproved": True}
    if job["status"] != "review":
        raise HTTPException(409, "This job was already approved. Use Retry in the Tracker instead.")
    answers =body.answers if body.answers is not None else job["result"].get("answers", [])
    if any(str(a.get("answer", "")).upper().startswith("ASK ME") for a in answers):
        raise HTTPException(400, "Fill in the answers marked ASK ME first.")
    result = {**job["result"], "answers": answers}
    if body.coverLetter is not None:
        result["coverLetter"] = body.coverLetter
    db.patch_job(job_id, status="ready", approvedAt=db.now_iso(), result=result, note="")
    workers.enqueue_apply([job_id])
    return {"ok": True, "ats": ats, "willSubmit": get_settings().apply_submit}


@api.post("/jobs/{job_id}/retry", tags=["Review & apply"], summary="Try applying again after a problem", status_code=202)
async def retry(job_id: str):
    db.patch_job(job_id, status="ready", note="", possiblySubmitted=False)
    workers.enqueue_apply([job_id])
    return {"ok": True}


@api.get("/jobs/{job_id}/{kind}.docx", tags=["Review & apply"], summary="Download the tailored resume or cover letter")
def download(job_id: str, kind: str):
    job = db.get_job(job_id)
    if not job or not job.get("result"):
        raise HTTPException(404, "Not tailored yet")
    profile = db.get_setting("profile") or {}
    base = job["result"].get("fileBase") or file_base(profile.get("name", ""), job.get("company", ""), job.get("title", ""))
    if kind == "cover":
        data, name = letter_docx(job["result"].get("coverLetter", "")), base.replace("_Resume_", "_CoverLetter_")
    else:
        data, name = resume_docx(job["result"].get("resume") or {}, profile.get("name", "")), base
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{name}.docx"'})


# ---------- search & push ----------
@api.post("/search/run", tags=["Search & notifications"], summary="Start a job search now (runs in the background)", status_code=202)
async def search_now():
    import asyncio

    if not is_running():
        async def go():
            try:
                await run_search("manual")
            except Exception:
                log.exception("manual search failed")
        asyncio.create_task(go())
    return {"ok": True, "started": True}


@api.post("/push/subscribe", tags=["Search & notifications"], summary="Register this device for push notifications")
def subscribe(sub: dict[str, Any] = Body(...)):
    if not sub.get("endpoint"):
        raise HTTPException(400, "Bad subscription")
    db.add_push_sub(sub)
    return {"ok": True}


app.include_router(api)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    f = STATIC / path
    if path and f.is_file() and STATIC in f.resolve().parents:
        return FileResponse(f)
    if path.startswith("api/"):
        raise HTTPException(404, "Not found")
    return FileResponse(STATIC / "index.html")
