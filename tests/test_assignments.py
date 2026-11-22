from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from gradebook.sources.skyward_assignments_parser import (
    GradeLink,
    assignment_status,
    context_comment,
    latest_grade_links,
    merge_assignments,
    parse_assignment_dialog,
    parse_gradebook_assignments,
)

FIXTURES = Path(__file__).parent / "fixtures"
GRADEBOOK = (FIXTURES / "skyward_gradebook_assignments.html").read_text()
NOW = datetime(2026, 11, 10, 17, 0, tzinfo=ZoneInfo("America/Chicago"))
TODAY = NOW.date()


def test_latest_grade_link_skips_semester_and_blank_grades():
    links = {(link.cni, link.lit) for link in latest_grade_links(GRADEBOOK)}
    assert links == {("9001", "PR2"), ("9002", "PR1")}


@pytest.mark.parametrize(
    ("score", "due", "flags", "expected"),
    [
        ("92", "2026-11-02", [], "done"),
        ("", "2026-11-05", ["missing"], "missing"),
        ("*", "2026-11-05", [], "not_turned_in"),
        ("", "2026-11-05", [], "not_turned_in"),
        ("", "2026-11-10", [], "not_yet_due"),   # due today
        ("", "2026-11-20", [], "not_yet_due"),
        ("", "2026-11-03", ["no count"], "exempt"),
        ("", "", [], "not_yet_due"),
    ],
)
def test_assignment_status(score, due, flags, expected):
    assert assignment_status(score, due, flags, TODAY) == expected


def test_gradebook_page_assignments():
    records = parse_gradebook_assignments(GRADEBOOK, NOW)
    got = {(r.assignment, r.course, r.term, r.due_date, r.score, r.status) for r in records}
    assert got == {
        ("Fractions Quiz (Part 1)", "SAMPLE MATH", "PR2", "2026-11-02", "92", "done"),
        ("Homework 4", "SAMPLE MATH", "PR2", "2026-11-05", "", "not_turned_in"),
        ("Project Draft", "SAMPLE MATH", "PR2", "2026-11-20", "", "not_yet_due"),
    }
    assert {r.student for r in records} == {"PAT SAMPLE"}


def _open_dialog_html() -> str:
    """The fixture page as it looks with the fake dialog open (built without a browser)."""
    link = GradeLink(sid="2001", cni="9001", trk="0", sec="02", lit="PR2", grade="90")
    dialog = (FIXTURES / "skyward_assignment_dialog.html").read_text()
    return context_comment(link) + GRADEBOOK.replace("</body>", dialog + "</body>")


def test_dialog_assignments_with_categories_points_and_flags():
    records = parse_assignment_dialog(_open_dialog_html(), NOW)
    assert len(records) == 5  # the outer summary table must not add copies
    by_name = {r.assignment: r for r in records}
    assert set(by_name) == {"Fractions Quiz (Part 1)", "Homework 4", "Homework 5", "Project Draft", "Practice Set"}

    quiz = by_name["Fractions Quiz (Part 1)"]
    assert (quiz.student, quiz.course, quiz.term, quiz.category) == ("PAT SAMPLE", "SAMPLE MATH", "PR2", "Daily")
    assert (quiz.due_date, quiz.score, quiz.points_earned, quiz.points_possible, quiz.status) == (
        "2026-11-02", "92", "23", "25", "done")

    hw4 = by_name["Homework 4"]
    assert (hw4.flags, hw4.status, hw4.points_possible) == ("missing", "missing", "10")
    # Not flagged in the dialog, but listed in the page's Missing Assignments box.
    assert (by_name["Homework 5"].flags, by_name["Homework 5"].status) == ("absent;missing", "missing")
    assert (by_name["Project Draft"].category, by_name["Project Draft"].status) == ("Major", "not_yet_due")
    assert (by_name["Practice Set"].flags, by_name["Practice Set"].status) == ("no count", "exempt")


def test_merge_prefers_dialog_rows_and_keeps_extra_page_rows():
    dialog = parse_assignment_dialog(_open_dialog_html(), NOW)
    page = parse_gradebook_assignments(GRADEBOOK, NOW)
    extra = page[0].__class__(**{**page[0].__dict__, "assignment_id": "999", "assignment": "Older Quiz"})
    merged = merge_assignments(dialog, page + [extra])
    assert len(merged) == len(dialog) + 1
    assert merged[-1].assignment == "Older Quiz"
    assert {r.detail_source for r in merged[:-1]} == {"dialog"}


def test_points_with_nothing_earned_yet():
    by_name = {r.assignment: r for r in parse_assignment_dialog(_open_dialog_html(), NOW)}
    hw5 = by_name["Homework 5"]
    assert (hw5.points_earned, hw5.points_possible) == ("", "10")


def test_excused_special_code_and_comments_become_notes():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from gradebook.sources.skyward_assignments_parser import parse_gradebook_assignments

    html = """
    <table id="classDesc_1_77_0_01"><tr><td><span class="bld classDesc"><a>MATH 7</a></span></td></tr></table>
    <table id="grid_1_77">
      <tr group-child="1_77_0_01" data-rownum="5"><td>
        <a id="showAssignmentInfo" data-sid="1" data-aid="900">Old Task</a>
        <label>Due:</label><span>10/06/2026</span></td></tr>
      <tr group-child="1_77_0_01" data-rownum="6"><td>
        <a id="specCode_1_900" data-info="Excused"></a></td></tr>
      <tr group-child="1_77_0_01" data-rownum="7"><td>
        <a id="showAssignmentInfo" data-sid="1" data-aid="901">Absent Task</a>
        <label>Due:</label><span>10/07/2026</span></td></tr>
      <tr group-child="1_77_0_01" data-rownum="8"><td>
        <a id="comment_1_901" data-info="UNEXCUSED absence"></a></td></tr>
    </table>"""
    when = datetime(2026, 11, 22, 8, 30, tzinfo=ZoneInfo("America/Chicago"))
    recs = {r.assignment_id: r for r in parse_gradebook_assignments(html, when)}
    assert recs["900"].status == "exempt" and "excused" in recs["900"].flags
    assert recs["900"].notes == "Excused"
    assert recs["901"].status == "not_turned_in" and "excused" not in recs["901"].flags
    assert recs["901"].notes == "UNEXCUSED absence"
