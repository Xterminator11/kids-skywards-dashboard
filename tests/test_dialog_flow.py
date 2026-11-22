"""Drives the real click / save / close code against a made-up page in Chromium.

The page's own script stands in for Skyward: clicking a grade opens a term-grade
dialog after a short delay, and its close link removes it. Skipped if Chromium is not
installed (e.g. `uv run playwright install chromium` has not been run).
"""
from pathlib import Path

import pytest

from gradebook.config import Settings
from gradebook.sources.skyward import DIALOG_COUNT_JS, SkywardSource

FIXTURE = Path(__file__).parent / "fixtures" / "skyward_gradebook_assignments.html"
DIALOG = Path(__file__).parent / "fixtures" / "skyward_assignment_dialog.html"


@pytest.fixture()
def page():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # browser not installed
            pytest.skip(f"Chromium not available: {exc}")
        page = browser.new_page()
        page.set_default_timeout(10_000)
        yield page
        browser.close()


def _settings(tmp_path) -> Settings:
    return Settings(
        skyward_url="", skyward_username="", skyward_password="", data_dir=tmp_path,
        schedule_cron="0 17 * * *", timezone="America/Chicago", run_on_start=False,
        save_raw_html=True, headless=True, max_retries=0, retry_delay_minutes=0,
        log_level="INFO", fetch_assignments=True, assignment_delay_seconds=0,
    )


def test_clicks_latest_grade_per_course_saves_and_closes_each_dialog(page, tmp_path):
    page.set_content(FIXTURE.read_text())
    page.evaluate("html => { window.dialogHtml = html; }", DIALOG.read_text())
    source = SkywardSource(_settings(tmp_path))
    source._stamp = "test"

    source._read_assignment_dialogs(page, page.content())

    assert page.evaluate("window.clicked") == ["9001:PR2", "9002:PR1"]
    assert page.evaluate(DIALOG_COUNT_JS) == 0
    assert len(source._dialog_pages) == 2
    saved = sorted(p.name for p in (tmp_path / "raw").glob("assignments_*.html"))
    assert saved == ["assignments_test_2001_9001_02_PR2.html", "assignments_test_2001_9002_03_PR1.html"]
    first = (tmp_path / "raw" / saved[0]).read_text()
    assert first.startswith("<!-- gradebook-assignments sid=2001 cni=9001")
    assert "Homework 5" in first  # dialog content was captured while open
