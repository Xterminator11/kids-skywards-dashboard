"""Assignments from Skyward Family Access pages (HTML -> AssignmentRecords).

Two places carry assignments:

1. The gradebook page itself. Under each course there are hidden rows, one per
   assignment ("Unit 3 Test", "Due: 11/12/2026 (PR4)"), and the score sits in the
   matching row (same data-rownum) of the right-hand grade grid. Skyward only lists the
   first few per course here ("Next 10..."), so this is a partial list.
2. The term-grade dialog that opens when a grade is clicked. It lists every assignment
   for that course and term, usually with category, points and Missing / No Count flags.
   The browser code saves the whole page while the dialog is open, with a comment at the
   top naming the student, course and term that were clicked (see `context_comment`).

Everything here is pure (HTML in, records out) so it can be tested and re-run on saved
pages without logging in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from ..models import AssignmentRecord
from .skyward_parser import CLASS_DESC_ID, _clean, _course_info, _student_names

ASSIGNMENT_LINK = 'a[name="showAssignmentInfo"], a#showAssignmentInfo, a[data-aid]'
GRID_PREFIX = "grid_stuGradesGrid"
DIALOG_BOX = re.compile(r"\bsf_DialogWrap\b|\bui-dialog\b")
# The gradebook page's "Missing Assignments" box (lists assignment links when any are missing).
MISSING_BOX = re.compile(r"missingAssignments", re.I)
# Semester averages, exams and finals are summaries, not terms with their own assignments.
SUMMARY_TERM = re.compile(r"^(SM|SEM|S)\d|^EX|^FIN|^YR|^Y\d", re.I)
DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})")
TERM_IN_PARENS = re.compile(r"\(([^)]+)\)")
OUT_OF = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:out of|/|of)\s*(\d+(?:\.\d+)?)", re.I)
OUT_OF_ONLY = re.compile(r"^\s*[*-]?\s*(?:out of|/)\s*(\d+(?:\.\d+)?)", re.I)
CONTEXT = re.compile(r"<!--\s*gradebook-assignments\s+(?P<body>[^>]*?)\s*-->")


@dataclass(frozen=True)
class GradeLink:
    """One clickable term grade on the gradebook page."""

    sid: str
    cni: str
    trk: str
    sec: str
    lit: str
    grade: str

    @property
    def key(self) -> str:
        return f"{self.sid}_{self.cni}_{self.trk}_{self.sec}"

    @property
    def selector(self) -> str:
        return (
            f'a[data-lit="{self.lit}"][data-cni="{self.cni}"][data-sid="{self.sid}"]'
            f'[data-trk="{self.trk}"][data-sec="{self.sec}"]'
        )


def latest_grade_links(html: str) -> list[GradeLink]:
    """For each course, the right-most term grade that is filled in (skipping semester,
    exam and final columns). Clicking it opens that term's assignment list."""
    soup = BeautifulSoup(html, "html.parser")
    latest: dict[str, GradeLink] = {}
    for a in soup.select("a[data-lit]"):
        grade = _clean(a.get_text())
        lit = _clean(a.get("data-lit"))
        if not grade or not lit or SUMMARY_TERM.match(lit):
            continue
        link = GradeLink(
            sid=a.get("data-sid", ""), cni=a.get("data-cni", ""), trk=a.get("data-trk", ""),
            sec=a.get("data-sec", ""), lit=lit, grade=grade,
        )
        latest[link.key] = link  # document order runs left to right, so the last one wins
    return list(latest.values())


def context_comment(link: GradeLink) -> str:
    """Marker written at the top of each saved dialog page so it can be parsed offline."""
    return (
        f"<!-- gradebook-assignments sid={link.sid} cni={link.cni} trk={link.trk} "
        f"sec={link.sec} lit={link.lit} -->\n"
    )


def _read_context(html: str) -> dict[str, str]:
    m = CONTEXT.search(html[:2000])
    if not m:
        return {}
    return dict(part.split("=", 1) for part in m.group("body").split() if "=" in part)


def parse_iso_date(text: str) -> str:
    m = DATE.search(text or "")
    if not m:
        return ""
    month, day, year = (int(x) for x in m.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _positive(score: str) -> bool:
    try:
        return float(score) > 0
    except (TypeError, ValueError):
        return False


def assignment_status(score: str, due_date: str, flags: list[str], today: date) -> str:
    """done / missing / not_turned_in / not_yet_due / exempt.

    An "excused" flag (from a teacher's special code or comment) wins over everything:
    the assignment is exempt unless it still has a real score. Then Skyward's own flags. Otherwise a score means done; no score means not yet due
    (due today or later) or not turned in (due date passed). "*" is Skyward's usual
    placeholder for a missing score.
    """
    lowered = [f.lower() for f in flags]
    if "excused" in lowered:
        # Teacher excused the student: never counts as missing or a zero.
        return "done" if _positive(score) else "exempt"
    if "missing" in lowered:
        return "missing"
    if "exempt" in lowered or "no count" in lowered:
        return "exempt" if not score or score == "*" else "done"
    if score and score != "*":
        return "done"
    if due_date:
        if date.fromisoformat(due_date) >= today:
            return "not_yet_due"
        return "not_turned_in"
    return "not_turned_in" if score == "*" else "not_yet_due"


# ---------------------------------------------------------------- gradebook page rows


def parse_gradebook_assignments(
    html: str, scraped_at: datetime, today: date | None = None
) -> list[AssignmentRecord]:
    """The (partial) assignment rows embedded in the gradebook page."""
    today = today or scraped_at.date()
    soup = BeautifulSoup(html, "html.parser")
    students = _student_names(soup)
    courses = {
        CLASS_DESC_ID.match(t["id"]).group("key"): _course_info(t)
        for t in soup.find_all("table", id=CLASS_DESC_ID)
    }

    # Score rows: grade-grid rows without an assignment link, keyed by (grid id, rownum).
    scores: dict[tuple[str, str], str] = {}
    for tr in soup.select("tr[group-child][data-rownum]"):
        if tr.select_one(ASSIGNMENT_LINK):
            continue
        table = tr.find_parent("table")
        texts = [_clean(td.get_text(" ")) for td in tr.find_all("td", recursive=False)]
        values = [t for t in texts if t]
        scores[(table.get("id", "") if table else "", tr["data-rownum"])] = values[0] if values else ""

    missing = _missing_ids(soup)
    records: list[AssignmentRecord] = []
    for link in soup.select(ASSIGNMENT_LINK):
        tr = link.find_parent("tr")
        if tr is None or not tr.get("group-child"):
            continue
        key = tr["group-child"]
        sid = link.get("data-sid") or key.split("_")[0]
        table = tr.find_parent("table")
        score = scores.get((table.get("id", "") if table else "", tr.get("data-rownum", "")), "")
        if score.lower().startswith("next "):
            score = ""
        label = tr.find("label", string=re.compile(r"Due", re.I))
        due_text = _clean(label.find_next("span").get_text(" ")) if label and label.find_next("span") else ""
        due_text = due_text or _clean(tr.get_text(" "))
        terms = TERM_IN_PARENS.findall(due_text)
        due = parse_iso_date(due_text)
        course = courses.get(key, {"course": "", "period": "", "teacher": ""})
        records.append(
            AssignmentRecord(
                scraped_at=scraped_at,
                student=students.get(sid) or f"Student {sid}",
                student_id=sid,
                course=course["course"],
                course_id=key.split("_")[1] if "_" in key else "",
                term=_clean(terms[-1]) if terms else "",
                category="",
                assignment=_clean(link.get_text()),
                assignment_id=link.get("data-aid", ""),
                due_date=due,
                score=score,
                points_earned="",
                points_possible="",
                flags="",
                status=assignment_status(score, due, [], today),
                detail_source="gradebook",
            )
        )
    notes = _notes_by_id(soup)
    return [_apply_notes(_apply_missing(r, missing, today), notes, today) for r in records]


# ---------------------------------------------------------------- term-grade dialog

_HEADER_ALIASES = {
    "due": "due", "due date": "due", "date due": "due",
    "assignment": "assignment", "assignments": "assignment", "description": "assignment",
    "grade": "grade", "score": "score", "score (%)": "score", "score(%)": "score", "%": "score",
    "points": "points", "points earned": "points", "pts": "points",
    "missing": "missing", "no count": "no count", "absent": "absent", "late": "late",
    "exempt": "exempt", "excused": "exempt", "category": "category",
}
_FLAG_COLUMNS = ("missing", "no count", "absent", "late", "exempt")


def _spans(cells: list[Tag]) -> list[tuple[int, int, Tag]]:
    """(first column, last column, cell) for each cell, honouring colspan."""
    out: list[tuple[int, int, Tag]] = []
    col = 0
    for cell in cells:
        try:
            width = max(1, int(cell.get("colspan", 1)))
        except ValueError:
            width = 1
        out.append((col, col + width - 1, cell))
        col += width
    return out


def _header_map(table: Tag) -> dict[int, str]:
    """Column position -> field name, from the table's header row."""
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        ths = tr.find_all("th", recursive=False)
        if len(ths) >= 2:
            out: dict[int, str] = {}
            for start, _end, th in _spans(ths):
                name = _clean(th.get_text(" ")).lower().rstrip(":")
                if name in _HEADER_ALIASES:
                    out[start] = _HEADER_ALIASES[name]
            if "assignment" in out.values() or "due" in out.values():
                return out
    return {}


def _cell_flag(cell: Tag) -> bool:
    """Flag columns show a check image, an "X"/"Y"/"*", or the word itself."""
    text = _clean(cell.get_text(" ")).lower()
    if text and text not in {"no", "n", "-", "0"}:
        return True
    for img in cell.find_all("img"):
        if (img.get("alt") or img.get("title") or "").strip():
            return True
    checkbox = cell.find("input", attrs={"type": "checkbox"})
    return bool(checkbox and checkbox.has_attr("checked"))


def _category_name(text: str) -> str:
    text = re.split(r"\s+weighted at\s+|\s+\(\s*\d", text, maxsplit=1, flags=re.I)[0]
    return _clean(text)


def parse_assignment_dialog(
    html: str, scraped_at: datetime, today: date | None = None
) -> list[AssignmentRecord]:
    """Assignments from a page saved while the term-grade dialog was open."""
    today = today or scraped_at.date()
    ctx = _read_context(html)
    soup = BeautifulSoup(html, "html.parser")
    students = _student_names(soup)
    sid = ctx.get("sid", "")
    key = "_".join(ctx.get(k, "") for k in ("sid", "cni", "trk", "sec"))
    course_tables = soup.find_all("table", id=re.compile(rf"^classDesc_{re.escape(key)}$")) if ctx else []
    course = _course_info(course_tables[0])["course"] if course_tables else ""

    missing = _missing_ids(soup)
    boxes = [
        el for el in soup.find_all(["div", "section"])
        if (DIALOG_BOX.search(" ".join(el.get("class", []))) or el.get("role") == "dialog")
        and el.get("id") != "sf_message"
    ]
    candidates = [t for box in boxes for t in box.find_all("table")] or soup.find_all("table")

    records: list[AssignmentRecord] = []
    for table in candidates:
        if (table.get("id") or "").startswith(GRID_PREFIX) or table.find_parent(
            "table", id=re.compile(f"^{GRID_PREFIX}")
        ) or table.find_parent(id=MISSING_BOX):
            continue
        rows = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
        if not any(tr.select_one(ASSIGNMENT_LINK) for tr in rows):
            continue
        header = _header_map(table)
        category = ""
        for tr in rows:
            link = tr.select_one(ASSIGNMENT_LINK)
            if link is not None and link.find_parent("table") is not table:
                continue  # the link belongs to a table nested inside this row
            cells = tr.find_all(["td", "th"], recursive=False)
            if link is None:
                if tr.find("th"):
                    continue
                classes = tr.get("class", [])
                weighted = next((c for c in cells if re.search(r"weighted at", c.get_text(" "), re.I)), None)
                if weighted is not None:
                    category = _category_name(_clean(weighted.get_text(" ")))
                elif "cat" in classes:
                    category = _category_name(_clean(tr.get_text(" ")))
                continue
            records.append(_dialog_row(link, cells, header, category, ctx, sid, students, course, scraped_at, today))
    notes = _notes_by_id(soup)
    return _dedupe([_apply_notes(_apply_missing(r, missing, today), notes, today) for r in records])


def _missing_ids(soup: BeautifulSoup) -> set[str]:
    """Assignment ids listed in the page's "Missing Assignments" box."""
    ids: set[str] = set()
    for box in soup.find_all(id=MISSING_BOX):
        for a in box.select("a[data-aid]"):
            ids.add(a["data-aid"])
    return ids


# Teachers attach notes to a score as small icons: a special code ("Excused",
# "MISSING OR LATE WRK") or a comment ("Turned in late."). Their ids end in
# _<student id>_<assignment id> and the text is in data-info.
NOTE_LINK = re.compile(r"^(?:specCode|comment)_(\d+)_(\d+)$")
EXCUSED = re.compile(r"\bexcused\b", re.I)   # "UNEXCUSED" does not match


def _notes_by_id(soup: BeautifulSoup) -> dict[tuple[str, str], list[str]]:
    notes: dict[tuple[str, str], list[str]] = {}
    for a in soup.find_all("a", id=NOTE_LINK):
        sid, aid = NOTE_LINK.match(a["id"]).groups()
        text = _clean(a.get("data-info", ""))
        found = notes.setdefault((sid, aid), [])
        if text and text not in found:
            found.append(text)
    return notes


def _apply_notes(
    record: AssignmentRecord, notes: dict[tuple[str, str], list[str]], today: date
) -> AssignmentRecord:
    found = notes.get((record.student_id, record.assignment_id))
    if not found:
        return record
    flags = [f for f in record.flags.split(";") if f]
    if any(EXCUSED.search(n) for n in found) and "excused" not in flags:
        flags.append("excused")
    return replace(
        record, notes="; ".join(found), flags=";".join(flags),
        status=assignment_status(record.score, record.due_date, flags, today),
    )


def _apply_missing(record: AssignmentRecord, missing: set[str], today: date) -> AssignmentRecord:
    if record.assignment_id not in missing or "missing" in record.flags.split(";"):
        return record
    flags = [f for f in record.flags.split(";") if f] + ["missing"]
    return replace(
        record, flags=";".join(flags),
        status=assignment_status(record.score, record.due_date, flags, today),
    )


def _dialog_row(link, cells, header, category, ctx, sid, students, course, scraped_at, today) -> AssignmentRecord:
    by_name: dict[str, Tag] = {}
    spans = _spans(cells)
    for pos, name in header.items():
        cell = next((c for start, end, c in spans if start <= pos <= end), None)
        if cell is not None and name not in by_name:
            by_name[name] = cell

    def text(name: str) -> str:
        return _clean(by_name[name].get_text(" ")) if name in by_name else ""

    row_text = _clean(" ".join(c.get_text(" ") for c in cells))
    due = parse_iso_date(text("due")) or parse_iso_date(row_text)
    score = text("grade") or text("score")
    earned = possible = ""
    m = OUT_OF.search(text("points") or row_text)
    if m:
        earned, possible = m.group(1), m.group(2)
    elif m2 := OUT_OF_ONLY.search(text("points")):
        possible = m2.group(1)  # nothing earned yet: "out of 10"
    elif text("points"):
        earned = text("points")

    flags = [name for name in _FLAG_COLUMNS if name in by_name and _cell_flag(by_name[name])]
    for name in _FLAG_COLUMNS:  # some layouts show flags as words in the row instead
        if name not in flags and re.search(rf"\b{name}\b", row_text, re.I) and name not in by_name:
            flags.append(name)
    student_id = link.get("data-sid") or sid
    return AssignmentRecord(
        scraped_at=scraped_at,
        student=students.get(student_id) or f"Student {student_id}",
        student_id=student_id,
        course=course,
        course_id=ctx.get("cni", ""),
        term=ctx.get("lit", ""),
        category=text("category") or category,
        assignment=_clean(link.get_text()),
        assignment_id=link.get("data-aid", ""),
        due_date=due,
        score=score,
        points_earned=earned,
        points_possible=possible,
        flags=";".join(flags),
        status=assignment_status(score, due, flags, today),
        detail_source="dialog",
    )


def _dedupe(records: list[AssignmentRecord]) -> list[AssignmentRecord]:
    seen: set[tuple[str, str, str]] = set()
    out: list[AssignmentRecord] = []
    for r in records:
        key = (r.student_id, r.assignment_id or r.assignment, r.term)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def merge_assignments(
    dialog: list[AssignmentRecord], gradebook: list[AssignmentRecord]
) -> list[AssignmentRecord]:
    """Dialog rows (complete, with details) plus any gradebook-page rows they do not cover.

    Course names missing from dialog rows are filled in from the gradebook rows.
    """
    names = {(r.student_id, r.course_id): r.course for r in gradebook if r.course}
    dialog = [
        replace(r, course=r.course or names.get((r.student_id, r.course_id), "")) for r in dialog
    ]
    # A note (e.g. "Excused") may only be on the main page; carry it over.
    page = {(r.student_id, r.assignment_id): r for r in gradebook if r.notes}
    dialog = [_take_notes(r, page.get((r.student_id, r.assignment_id))) for r in dialog]
    have = {(r.student_id, r.assignment_id) for r in dialog if r.assignment_id}
    extra = [r for r in gradebook if (r.student_id, r.assignment_id) not in have]
    return dialog + extra


def _take_notes(record: AssignmentRecord, other: AssignmentRecord | None) -> AssignmentRecord:
    if other is None or record.notes:
        return record
    flags = [f for f in record.flags.split(";") if f]
    if "excused" in other.flags.split(";") and "excused" not in flags:
        flags.append("excused")
    status = record.status
    if "excused" in flags:
        status = assignment_status(record.score, record.due_date, flags, record.scraped_at.date())
    return replace(record, notes=other.notes, flags=";".join(flags), status=status)
