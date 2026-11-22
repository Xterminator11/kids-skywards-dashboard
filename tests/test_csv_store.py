import csv
from datetime import datetime
from zoneinfo import ZoneInfo

from gradebook.models import GradeRecord
from gradebook.storage import CsvGradeStore


def _rec(grade: str, day: int) -> GradeRecord:
    return GradeRecord(
        scraped_at=datetime(2026, 11, day, 17, 0, tzinfo=ZoneInfo("America/Chicago")),
        student="Alex Sample", student_id="1001", course="MATH 7", course_id="5501",
        period="1", teacher="Jordan Teacher", term="Q1", grade=grade,
    )


def test_writes_snapshot_latest_and_history(tmp_path):
    store = CsvGradeStore(tmp_path)
    store.save([_rec("93", 12)])
    store.save([_rec("95", 13)])

    history = list(csv.DictReader((tmp_path / "grades_history.csv").open()))
    assert [r["grade"] for r in history] == ["93", "95"]

    latest = list(csv.DictReader((tmp_path / "grades_latest.csv").open()))
    assert [r["grade"] for r in latest] == ["95"]

    assert (tmp_path / "snapshots" / "grades_2026-11-12.csv").exists()
    assert (tmp_path / "snapshots" / "grades_2026-11-13.csv").exists()
    assert history[0]["scraped_at"] == "2026-11-12T17:00:00-06:00"


def test_history_gets_new_columns(tmp_path):
    hist = tmp_path / "grades_history.csv"
    hist.write_text("scraped_at,student\n2026-11-01T17:00:00-05:00,Old Row\n", encoding="utf-8")
    CsvGradeStore(tmp_path).save([_rec("95", 13)])
    rows = list(csv.DictReader(hist.open(encoding="utf-8")))
    assert rows[0]["student"] == "Old Row" and rows[0]["grade"] == ""
    assert rows[1]["grade"] == "95"
