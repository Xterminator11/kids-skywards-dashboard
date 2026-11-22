"""Logs in to Skyward Family Access with a headless browser and reads the gradebook."""
from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import Error as PlaywrightError, Page, TimeoutError as PlaywrightTimeout, sync_playwright

from ..config import Settings
from ..models import AssignmentRecord, GradeRecord
from .base import GradeSource, LoginError, SourceError
from .skyward_assignments_parser import (
    GradeLink,
    context_comment,
    latest_grade_links,
    merge_assignments,
    parse_assignment_dialog,
    parse_gradebook_assignments,
)
from .skyward_parser import gradebook_unavailable, parse_gradebook, student_options

log = logging.getLogger(__name__)

# Selectors for the standard Skyward SMS 2.0 Family Access pages.
# If your district's page differs, these are the lines to adjust.
SEL_USERNAME = "#login"
SEL_PASSWORD = "#password"
SEL_SIGN_IN = "#bLogin"
SEL_LOGIN_ERROR = "#msgBottom, .validation-error"
SEL_GRADEBOOK_NAV = 'a[data-nav="sfgradebook001.w"]'
SEL_GRADES_READY = '[id^="grid_stuGradesGrid"], a[data-lit]'
# Skyward shows this instead of grades while "All Students" is selected.
SEL_GRADES_SUPPRESSED = "#grid_suppressed"
SEL_STUDENT_LABEL = "#sf_StudentLabel"
SEL_STUDENT_OPEN = "#sf_StudentSelect"
SEL_STUDENT_OPTION = '#sf_StudentList a[data-nameid="{sid}"]'

# Term-grade dialog (opened by clicking a grade). Close buttons tried in order.
# "#sf_message" is Skyward's "Please Wait..." box, not a real dialog.
SEL_DIALOG_CLOSE = (
    "css=.sf_DialogWrap:not(#sf_message) .sf_DialogClose >> visible=true",
    "css=.sf_DialogWrap:not(#sf_message) .sf_DialogCloseLink >> visible=true",
    "css=.ui-dialog-titlebar-close >> visible=true",
)
# Number of dialog boxes on screen that have content. "#sf_message" is excluded.
# Compared before/after a click, so a box that was already showing does not confuse it.
DIALOG_COUNT_JS = """() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  return [...document.querySelectorAll('.sf_DialogWrap, [role="dialog"], .ui-dialog')]
    .filter(d => d.id !== 'sf_message' && !d.parentElement.closest('.sf_DialogWrap, [role="dialog"], .ui-dialog'))
    .filter(d => vis(d) && (d.innerText || '').trim().length > 40).length;
}"""
DIALOG_TIMEOUT_MS = 20_000
MAX_DIALOG_FAILURES = 3  # stop clicking after this many dialogs fail in a row

TIMEOUT_MS = 45_000


class SkywardSource(GradeSource):
    name = "skyward"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tz = ZoneInfo(settings.timezone)
        self.debug_dir = Path(settings.data_dir) / "debug"
        self.raw_dir = Path(settings.data_dir) / "raw"
        self._assignments: list[AssignmentRecord] = []
        self._dialog_pages: list[tuple[GradeLink, str]] = []
        self._stamp = ""

    def fetch_assignments(self) -> list[AssignmentRecord]:
        return list(self._assignments)

    def fetch(self) -> list[GradeRecord]:
        self.settings.require_credentials()
        scraped_at = datetime.now(self.tz)
        self._stamp = f"{scraped_at:%Y-%m-%d_%H%M}"
        self._assignments = []
        self._dialog_pages = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.settings.headless)
            context = browser.new_context()
            context.set_default_timeout(TIMEOUT_MS)
            page = context.new_page()
            try:
                home = self._login(page)
                pages = self._open_gradebook(home)
            except LoginError:
                self._save_debug(context.pages)
                raise
            except Exception as exc:
                self._save_debug(context.pages)
                raise SourceError(f"Skyward scrape failed: {exc}") from exc
            finally:
                context.close()
                browser.close()

        records: list[GradeRecord] = []
        for sid, name, html in pages:
            if self.settings.save_raw_html:
                self.raw_dir.mkdir(parents=True, exist_ok=True)
                suffix = f"_{sid}" if sid else ""
                raw = self.raw_dir / f"gradebook_{scraped_at:%Y-%m-%d_%H%M}{suffix}.html"
                raw.write_text(html, encoding="utf-8")
                log.info("Saved raw gradebook HTML to %s", raw)
            found = parse_gradebook(html, scraped_at)
            if sid:
                # The page was opened for one student, so grades without an id are theirs.
                found = [
                    replace(r, student_id=r.student_id or sid, student=r.student if r.student_id else name)
                    for r in found
                ]
                if not found:
                    log.warning("No grades found for student %s", sid)
            records.extend(found)

        if not records:
            raise SourceError(
                "Logged in and opened the gradebook but found no grades. "
                "Check the raw HTML in data/raw/ (the page layout may differ)."
            )
        log.info("Parsed %d grades for %d student(s)", len(records), len({r.student_id for r in records}))
        if self.settings.fetch_assignments:
            try:
                self._assignments = self._parse_assignments([html for _, _, html in pages], scraped_at)
            except Exception:  # assignments are extra; never lose the grades over them
                log.exception("Could not parse assignments")
        return records

    def _parse_assignments(self, gradebook_pages: list[str], scraped_at: datetime) -> list[AssignmentRecord]:
        on_page: list[AssignmentRecord] = []
        for html in gradebook_pages:
            on_page.extend(parse_gradebook_assignments(html, scraped_at))
        from_dialogs: list[AssignmentRecord] = []
        for link, html in self._dialog_pages:
            found = parse_assignment_dialog(html, scraped_at)
            if not found:
                log.warning("No assignments read from the %s dialog for course %s", link.lit, link.cni)
            from_dialogs.extend(found)
        merged = merge_assignments(from_dialogs, on_page)
        log.info(
            "Parsed %d assignments (%d from %d term-grade dialogs, %d more from the gradebook page)",
            len(merged), len(from_dialogs), len(self._dialog_pages), len(merged) - len(from_dialogs),
        )
        return merged

    def _login(self, page: Page) -> Page:
        log.info("Opening Skyward login page")
        page.goto(self.settings.skyward_url, wait_until="domcontentloaded")
        page.fill(SEL_USERNAME, self.settings.skyward_username)
        page.fill(SEL_PASSWORD, self.settings.skyward_password)

        # Skyward usually opens Family Access in a new popup window after sign-in.
        try:
            with page.context.expect_page(timeout=20_000) as popup_info:
                page.click(SEL_SIGN_IN)
            home = popup_info.value
        except PlaywrightTimeout:
            error = page.locator(SEL_LOGIN_ERROR)
            if error.count() and error.first.is_visible() and error.first.inner_text().strip():
                raise LoginError(f"Login rejected: {error.first.inner_text().strip()}")
            home = page  # some districts load Family Access in the same window

        home.wait_for_load_state("domcontentloaded")
        home.wait_for_selector(SEL_GRADEBOOK_NAV)
        log.info("Logged in")
        return home

    def _open_gradebook(self, home: Page) -> list[tuple[str, str, str]]:
        """Return (student id, name, html) for each gradebook page read.

        With "All Students" selected Skyward hides the gradebook, so pick each child
        from the Student Select list in turn. The id is "" if no picker was needed.
        """
        log.info("Opening gradebook")
        home.click(SEL_GRADEBOOK_NAV)
        home.wait_for_selector(f"{SEL_GRADES_READY}, {SEL_GRADES_SUPPRESSED}", state="attached")
        home.wait_for_load_state("networkidle")
        html = home.content()
        students = student_options(html)
        if not gradebook_unavailable(html) and len(students) <= 1:
            self._read_assignment_dialogs(home, html)
            return [("", "", html)]

        log.info("Found %d student(s); reading each gradebook", len(students))
        pages: list[tuple[str, str, str]] = []
        for sid, name in students:
            self._select_student(home, sid, name)
            home.wait_for_selector(f"{SEL_GRADES_READY}, {SEL_GRADES_SUPPRESSED}", state="attached")
            home.wait_for_load_state("networkidle")
            html = home.content()
            pages.append((sid, name, html))
            self._read_assignment_dialogs(home, html)
        return pages

    # ------------------------------------------------------------ assignment dialogs

    def _read_assignment_dialogs(self, home: Page, html: str) -> None:
        """Click each course's latest term grade and keep the page HTML while its
        assignment dialog is open. Failures are logged and skipped, never fatal."""
        if not self.settings.fetch_assignments:
            return
        links = latest_grade_links(html)
        log.info("Reading assignments for %d course(s)", len(links))
        failures = 0
        for link in links:
            if failures >= MAX_DIALOG_FAILURES:
                log.warning("Stopping assignment dialogs after %d failures in a row", failures)
                return
            try:
                self._read_one_dialog(home, link)
                failures = 0
            except Exception as exc:
                failures += 1
                log.warning("Assignment dialog failed for course %s (%s): %s", link.cni, link.lit, exc)
                self._save_dialog_debug(home, link)
                self._recover(home)
            home.wait_for_timeout(self.settings.assignment_delay_seconds * 1000)

    def _dialog_count(self, home: Page) -> int:
        return int(home.evaluate(DIALOG_COUNT_JS))

    def _read_one_dialog(self, home: Page, link: GradeLink) -> None:
        before = self._dialog_count(home)
        grade = home.locator(link.selector).first
        grade.scroll_into_view_if_needed()
        grade.click()
        home.wait_for_function(f"() => ({DIALOG_COUNT_JS})() > {before}", timeout=DIALOG_TIMEOUT_MS)
        try:
            home.wait_for_load_state("networkidle", timeout=10_000)
        except PlaywrightTimeout:
            pass
        home.wait_for_timeout(500)  # let the dialog finish drawing
        html = context_comment(link) + home.content()
        self._dialog_pages.append((link, html))
        if self.settings.save_raw_html:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            base = self.raw_dir / f"assignments_{self._stamp}_{link.sid}_{link.cni}_{link.sec}_{link.lit}"
            base.with_suffix(".html").write_text(html, encoding="utf-8")
            if len(self._dialog_pages) == 1:
                home.screenshot(path=str(base.with_suffix(".png")))
        log.info("Read %s assignments for course %s", link.lit, link.cni)
        self._close_dialog(home, before)

    def _close_dialog(self, home: Page, target: int) -> None:
        for sel in SEL_DIALOG_CLOSE:
            close = home.locator(sel)
            if close.count():
                close.last.click()
                break
        else:
            home.keyboard.press("Escape")
        home.wait_for_function(f"() => ({DIALOG_COUNT_JS})() <= {target}", timeout=10_000)

    def _recover(self, home: Page) -> None:
        """Get back to a clean gradebook page (the selected student stays selected)."""
        try:
            home.keyboard.press("Escape")
            home.wait_for_timeout(1000)
            if self._dialog_count(home):
                home.click(SEL_GRADEBOOK_NAV)
                home.wait_for_selector(SEL_GRADES_READY, state="attached")
                home.wait_for_load_state("networkidle")
        except Exception:
            log.exception("Could not get back to the gradebook page")

    def _save_dialog_debug(self, home: Page, link: GradeLink) -> None:
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            base = self.debug_dir / f"assignments_failed_{self._stamp}_{link.sid}_{link.cni}_{link.lit}"
            home.screenshot(path=str(base.with_suffix(".png")), full_page=True)
            base.with_suffix(".html").write_text(context_comment(link) + home.content(), encoding="utf-8")
        except Exception:
            log.exception("Could not save dialog debug output")

    def _select_student(self, home: Page, sid: str, name: str) -> None:
        log.info("Selecting student %s", sid)
        option = home.locator(SEL_STUDENT_OPTION.format(sid=sid))
        if not option.is_visible():
            home.click(SEL_STUDENT_OPEN)
            option.wait_for(state="visible")
        # Choosing a student reloads the current page (the gradebook) for that student.
        option.click()
        deadline = time.monotonic() + TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            try:
                home.wait_for_load_state("domcontentloaded")
                label = home.locator(SEL_STUDENT_LABEL).first.inner_text(timeout=2_000)
                if name.upper() in label.upper():
                    return
            except PlaywrightError:
                pass  # page was mid-reload; try again
            home.wait_for_timeout(500)
        raise SourceError(f"Timed out switching to student {sid}")

    def _save_debug(self, pages: list[Page]) -> None:
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(self.tz).strftime("%Y-%m-%d_%H%M%S")
            for i, p in enumerate(pages):
                p.screenshot(path=str(self.debug_dir / f"failure_{stamp}_{i}.png"), full_page=True)
                (self.debug_dir / f"failure_{stamp}_{i}.html").write_text(p.content(), encoding="utf-8")
            log.warning("Saved failure screenshots/HTML to %s", self.debug_dir)
        except Exception:  # never let debugging hide the real error
            log.exception("Could not save debug output")
