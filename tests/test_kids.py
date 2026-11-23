"""Kids mode: the payload, the family's saved choices, and the server routes."""
import csv
import json
import threading
import urllib.error
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer

import pytest

from gradebook.dashboard import family, writeoffs
from gradebook.dashboard.kids import build_kids_payload, grade_level, pick_last_check, subject_label
from gradebook.dashboard.rules import Rules
from gradebook.dashboard.server import make_handler

OLD, NEW = "2026-11-11T17:05:00-06:00", "2026-11-22T08:30:00-06:00"
KIDS = {"1": "ALEX SAMPLE", "2": "SAM SAMPLE"}


def _g(stamp, sid, course, cid, term, grade):
    return {"scraped_at": stamp, "student": KIDS[sid], "student_id": sid, "course": course, "course_id": cid,
            "period": "1", "teacher": "JORDAN TEACHER", "term": term, "grade": grade, "source": "skyward"}


def _a(stamp, sid, course, cid, name, due, score="", cat="MINOR"):
    return {"scraped_at": stamp, "student": KIDS[sid], "student_id": sid, "course": course, "course_id": cid,
            "term": "2ND", "category": cat, "assignment": name, "assignment_id": name, "due_date": due,
            "score": score, "points_earned": score, "points_possible": "100" if score else "", "flags": "",
            "status": "", "detail_source": "dialog", "source": "skyward"}


def _write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.delenv("KIDS_MOODS", raising=False)
    data, state = tmp_path / "data", tmp_path / "state"
    data.mkdir()
    old_g = [_g(OLD, "1", "HONORS MATH 7A", "10", "1ST", "81"), _g(OLD, "1", "HONORS MATH 7A", "10", "2ND", "55"),
             _g(OLD, "2", "4TH GRADE SCIENCE", "20", "2ND", "96")]
    new_g = [_g(NEW, "1", "HONORS MATH 7A", "10", "1ST", "81"), _g(NEW, "1", "HONORS MATH 7A", "10", "2ND", "62"),
             _g(NEW, "1", "ORCHESTRA 7", "11", "2ND", "86"),
             _g(NEW, "2", "4TH GRADE SCIENCE", "20", "2ND", "96"), _g(NEW, "2", "ART 4", "21", "2ND", "E")]
    old_a = [_a(OLD, "1", "HONORS MATH 7A", "10", "Quiz 1", "2026-11-05", "70")]
    new_a = [_a(NEW, "1", "HONORS MATH 7A", "10", "Quiz 1", "2026-11-05", "70"),
             _a(NEW, "1", "HONORS MATH 7A", "10", "Test 2", "2026-11-18", "92", cat="MAJOR"),
             _a(NEW, "1", "HONORS MATH 7A", "10", "HW 3", "2026-11-19"),
             _a(NEW, "2", "4TH GRADE SCIENCE", "20", "Lab", "2026-11-20", "100")]
    _write(data / "grades_history.csv", old_g + new_g)
    _write(data / "assignments_history.csv", old_a + new_a)
    _write(data / "grades_latest.csv", new_g)
    _write(data / "assignments_latest.csv", new_a)
    return data, state


def test_labels_and_levels():
    assert subject_label("HONORS MATH 7A") == ("Honors Math", "owl")
    assert subject_label("4TH GRADE SOCIAL STUDIES") == ("Social Studies", "armadillo")
    assert subject_label("HONORS TX HISTORY 7") == ("Honors Texas History", "armadillo")
    assert subject_label("UNDERWATER BASKET WEAVING")[1] is None
    assert grade_level(["4TH GRADE SCIENCE"]) == 4
    assert grade_level(["HONORS MATH 7A"]) == 7


def test_pick_last_check():
    days = ["2026-11-01", "2026-11-11", "2026-11-20", "2026-11-22"]
    assert pick_last_check(days, "2026-11-22", 7) == "2026-11-11"
    assert pick_last_check(["2026-11-20", "2026-11-22"], "2026-11-22", 7) == "2026-11-20"
    assert pick_last_check(["2026-11-22"], "2026-11-22", 7) is None


def test_payload_trends_new_grades_and_moods(dirs):
    data, state = dirs
    p = build_kids_payload(data, state, Rules())
    assert p["lastCheck"] == "2026-11-11" and p["today"] == "2026-11-22"
    alex, sam = p["kids"]
    assert (alex["name"], sam["name"]) == ("Alex", "Sam")
    assert alex["low"] == "sleepy" and sam["low"] == "hungry"
    assert alex["gradeLabel"] == "7th grade" and sam["gradeLabel"] == "4th grade"
    math = next(s for s in alex["subjects"] if s["label"] == "Honors Math")
    assert (math["grade"], math["prev"], math["terms"]) == (62, 55, {"Q1": 81, "Q2": 62})
    orch = next(s for s in alex["subjects"] if s["label"] == "Orchestra")
    assert orch["prev"] == orch["grade"]          # no earlier grade: shows as steady
    assert sam["specials"] == [{"label": "Art", "grade": "E"}]
    items = {i["title"]: i for i in alex["items"]}
    assert items["Test 2"]["new"] and items["Test 2"]["cat"] == "major"
    assert not items["Quiz 1"]["new"]
    assert items["HW 3"]["st"] in ("overdue", "zero", "open")
    # The first season is saved, so the bar doesn't reset next month.
    assert family.load(state)["rewards"]["season_start"] == "2026-11-01"


def test_moods_can_be_set(dirs, monkeypatch):
    monkeypatch.setenv("KIDS_MOODS", "Alex=hungry")
    p = build_kids_payload(*dirs, Rules())
    assert p["kids"][0]["low"] == "hungry"


def test_payload_without_data(tmp_path):
    p = build_kids_payload(tmp_path / "none", tmp_path / "state", Rules())
    assert p["kids"] == [] and p["lastCheck"] is None


def test_family_actions(tmp_path):
    today = date(2026, 11, 23)
    family.claim(tmp_path, "1:HW 3", "1", today)
    family.request_writeoff(tmp_path, "1:Quiz 9", "1", "turned_in", "  gave it  in\nclass ", today)
    d = family.load(tmp_path)
    assert d["claims"]["1:HW 3"] == {"kid": "1", "at": "2026-11-23"}
    assert d["requests"]["1:Quiz 9"]["note"] == "gave it in class"
    family.decide_request(tmp_path, "1:Quiz 9", True, today, item={"student": "Alex"})
    assert "1:Quiz 9" not in family.load(tmp_path)["requests"]
    wo = writeoffs.load(tmp_path)["1:Quiz 9"]
    assert wo["by"] == "kid" and wo["reason"] == "turned_in" and wo["requested_at"] == "2026-11-23"

    family.request_writeoff(tmp_path, "1:HW 3", "1", "bogus", "", today)
    family.decide_request(tmp_path, "1:HW 3", False, today)
    req = family.load(tmp_path)["requests"]["1:HW 3"]
    assert req["status"] == "declined" and req["reason"] == "other"
    family.cancel_request(tmp_path, "1:HW 3")             # a declined ask stays for the log
    assert "1:HW 3" in family.load(tmp_path)["requests"]
    with pytest.raises(family.Invalid):
        family.decide_request(tmp_path, "1:HW 3", True, today)


def test_profiles_creatures_and_rewards(tmp_path):
    today = date(2026, 11, 23)
    family.set_profile(tmp_path, "1", "Alexandra the Great Explorer", {"type": "char", "sp": "giraffe"}, "ocean")
    assert family.load(tmp_path)["profiles"]["1"] == {"name": "Alexandra the Great",
                                                      "pic": {"type": "char", "sp": "giraffe"}, "theme": "ocean"}
    with pytest.raises(family.Invalid):
        family.set_profile(tmp_path, "1", "A", {"type": "photo", "data": "javascript:alert(1)"}, None)
    family.set_profile(tmp_path, "1", "", None, None)
    assert "1" not in family.load(tmp_path)["profiles"]

    family.set_creature(tmp_path, "1", "10", name="Hoot")
    family.set_creature(tmp_path, "1", "10", sp="lion")
    assert family.load(tmp_path)["creatures"]["1:10"] == {"sp": "lion"}   # a new character gets a new name
    with pytest.raises(family.Invalid):
        family.set_creature(tmp_path, "1", "10", sp="dragon")

    family.set_tiers(tmp_path, [{"stars": "200", "reward": "Movie"}, {"stars": 50, "reward": "Ice cream"},
                                {"stars": 0, "reward": "x"}, {"stars": 10, "reward": ""}])
    assert [t["stars"] for t in family.load(tmp_path)["rewards"]["tiers"]] == [50, 200]
    family.redeem(tmp_path, 50, today)
    family.redeem(tmp_path, 50, today)
    assert len(family.load(tmp_path)["rewards"]["redeemed"]) == 1
    family.new_season(tmp_path, today)
    r = family.load(tmp_path)["rewards"]
    assert r["redeemed"] == [] and r["season_start"] == "2026-11-23"


@pytest.fixture
def server(dirs):
    data, state = dirs
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(data, state, Rules(), pin="2468"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", state
    srv.shutdown()


def _post(base, path, body=None, cookie=""):
    req = urllib.request.Request(base + path, data=json.dumps(body or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Cookie": cookie})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read()), r.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()), ""


def test_server_kid_flow_and_pin(server):
    base, state = server
    code, p, _ = _post(base, "/api/claim", {"key": "1:HW 3", "kid": "1"})
    assert code == 200 and p["family"]["claims"]["1:HW 3"]["kid"] == "1" and p["parent"] is False
    code, p, _ = _post(base, "/api/request", {"key": "1:Test 2", "kid": "1", "reason": "excused"})
    assert p["family"]["requests"]["1:Test 2"]["status"] == "pending"

    assert _post(base, "/api/request/decide", {"key": "1:Test 2", "approve": True})[0] == 403
    assert _post(base, "/api/parent/unlock", {"pin": "0000"})[0] == 403
    code, p, cookie = _post(base, "/api/parent/unlock", {"pin": "2468"})
    assert code == 200 and p["parent"] is True and "HttpOnly" in cookie
    cookie = cookie.split(";")[0]
    code, p, _ = _post(base, "/api/request/decide", {"key": "1:Test 2", "approve": True}, cookie)
    wo = p["writeoffs"]["1:Test 2"]
    assert code == 200 and wo["by"] == "kid" and wo["assignment"] == "Test 2" and wo["course"] == "HONORS MATH 7A"
    assert _post(base, "/api/rewards/tiers", {"tiers": []}, cookie)[0] == 400

    _post(base, "/api/parent/lock", {}, cookie)
    assert _post(base, "/api/writeoffs/remove", {"key": "1:Test 2"}, cookie)[0] == 403


def test_server_pin_lockout(server):
    base, _ = server
    for _ in range(5):
        assert _post(base, "/api/parent/unlock", {"pin": "1111"})[0] == 403
    assert _post(base, "/api/parent/unlock", {"pin": "2468"})[0] == 429


def test_server_rejects_bad_input(server):
    base, _ = server
    assert _post(base, "/api/claim", {"kid": "1"})[0] == 400
    req = urllib.request.Request(base + "/api/claim", data=b"[1]", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 400
    page = urllib.request.urlopen(base + "/").read().decode()
    assert "Creature Island" in page and "<\\/" not in page.split("let P =")[0]


def test_alert_in_creature_voices(dirs):
    from gradebook.dashboard.alerts import alert_text

    data, state = dirs
    today = date(2026, 11, 23)
    text = alert_text(data, state, Rules(), today=today, due_days=2, url="")
    # Alex (7th grade) is sleepy; Sam (4th grade) has nothing due and gets a dancing creature.
    assert "Hoot 🦉 is snoozing 💤 HW 3 (Honors Math) is past due. Turn it in and Hoot wakes up!" in text
    assert "Sam: all clear! Bloop is dancing 🦎🎉" in text

    family.set_creature(state, "1", "10", name="Professor")
    family.set_profile(state, "1", "Lexi", None, None)
    text = alert_text(data, state, Rules(), today=today, due_days=2, url="")
    assert "Lexi:" in text and "Professor 🦉 is snoozing" in text

    # A kid's "I did it!" tap takes it off the text until Skyward catches up.
    family.claim(state, "1:HW 3", "1", today)
    assert alert_text(data, state, Rules(), today=today, due_days=2, url="") == ""


def test_alert_hungry_and_due_soon(dirs, monkeypatch):
    from gradebook.dashboard.alerts import alert_text

    monkeypatch.setenv("KIDS_MOODS", "Alex=hungry")
    data, state = dirs
    text = alert_text(data, state, Rules(), today=date(2026, 11, 18), due_days=2, url="")
    assert "Hoot 🦉 says: Test 2 (Honors Math) is due today." not in text   # already scored
    assert "Hoot 🦉 says: HW 3 (Honors Math) is due tomorrow." in text
    text = alert_text(data, state, Rules(), today=date(2026, 11, 23), due_days=2, url="")
    assert "Hoot 🦉 is hungry: HW 3 (Honors Math) is past due. Turn it in to feed Hoot!" in text
