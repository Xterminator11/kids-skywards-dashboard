import csv
import json
import re
from datetime import date

from gradebook.dashboard import Rules, build_dashboard, build_payload
from gradebook.dashboard.rules import course_summaries, item_state, lagging_alerts

TODAY = date(2026, 11, 11)
STAMP = "2026-11-11T17:05:00-06:00"


def _a(course, name, due, score="", cat="", status="", earned=None, possible="100"):
    return {
        "scraped_at": STAMP, "student": "ALEX SAMPLE", "student_id": "1", "course": course,
        "course_id": "9", "term": "2ND", "category": cat, "assignment": name, "assignment_id": name,
        "due_date": due, "score": score, "points_earned": score if earned is None else earned,
        "points_possible": possible, "flags": "", "status": status, "detail_source": "dialog",
        "source": "skyward",
    }


def _g(course, term, grade):
    return {"scraped_at": STAMP, "student": "ALEX SAMPLE", "student_id": "1", "course": course,
            "course_id": "9", "period": "1", "teacher": "JORDAN TEACHER", "term": term,
            "grade": grade, "source": "skyward"}


def test_item_state():
    assert item_state(_a("M", "a", "2026-11-01", "90"), TODAY) == "done"
    assert item_state(_a("M", "a", "2026-11-01", "0"), TODAY) == "zero"
    assert item_state(_a("M", "a", "2026-11-10"), TODAY) == "overdue"
    assert item_state(_a("M", "a", "2026-11-11"), TODAY) == "open"   # due today is not late yet
    assert item_state(_a("M", "a", "2026-11-01", status="exempt"), TODAY) == "exempt"


def test_course_summary_counts_and_averages():
    grades = [_g("MATH 7", "1ST", "85"), _g("MATH 7", "2ND", "62")]
    items = [
        _a("MATH 7", "Test 1", "2026-11-02", "40", "MAJOR"),
        _a("MATH 7", "HW 1", "2026-11-03", "90", "MINOR"),
        _a("MATH 7", "HW 2", "2026-11-04", "0", "MINOR"),
        _a("MATH 7", "HW 3", "2026-11-05"),                       # past due, no score
        _a("MATH 7", "Participation 11/2-11/6", "2026-11-06"),     # teacher-scored, not counted late
    ]
    (row,) = course_summaries(grades, items, "ALEX SAMPLE", TODAY, Rules())
    assert row["current"] == 62 and row["change"] == -23
    assert row["zeros"] == 1 and row["late"] == 1
    assert row["tests_avg"] == 40 and row["daily_avg"] == 45


def test_alert_rules_and_order():
    rules = Rules()
    courses = [
        {"course": "ART", "current": 95, "q1": 94, "q2": 95, "change": 1, "zeros": 0, "late": 0, "tests_avg": None, "daily_avg": None},
        {"course": "HISTORY", "current": 78, "q1": 79, "q2": 78, "change": -1, "zeros": 0, "late": 0, "tests_avg": 90, "daily_avg": 60},
        {"course": "SCIENCE", "current": 81, "q1": 95, "q2": 81, "change": -14, "zeros": 0, "late": 0, "tests_avg": None, "daily_avg": None},
        {"course": "MATH", "current": 55, "q1": 80, "q2": 55, "change": -25, "zeros": 2, "late": 1, "tests_avg": 40, "daily_avg": 85},
    ]
    alerts = lagging_alerts(courses, rules)
    assert [a["level"] for a in alerts] == ["bad", "warn", "warn", "good"]
    assert alerts[0]["title"] == "MATH is failing at 55."
    assert "understanding" in alerts[0]["why"]
    assert alerts[1]["title"].startswith("SCIENCE dropped 14 points")
    assert "effort or organization" in alerts[2]["why"]          # HISTORY: daily work far below tests
    assert alerts[3]["title"] == "Doing well in ART."


def test_thresholds_come_from_env(monkeypatch):
    monkeypatch.setenv("DASH_FAILING_BELOW", "60")
    monkeypatch.setenv("DASH_WATCH_BELOW", "")
    rules = Rules.from_env()
    assert rules.failing_below == 60 and rules.watch_below == 80


def _write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_build_dashboard_writes_page(tmp_path):
    _write(tmp_path / "grades_latest.csv", [_g("MATH 7", "1ST", "85"), _g("MATH 7", "2ND", "62")])
    _write(tmp_path / "assignments_latest.csv", [_a("MATH 7", "HW </script> 3", "2026-11-05")])
    out = build_dashboard(tmp_path, Rules())
    html = out.read_text(encoding="utf-8")
    assert out == tmp_path / "site" / "index.html"
    assert "__DATA__" not in html
    assert html.count("</script>") == html.count("<script>")     # data can't close the script tag
    payload = json.loads(re.search(r"const DATA = (.*);\n", html).group(1).replace("<\\/", "</"))
    assert payload["today"] == "2026-11-11"
    assert payload["kids"][0]["name"] == "Alex"
    assert payload["kids"][0]["alerts"][0]["level"] == "bad"


def test_build_payload_without_data(tmp_path):
    payload = build_payload(tmp_path)
    assert payload["kids"] == [] and payload["items"] == []


def test_excused_items_are_exempt():
    row = _a("M", "a", "2026-11-01")
    row["flags"] = "excused"
    assert item_state(row, TODAY) == "exempt"


def test_writeoffs_persist_and_leave_metrics(tmp_path):
    from gradebook.dashboard import writeoffs

    data, state = tmp_path / "data", tmp_path / "state"
    data.mkdir()
    _write(data / "grades_latest.csv", [_g("MATH 7", "1ST", "85"), _g("MATH 7", "2ND", "62")])
    _write(data / "assignments_latest.csv", [
        _a("MATH 7", "HW 1", "2026-11-05"), _a("MATH 7", "HW 2", "2026-11-06", "0", "MINOR"),
    ])
    before = build_payload(data, Rules(), state_dir=state)["kids"][0]["courses"][0]
    assert before["late"] == 1 and before["zeros"] == 1

    writeoffs.add(state, "1:HW 1", {"assignment": "HW 1"})
    writeoffs.add(state, "1:HW 2", {"assignment": "HW 2"})
    assert set(json.loads((state / "writeoffs.json").read_text())) == {"1:HW 1", "1:HW 2"}

    payload = build_payload(data, Rules(), state_dir=state)
    after = payload["kids"][0]["courses"][0]
    assert after["late"] == 0 and after["zeros"] == 0 and after["daily_avg"] is None
    assert all(i["wo"] for i in payload["items"])

    writeoffs.remove(state, "1:HW 1")
    assert list(writeoffs.load(state)) == ["1:HW 2"]


def test_server_writes_off_and_serves_page(tmp_path):
    """The kids app is the front door; the classic page and write-offs need the grown-up PIN."""
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from gradebook.dashboard.server import make_handler

    data, state = tmp_path / "data", tmp_path / "state"
    data.mkdir()
    _write(data / "grades_latest.csv", [_g("MATH 7", "2ND", "62")])
    _write(data / "assignments_latest.csv", [_a("MATH 7", "HW 1", "2026-11-05")])
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(data, state, Rules(), pin="2468"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def post(path, body, cookie=""):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Cookie": cookie})
        return urllib.request.urlopen(req)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    try:
        page = urllib.request.urlopen(base + "/").read().decode()
        assert "Creature Island" in page and "__KIDS_DATA__" not in page
        try:
            urllib.request.build_opener(NoRedirect).open(base + "/classic")
            raise AssertionError("classic page should need the PIN")
        except urllib.error.HTTPError as e:
            assert e.code == 302
        try:
            post("/api/writeoffs", {"key": "1:HW 1"})
            raise AssertionError("write-offs should need the PIN")
        except urllib.error.HTTPError as e:
            assert e.code == 403
        res = post("/api/parent/unlock", {"pin": "2468"})
        cookie = res.headers["Set-Cookie"].split(";")[0]
        assert json.loads(post("/api/writeoffs", {"key": "1:HW 1"}, cookie).read())["count"] == 1
        req = urllib.request.Request(base + "/classic", headers={"Cookie": cookie})
        assert '"wo":true' in urllib.request.urlopen(req).read().decode()
    finally:
        srv.shutdown()


def test_writeoff_reason_and_comment(tmp_path):
    from gradebook.dashboard import writeoffs

    writeoffs.add(tmp_path, "1:A", {"reason": "excused", "comment": "  Teacher said skip it  "})
    writeoffs.add(tmp_path, "1:B", {"reason": "made-up", "comment": "x" * 900})
    data = writeoffs.load(tmp_path)
    assert data["1:A"]["reason"] == "excused" and data["1:A"]["comment"] == "Teacher said skip it"
    assert data["1:B"]["reason"] == "other" and len(data["1:B"]["comment"]) == writeoffs.MAX_COMMENT


def test_alert_text(tmp_path):
    from gradebook.dashboard import writeoffs
    from gradebook.dashboard.alerts import alert_text

    data, state = tmp_path / "data", tmp_path / "state"
    data.mkdir()
    _write(data / "grades_latest.csv", [_g("MATH 7", "2ND", "90")])
    _write(data / "assignments_latest.csv", [
        _a("MATH 7", "Quiz 3", "2026-11-12"),             # due tomorrow
        _a("MATH 7", "Project", "2026-11-20"),            # too far out
        _a("MATH 7", "HW 1", "2026-11-05"),               # past due
        _a("MATH 7", "HW 2", "2026-11-04"),               # past due, written off below
        _a("MATH 7", "Participation 11/9-11/13", "2026-11-12"),  # teacher-scored, skipped
    ])
    writeoffs.add(state, "1:HW 2", {"reason": "cannot_complete"})
    text = alert_text(data, state, Rules(), today=TODAY, due_days=2, url="http://x.local")
    assert "Hoot 🦉 says: Quiz 3 (Math) is due tomorrow." in text
    assert "Project" not in text and "Participation" not in text and "HW 2" not in text
    assert "Hoot 🦉 is snoozing 💤 HW 1 (Math) is past due. Turn it in and Hoot wakes up!" in text
    assert text.endswith("http://x.local")


def test_alert_text_empty_when_all_clear(tmp_path):
    from gradebook.dashboard.alerts import alert_text

    _write(tmp_path / "grades_latest.csv", [_g("MATH 7", "2ND", "90")])
    _write(tmp_path / "assignments_latest.csv", [_a("MATH 7", "HW", "2026-11-05", "95")])
    assert alert_text(tmp_path, None, Rules(), today=TODAY, due_days=2) == ""
