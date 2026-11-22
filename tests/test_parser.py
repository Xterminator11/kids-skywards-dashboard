from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gradebook.sources.skyward_parser import parse_gradebook

FIXTURE = Path(__file__).parent / "fixtures" / "skyward_gradebook.html"
NOW = datetime(2026, 11, 12, 17, 0, tzinfo=ZoneInfo("America/Chicago"))


def test_parses_all_grades_for_each_student():
    records = parse_gradebook(FIXTURE.read_text(), NOW)
    assert len(records) == 6
    assert {r.student for r in records} == {"Alex Sample", "Jamie Sample"}


def test_lines_up_courses_teachers_and_terms():
    records = parse_gradebook(FIXTURE.read_text(), NOW)
    eng_pr2 = next(r for r in records if r.course == "ENGLISH 7" and r.term == "PR2")
    assert eng_pr2.grade == "87"
    assert eng_pr2.teacher == "Casey Teacher"
    assert eng_pr2.period == "2"
    assert eng_pr2.course_id == "5502"

    math_q1 = next(r for r in records if r.course == "MATH 7 ADV" and r.term == "Q1")
    assert math_q1.grade == "93" and math_q1.teacher == "Jordan Teacher" and math_q1.period == "1"

    sci = next(r for r in records if r.student == "Jamie Sample")
    assert (sci.course, sci.teacher, sci.period, sci.grade) == ("SCIENCE 4", "Riley Teacher", "3", "A")


def test_empty_page_gives_no_records():
    assert parse_gradebook("<html><body>Nothing here</body></html>", NOW) == []


ALL_STUDENTS = Path(__file__).parent / "fixtures" / "skyward_all_students.html"


def test_all_students_page_lists_each_child_and_is_suppressed():
    from gradebook.sources.skyward_parser import gradebook_unavailable, student_options

    html = ALL_STUDENTS.read_text()
    assert student_options(html) == [("2001", "PAT SAMPLE"), ("2002", "ROBIN SAMPLE")]
    assert gradebook_unavailable(html)
    assert parse_gradebook(html, NOW) == []


def test_normal_gradebook_is_not_suppressed():
    from gradebook.sources.skyward_parser import gradebook_unavailable, student_options

    html = FIXTURE.read_text()
    assert not gradebook_unavailable(html)
    assert student_options(html) == [("1001", "Alex Sample"), ("1002", "Jamie Sample")]


KEYED = Path(__file__).parent / "fixtures" / "skyward_keyed_courses.html"


def test_matches_per_course_tables_to_grades_by_key():
    records = parse_gradebook(KEYED.read_text(), NOW)
    got = {(r.student, r.student_id, r.course, r.period, r.teacher, r.term, r.grade) for r in records}
    assert got == {
        ("PAT SAMPLE", "2001", "SAMPLE MATH", "1", "Casey Teacher", "PR1", "88"),
        ("PAT SAMPLE", "2001", "SAMPLE MATH", "1", "Casey Teacher", "Q1", "90"),
        ("PAT SAMPLE", "2001", "SAMPLE SCIENCE", "3", "Jordan Teacher", "PR1", "95"),
    }
