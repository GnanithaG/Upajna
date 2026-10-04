"""Auto-apply worker. Fills and (if APPLY_SUBMIT=true) submits approved applications on Greenhouse,
Lever and Ashby, which have public forms that need no sign-in. Anything else (LinkedIn, Indeed,
Workday, CAPTCHAs, required questions without an approved answer) goes back to the user as "needs_you"."""
from __future__ import annotations

import base64
import logging
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse

from .. import db, roles
from ..ai import map_form_fields
from ..config import get_settings
from ..documents import letter_docx, resume_docx

log = logging.getLogger("upajna.apply")
_HERE = Path(__file__).parent


def _js(name: str) -> str:
    return re.sub(r"^//.*\n", "", (_HERE / name).read_text()).strip()


COLLECT_FIELDS = _js("collect_fields.js")
EMPTY_REQUIRED = _js("empty_required.js")
AUTO_ATS = {"greenhouse", "lever", "ashby"}

HANDOFF = {
    "linkedin": "This is a LinkedIn Easy Apply job, which needs your own LinkedIn sign-in. Open it, choose Easy Apply, upload your tailored resume (Resume button) and copy your approved answers.",
    "indeed": "Indeed applications need your own sign-in. Open the application and use your approved answers.",
    "workday": "Workday needs an account on this company's site. Open the application, sign in or create the account, then use your approved answers.",
    "other": "This site isn't one Upajna can fill automatically yet. Open the application and use your approved resume and answers.",
}
CONFIRM = re.compile(r"(thank you for (your )?(applying|application|interest)|thanks for applying|application (has been )?(received|submitted)|we('ve| have) received your application|successfully submitted)", re.I)


def detect_ats(url: str = "") -> str:
    u = url or ""
    if "greenhouse.io" in u or "gh_jid=" in u:
        return "greenhouse"
    if "jobs.lever.co" in u:
        return "lever"
    if "ashbyhq.com" in u:
        return "ashby"
    if "linkedin.com" in u:
        return "linkedin"
    if "indeed.com" in u:
        return "indeed"
    if "myworkdayjobs.com" in u or "workday" in u:
        return "workday"
    return "other"


def apply_page_url(ats: str, url: str) -> str:
    p = urlparse(url)
    path = p.path.rstrip("/")
    if ats == "lever" and not path.endswith("/apply"):
        path += "/apply"
    if ats == "ashby" and not path.endswith("/application"):
        path += "/application"
    return urlunparse(p._replace(path=path))


def _today() -> str:
    return date.today().isoformat()


def _plus(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


async def fill_field(page, f: dict, value, files: dict) -> None:
    """Fill one field found by collect_fields.js (addressed by its data-upajna key)."""
    if value is None or value == "":
        return
    el = page.locator(f'[data-od-key="{f["key"]}"]').first
    try:
        t = f["type"]
        if t == "file":
            path = files.get("resume") if value == "RESUME" else files.get("cover") if value == "COVER_LETTER" else None
            if path:
                await el.set_input_files(path)
        elif t == "select":
            try:
                await el.select_option(label=str(value))
            except Exception:
                await el.select_option(str(value))
        elif t == "radio":
            opt = str(value).replace('"', '\\"')
            await page.locator(f'[data-od-key="{f["key"]}"][data-od-opt="{opt}"]').first.check(force=True)
        elif t == "checkbox":
            if value is True or str(value).lower() == "true":
                await el.check(force=True)
        elif t == "combobox":
            await el.click()
            await el.fill(str(value))
            await page.wait_for_timeout(600)
            option = page.locator("[role='option']").filter(has_text=str(value)).first
            if await option.count():
                await option.click()
            else:
                await el.press("Enter")
        else:
            await el.fill(str(value))
    except Exception as e:  # the required-field check afterwards catches anything left empty
        log.debug("could not fill %s: %s", f.get("label"), e)


async def _captcha_blocking(page) -> bool:
    if not any(re.search(r"recaptcha/.*bframe|hcaptcha\.com.*challenge|challenges\.cloudflare\.com", fr.url) for fr in page.frames):
        return False
    try:
        return await page.locator("iframe[src*='bframe'], iframe[src*='hcaptcha'], iframe[src*='challenges.cloudflare']").first.is_visible()
    except Exception:
        return False


async def _shot(page) -> str:
    try:
        return "data:image/jpeg;base64," + base64.b64encode(await page.screenshot(type="jpeg", quality=45)).decode()
    except Exception:
        return ""


async def apply_one(job_id: str) -> str:
    """Returns 'submitted', 'needs_you', 'closed' or 'skipped'."""
    settings = get_settings()
    job = db.get_job(job_id)
    if not job or job["status"] != "ready":
        return "skipped"
    ats = detect_ats(job.get("applyUrl") or job.get("url") or "")
    if ats not in AUTO_ATS:
        note = HANDOFF.get(ats, HANDOFF["other"])
        if ats == "linkedin" and job.get("applyVia") != "easy_apply":
            note = (f"This job applies on {job.get('company') or 'the company'}'s own website, but LinkedIn hides that address from Upajna. "
                    "On LinkedIn, click Apply, copy the address of the page that opens, and paste it below.")
        db.patch_job(job_id, status="needs_you", note=note)
        return "needs_you"
    db.patch_job(job_id, status="applying", note="")

    profile = db.get_setting("profile") or {}
    resume_text, _ = roles.resume_for(job)
    r = job.get("result") or {}
    with tempfile.TemporaryDirectory(prefix="upajna-") as tmp:
        base = r.get("fileBase") or "Resume"
        files = {"resume": str(Path(tmp) / f"{base}.docx")}
        Path(files["resume"]).write_bytes(resume_docx(r.get("resume") or {}, profile.get("name", "")))
        if r.get("coverLetter"):
            files["cover"] = str(Path(tmp) / f"{base.replace('_Resume_', '_CoverLetter_')}.docx")
            Path(files["cover"]).write_bytes(letter_docx(r["coverLetter"]))

        if settings.mock_external:
            if settings.apply_submit:
                db.patch_job(job_id, status="submitted", appliedAt=_today(), followUp=_plus(7), trackerStatus="Applied", submitNote="Mock submission")
                return "submitted"
            db.patch_job(job_id, status="needs_you", note="Dry run: form filled but not submitted (APPLY_SUBMIT is off).")
            return "needs_you"

        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                ctx = await browser.new_context(viewport={"width": 1280, "height": 1600},
                                                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36")
                page = await ctx.new_page()
                await page.goto(apply_page_url(ats, job.get("applyUrl") or job["url"]), wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2500)

                # Greenhouse embedded on a company site: open the iframe's own page.
                gh = page.locator("iframe#grnhse_iframe, iframe[src*='greenhouse.io']").first
                if await gh.count():
                    src = await gh.get_attribute("src")
                    if src:
                        await page.goto(src, wait_until="domcontentloaded")
                        await page.wait_for_timeout(2000)
                # Some pages need an "Apply" click to reveal the form.
                btn = page.get_by_role("button", name=re.compile(r"^apply( for this job| now)?$", re.I)).first
                if await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(1500)

                body = await page.locator("body").inner_text()
                if re.search(r"closed|no longer (accepting|available)|position has been filled|job not found", body, re.I):
                    db.patch_job(job_id, status="closed", note="This posting is closed.")
                    return "closed"

                fields = await page.evaluate(COLLECT_FIELDS, "form")
                if not fields:
                    db.patch_job(job_id, status="needs_you", note="Couldn't find the application form on this page.", shot=await _shot(page))
                    return "needs_you"

                mapped = await map_form_fields(fields, job, profile, resume_text)
                for f in fields:
                    await fill_field(page, f, mapped.values.get(f["key"]), files)
                await page.wait_for_timeout(800)

                required = [f["key"] for f in fields if f.get("required")]
                empty = set(await page.evaluate(EMPTY_REQUIRED, required))
                missing = list(dict.fromkeys(mapped.missing + [f["label"] for f in fields if f["key"] in empty]))
                if missing:
                    db.patch_job(job_id, status="needs_you", note="These required questions need you: " + "; ".join(missing[:6]), shot=await _shot(page))
                    return "needs_you"
                if await _captcha_blocking(page):
                    db.patch_job(job_id, status="needs_you", note="The site is showing a CAPTCHA. Open the application to finish it.", shot=await _shot(page))
                    return "needs_you"
                if not settings.apply_submit:
                    db.patch_job(job_id, status="needs_you", shot=await _shot(page),
                                 note="Dry run: every field was filled, but nothing was submitted because APPLY_SUBMIT is off. Check the screenshot.")
                    return "needs_you"

                submit = page.locator("button[type='submit'], input[type='submit'], button:has-text('Submit Application'), button:has-text('Submit application'), #btn-submit").first
                await submit.click(timeout=10000)
                confirmed = False
                for _ in range(25):
                    await page.wait_for_timeout(1000)
                    text = await page.locator("body").inner_text()
                    if CONFIRM.search(text) or re.search(r"confirmation|thank", page.url, re.I):
                        confirmed = True
                        break
                    if await _captcha_blocking(page):
                        break
                if confirmed:
                    db.patch_job(job_id, status="submitted", appliedAt=_today(), followUp=_plus(7), trackerStatus="Applied",
                                 submitNote="Confirmation page shown", note="", shot=await _shot(page))
                    return "submitted"
                errs = " ".join(await page.locator("[class*='error'], [role='alert'], .invalid-feedback").all_inner_texts())[:200]
                db.patch_job(job_id, status="needs_you", possiblySubmitted=not errs, shot=await _shot(page),
                             note=f"The form reported: {errs}" if errs else "Clicked Submit but didn't see a confirmation. Check your email for a confirmation before trying again.")
                return "needs_you"
            finally:
                await browser.close()
