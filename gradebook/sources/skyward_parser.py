"""Turns a rendered Skyward Family Access gradebook page (HTML) into GradeRecords.

This is kept separate from the browser code so it can be tested against saved HTML
and re-run on old pages (see `python -m gradebook parse <file>`).

Skyward (SMS 2.0) renders each student's gradebook as a grid with id
"grid_stuGradesGrid_<studentId>_<entity>". Grades are links carrying
data-lit (term label), data-cni (course id) and data-sid (student id). Course names
sit in a separate left-hand table whose rows line up with the grade rows.
"""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from ..models import GradeRecord

GRID_ID = re.compile(r"^grid_stuGradesGrid_(?P<sid>[^_]+)")
# Newer layout: one small table per course, id "classDesc_<sid>_<cni>_<trk>_<sec>",
# matched to grade links by their data-sid / data-cni / data-trk / data-sec.
CLASS_DESC_ID = re.compile(r"^classDesc_(?P<key>.+)$")
PERIOD = re.compile(r"Period\s*(\S+)", re.I)
TIME = re.compile(r"\(\d{1,2}:\d{2}\s*[AP]M\s*-\s*\d{1,2}:\d{2}\s*[AP]M\)", re.I)


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_gradebook(html: str, scraped_at: datetime) -> list[GradeRecord]:
    soup = BeautifulSoup(html, "html.parser")
    students = _student_names(soup)
    records: list[GradeRecord] = []

    keyed = _parse_keyed_courses(soup, students, scraped_at)
    if keyed:
        return _dedupe(keyed)

    grids = [g for g in soup.find_all(id=GRID_ID)]
    if not grids:
        # Unknown layout: fall back to treating the whole page as one grid.
        grids = [soup]

    for grid in grids:
        match = GRID_ID.match(grid.get("id", "")) if isinstance(grid, Tag) and grid.get("id") else None
        grid_sid = match.group("sid") if match else ""
        for course_info, grade_links in _course_rows(grid):
            for link in grade_links:
                grade = _clean(link.get_text())
                if not grade:
                    continue
                sid = link.get("data-sid") or grid_sid
                records.append(
                    GradeRecord(
                        scraped_at=scraped_at,
                        student=students.get(sid) or _student_heading(grid) or f"Student {sid}".strip(),
                        student_id=sid,
                        course=course_info["course"],
                        course_id=link.get("data-cni", ""),
                        period=course_info["period"],
                        teacher=course_info["teacher"],
                        term=_clean(link.get("data-lit")),
                        grade=grade,
                    )
                )
    return _dedupe(records)


def _link_key(link: Tag) -> str:
    return "_".join(link.get(a, "") for a in ("data-sid", "data-cni", "data-trk", "data-sec"))


def _parse_keyed_courses(
    soup: BeautifulSoup, students: dict[str, str], scraped_at: datetime
) -> list[GradeRecord]:
    """Layout C: per-course "classDesc_<key>" tables matched to grade links by key."""
    courses: dict[str, dict[str, str]] = {}
    for table in soup.find_all("table", id=CLASS_DESC_ID):
        key = CLASS_DESC_ID.match(table["id"]).group("key")
        courses[key] = _course_info(table)
    if not courses:
        return []

    blank = {"course": "", "period": "", "teacher": ""}
    records: list[GradeRecord] = []
    for link in soup.select("a[data-lit]"):
        grade = _clean(link.get_text())
        if not grade:
            continue
        sid = link.get("data-sid", "")
        info = courses.get(_link_key(link), blank)
        records.append(
            GradeRecord(
                scraped_at=scraped_at,
                student=students.get(sid) or f"Student {sid}".strip(),
                student_id=sid,
                course=info["course"],
                course_id=link.get("data-cni", ""),
                period=info["period"],
                teacher=info["teacher"],
                term=_clean(link.get("data-lit")),
                grade=grade,
            )
        )
    return records


def _course_rows(grid: Tag) -> list[tuple[dict[str, str], list[Tag]]]:
    """Pair each course description with the grade links on the same visual row."""
    rows = grid.find_all("tr")
    course_rows = [r for r in rows if r.select_one(".classDesc")]
    grade_rows = [r for r in rows if r.select_one("a[data-lit]")]

    pairs: list[tuple[dict[str, str], list[Tag]]] = []
    # Layout A: course name and grades in the same row.
    same_row = [r for r in course_rows if r.select_one("a[data-lit]")]
    if same_row:
        for r in same_row:
            pairs.append((_course_info(r), r.select("a[data-lit]")))
        return pairs

    # Layout B (usual): fixed left table of courses + scrolling right table of grades.
    if course_rows and len(course_rows) == len(grade_rows):
        for c, g in zip(course_rows, grade_rows):
            pairs.append((_course_info(c), g.select("a[data-lit]")))
        return pairs

    # Fallback: we found grades but could not line them up with course names.
    for g in grade_rows:
        pairs.append(({"course": "", "period": "", "teacher": ""}, g.select("a[data-lit]")))
    return pairs


def _course_info(row: Tag) -> dict[str, str]:
    desc = row.select_one(".classDesc")
    course = _clean(desc.get_text()) if desc else ""
    text = _clean(row.get_text(" "))
    period_match = PERIOD.search(text)
    period = period_match.group(1) if period_match else ""

    teacher = ""
    links = [a for a in row.find_all("a") if not a.get("data-lit")]
    for a in links:
        name = _clean(a.get_text())
        if name and name != course and not (desc and a in desc.find_all("a")):
            teacher = name
            break
    return {"course": course, "period": period, "teacher": teacher}


def _student_names(soup: BeautifulSoup) -> dict[str, str]:
    """Map student id -> name from the student picker, when the page has one."""
    names: dict[str, str] = {}
    for el in soup.select("[data-nameid], #sf_StudentList a, #sf_StudentList option"):
        sid = el.get("data-nameid") or el.get("value") or ""
        name = _clean(el.get_text())
        if sid and name and "all students" not in name.lower():
            names[sid] = name
    return names


def student_options(html: str) -> list[tuple[str, str]]:
    """(student id, name) for each child in the Student Select list, without "All Students".

    Skyward hides the gradebook while "All Students" is selected, so the browser code
    picks each of these in turn.
    """
    soup = BeautifulSoup(html, "html.parser")
    options: list[tuple[str, str]] = []
    for el in soup.select("#sf_StudentList [data-nameid]"):
        sid = (el.get("data-nameid") or "").strip()
        name = _clean(el.get_text())
        if sid and sid != "0" and name and "all students" not in name.lower():
            if sid not in {o[0] for o in options}:
                options.append((sid, name))
    return options


def gradebook_unavailable(html: str) -> bool:
    """True when Skyward shows "Gradebook is not available when viewing All Students"."""
    soup = BeautifulSoup(html, "html.parser")
    return soup.select_one("#grid_suppressed") is not None


def _student_heading(grid: Tag) -> str:
    """Nearest heading before the grid, e.g. the student-name banner above it."""
    if not isinstance(grid, Tag) or grid.name == "[document]":
        return ""
    for prev in grid.find_all_previous(limit=40):
        classes = " ".join(prev.get("class", []))
        if prev.name in {"h1", "h2", "h3"} or "sf_heading" in classes or "studentName" in classes:
            text = _clean(prev.get_text())
            if text and len(text) < 80 and "gradebook" not in text.lower():
                return text
    return ""


def _dedupe(records: list[GradeRecord]) -> list[GradeRecord]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[GradeRecord] = []
    for r in records:
        key = (r.student_id, r.course_id or r.course, r.term, r.grade)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out
