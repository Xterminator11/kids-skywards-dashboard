"""Data shapes shared by every grade source and storage backend."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime


@dataclass(frozen=True)
class GradeRecord:
    """One grade for one student, in one course, for one grading term."""

    scraped_at: datetime
    student: str
    student_id: str
    course: str
    course_id: str
    period: str
    teacher: str
    term: str          # e.g. "PR1", "Q1", "S1"
    grade: str         # as shown: "95", "A", "93.5", etc.
    source: str = "skyward"

    @classmethod
    def field_names(cls) -> list[str]:
        return [f.name for f in fields(cls)]

    def to_row(self) -> dict[str, str]:
        row = asdict(self)
        row["scraped_at"] = self.scraped_at.isoformat(timespec="seconds")
        return row


@dataclass(frozen=True)
class AssignmentRecord:
    """One assignment for one student in one course and grading term."""

    scraped_at: datetime
    student: str
    student_id: str
    course: str
    course_id: str
    term: str             # grading term the assignment counts toward, e.g. "2ND" or "PR4"
    category: str         # e.g. "Daily", "Major" (blank if Skyward does not show it)
    assignment: str
    assignment_id: str
    due_date: str         # ISO date "YYYY-MM-DD" (blank if unknown)
    score: str            # grade/percent as shown, e.g. "95", "*", "E"
    points_earned: str
    points_possible: str
    flags: str            # ";"-joined: missing, no count, absent, late, exempt, excused
    status: str           # done / missing / not_turned_in / not_yet_due / exempt
    detail_source: str    # "dialog" (term grade popup) or "gradebook" (rows on the main page)
    notes: str = ""       # teacher's special codes and comments, "; "-joined (e.g. "Excused")
    source: str = "skyward"

    @classmethod
    def field_names(cls) -> list[str]:
        return [f.name for f in fields(cls)]

    def to_row(self) -> dict[str, str]:
        row = asdict(self)
        row["scraped_at"] = self.scraped_at.isoformat(timespec="seconds")
        return row
