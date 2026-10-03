"""Reads and fills a Greenhouse-style application form in a real browser.
Skipped automatically when Chromium isn't installed (it is in the Docker image).
Locally: `playwright install chromium`, or set CHROME_PATH to an existing Chrome."""
import asyncio
import os

import pytest

from app.apply.worker import COLLECT_FIELDS, EMPTY_REQUIRED, fill_field

FORM = """<!doctype html><html><body><form id="application-form">
<div class="field"><label for="first_name">First Name *</label><input id="first_name" required></div>
<div class="field"><label for="last_name">Last Name *</label><input id="last_name" required></div>
<div class="field"><label for="email">Email *</label><input id="email" type="email" required></div>
<div class="field"><label for="phone">Phone</label><input id="phone" type="tel"></div>
<div class="field"><label for="resume">Resume/CV *</label><input id="resume" type="file" required></div>
<div class="field"><label for="q1">Will you now or in the future require sponsorship? *</label>
  <select id="q1" required><option value="">Select...</option><option>Yes</option><option>No</option></select></div>
<fieldset class="field"><legend>Are you legally authorized to work in the United States? *</legend>
  <label><input type="radio" name="auth" value="1" required> Yes</label><label><input type="radio" name="auth" value="0"> No</label></fieldset>
<div class="field"><label for="why">Why do you want to work here? *</label><textarea id="why" required></textarea></div>
<div class="field"><label for="cpa">Do you hold an active CPA license? *</label><input id="cpa" required></div>
<div class="field"><label><input type="checkbox" id="privacy" required> I agree to the privacy policy</label></div>
<button type="submit">Submit Application</button></form></body></html>"""


async def _run(tmp_path):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(executable_path=os.environ.get("CHROME_PATH") or None, args=["--no-sandbox"])
        except Exception as e:
            pytest.skip(f"Chromium not available: {e}")
        page = await browser.new_page()
        await page.set_content(FORM)
        fields = await page.evaluate(COLLECT_FIELDS, "form")
        by = lambda word: next(f for f in fields if word in f["label"])
        assert len(fields) == 10
        assert by("authorized")["type"] == "radio" and by("authorized")["options"] == ["Yes", "No"]
        assert by("sponsorship")["options"] == ["Yes", "No"]
        assert by("First Name")["required"] and by("Resume")["type"] == "file" and not by("Phone")["required"]

        resume = tmp_path / "Resume.docx"
        resume.write_bytes(b"x")
        values = {by("First Name")["key"]: "Lakshmi", by("Last Name")["key"]: "Guttikonda", by("Email")["key"]: "l@example.com",
                  by("Phone")["key"]: "+1 555 0100", by("Resume")["key"]: "RESUME", by("sponsorship")["key"]: "Yes",
                  by("authorized")["key"]: "Yes", by("Why")["key"]: "Because", by("privacy")["key"]: True}
        for f in fields:
            await fill_field(page, f, values.get(f["key"]), {"resume": str(resume)})
        empty = await page.evaluate(EMPTY_REQUIRED, [f["key"] for f in fields if f["required"]])
        assert [f["label"] for f in fields if f["key"] in empty] == ["Do you hold an active CPA license?"]
        assert await page.input_value("#q1") == "Yes"
        assert await page.is_checked("input[name=auth][value='1']") and await page.is_checked("#privacy")
        assert await page.evaluate("document.querySelector('#resume').files.length") == 1
        await browser.close()


def test_form_filler(tmp_path):
    asyncio.run(_run(tmp_path))
