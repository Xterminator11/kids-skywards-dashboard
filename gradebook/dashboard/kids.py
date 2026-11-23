"""Data for kids mode (the creature island) and the grown-up view.

Plain rules, no AI. Builds one JSON payload from the scraped CSVs plus the family's
saved choices (state/family.json and state/writeoffs.json). The page does the rest.

Per child:
  - one "subject" per numeric-grade course, with a friendly label, a default creature,
    the grade now, the grade at the last check (about DASH_TREND_DAYS ago, default 7),
    and the grade at every progress report / quarter so far
  - letter-grade classes (specials) listed separately
  - every assignment, with a "new" flag when it got a score since the last check
  - the lowest creature mood: "hungry" for elementary, "sleepy" for older kids
    (override with KIDS_MOODS, e.g. "Dithya=hungry,Manya=sleepy")
"""
from __future__ import annotations

import csv
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from . import family, writeoffs
from .rules import Rules, item_state, percent

# Skyward term codes in calendar order (semesters left out: they repeat the quarters).
TERM_ORDER = ["PR1", "PR2", "1ST", "PR3", "PR4", "2ND", "PR5", "PR6", "3RD", "PR7", "PR8", "4TH"]
QUARTERS = ["1ST", "2ND", "3RD", "4TH"]
TERM_LABEL = {"1ST": "Q1", "2ND": "Q2", "3RD": "Q3", "4TH": "Q4"}
STAGES = [0, 8, 20, 40]          # stars needed for egg, baby, grown-up, hero

# (pattern in the course name, label, creature). First match wins.
SUBJECTS = [
    (r"\bMATH", "Math", "owl"),
    (r"\bSCI", "Science", "axolotl"),
    (r"\bTX\b.*\bHIS|TEXAS", "Texas History", "armadillo"),
    (r"\bHIS", "History", "armadillo"),
    (r"SOCIAL", "Social Studies", "armadillo"),
    (r"READING", "Reading", "bunny"),
    (r"\bELAR?\b|ENGLISH|LANG ARTS", "ELAR", "bunny"),
    (r"ORCH", "Orchestra", "fox"),
    (r"\bBAND\b", "Band", "fox"),
    (r"CHOIR", "Choir", "fox"),
    (r"MUSIC", "Music", "fox"),
    (r"\bPE\b|PHYSICAL", "PE", "bear"),
    (r"PHOTO", "Photojournalism", "bug"),
    (r"METAVERSE|COMPUTER|TECH|CODING|STEAM|STEM", None, "robot"),
    (r"\bART\b", "Art", "chick"),
    (r"SPANISH|FRENCH|LANGUAGE", None, "monkey"),
]
SPARE = ["elephant", "giraffe", "lion", "dog", "cat", "car", "monkey"]


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _num(v) -> float | None:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def first_name(student: str) -> str:
    return student.split()[0].capitalize() if student.strip() else student


def subject_label(course: str) -> tuple[str, str | None]:
    """'HONORS MATH 7A' -> ('Honors Math', 'owl'); unknown courses keep a tidy name."""
    up = course.upper()
    honors = up.startswith("HONORS")
    for pattern, label, creature in SUBJECTS:
        if re.search(pattern, up):
            if label is None:
                label = _tidy(course)
            return (f"Honors {label}" if honors and not label.startswith("Honors") else label), creature
    return _tidy(course), None


def _tidy(course: str) -> str:
    words = [w for w in course.split() if not re.fullmatch(r"\d+(ST|ND|RD|TH)?|[AB]|\d+[AB]|GRADE|HONORS|MIDDLE|SCHOOL", w.upper())]
    keep = {"STEAM", "STEM", "PE", "ELAR", "AP"}
    return " ".join(w.upper() if w.upper() in keep else w.capitalize() for w in words) or course.title()


def grade_level(courses: list[str]) -> int | None:
    for c in courses:
        m = re.search(r"\b(\d{1,2})(ST|ND|RD|TH)\b", c.upper())
        if m:
            return int(m.group(1))
    for c in courses:
        m = re.search(r"\b([5-9]|1[0-2])\s?[AB]?\s*$|\b([5-9]|1[0-2])[AB]\b", c.upper())
        if m:
            return int(m.group(1) or m.group(2))
    return None


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _moods_from_env() -> dict[str, str]:
    out = {}
    for part in os.getenv("KIDS_MOODS", "").split(","):
        if "=" in part:
            name, mood = (x.strip() for x in part.split("=", 1))
            if mood.lower() in ("hungry", "sleepy"):
                out[name.lower()] = mood.lower()
    return out


def _snapshots(rows: list[dict]) -> dict[str, list[dict]]:
    by_day: dict[str, list[dict]] = {}
    for r in rows:
        by_day.setdefault((r.get("scraped_at") or "")[:10], []).append(r)
    by_day.pop("", None)
    return by_day


def pick_last_check(days: list[str], latest: str, trend_days: int) -> str | None:
    """The snapshot to compare with: the newest one at least trend_days before the latest,
    else the oldest one before the latest. None when there is only one day of data."""
    earlier = sorted(d for d in days if d < latest)
    if not earlier:
        return None
    cutoff = (date.fromisoformat(latest) - timedelta(days=trend_days)).isoformat()
    old_enough = [d for d in earlier if d <= cutoff]
    return old_enough[-1] if old_enough else earlier[0]


def build_kids_payload(data_dir: Path, state_dir: Path | None, rules: Rules | None = None,
                       now: datetime | None = None) -> dict:
    rules = rules or Rules.from_env()
    data_dir = Path(data_dir)
    state_dir = Path(state_dir) if state_dir is not None else None   # None: no saved family choices
    grades = _read(data_dir / "grades_latest.csv")
    assignments = _read(data_dir / "assignments_latest.csv")
    g_hist = _snapshots(_read(data_dir / "grades_history.csv"))
    a_hist = _snapshots(_read(data_dir / "assignments_history.csv"))
    stamps = [r["scraped_at"] for r in grades + assignments if r.get("scraped_at")]
    scraped = max(stamps) if stamps else datetime.now().isoformat(timespec="seconds")
    data_day = scraped[:10]
    today = date.fromisoformat(data_day)
    trend_days = int(os.getenv("DASH_TREND_DAYS") or "7")
    last_check = pick_last_check(list(g_hist), data_day, trend_days)
    prev_grades = {(r["student_id"], r["course_id"], r["term"]): r["grade"] for r in g_hist.get(last_check or "", [])}
    prev_scored = {writeoffs.item_key(r) for r in a_hist.get(last_check or "", []) if (r.get("score") or "").strip()}

    moods = _moods_from_env()
    kids = []
    for sid in sorted({r["student_id"] for r in grades} | {r["student_id"] for r in assignments}):
        g_rows = [r for r in grades if r["student_id"] == sid]
        a_rows = [r for r in assignments if r["student_id"] == sid]
        student = (g_rows or a_rows)[0]["student"]
        name = first_name(student)
        courses: dict[str, dict] = {}
        for r in g_rows:
            c = courses.setdefault(r["course_id"], {"course": r["course"], "teacher": r.get("teacher", ""), "terms": {}})
            c["terms"][r["term"]] = r["grade"]
        for r in a_rows:
            courses.setdefault(r["course_id"], {"course": r["course"], "teacher": "", "terms": {}})

        level = grade_level([c["course"] for c in courses.values()])
        present = [t for t in TERM_ORDER if any(_num(c["terms"].get(t)) is not None for c in courses.values())]
        quarters = [t for t in present if t in QUARTERS]
        term = quarters[-1] if quarters else (present[-1] if present else "")

        subjects, specials, used = [], [], set()
        for cid, c in courses.items():
            numeric = {t: _num(v) for t, v in c["terms"].items() if t in TERM_ORDER and _num(v) is not None}
            label, creature = subject_label(c["course"])
            if not numeric:
                if c["terms"]:
                    specials.append({"label": label, "grade": c["terms"].get(term) or next(iter(c["terms"].values()))})
                continue
            grade = numeric.get(term)
            if grade is None:
                grade = numeric[[t for t in TERM_ORDER if t in numeric][-1]]
            prev = _num(prev_grades.get((sid, cid, term)))
            if creature is None or creature in used:
                creature = next((s for s in SPARE if s not in used), "robot")
            used.add(creature)
            subjects.append({
                "id": cid, "course": c["course"], "label": label, "teacher": c["teacher"].title(),
                "sp": creature, "grade": grade, "prev": grade if prev is None else prev,
                "terms": {TERM_LABEL.get(t, t): v for t, v in sorted(numeric.items(), key=lambda kv: TERM_ORDER.index(kv[0]))},
            })
        subjects.sort(key=lambda s: s["label"])

        items = []
        for a in a_rows:
            key = writeoffs.item_key(a)
            st = item_state(a, today)
            cat = (a.get("category") or "").upper()
            items.append({
                "key": key, "sub": a["course_id"], "term": a.get("term", ""),
                "cat": "major" if "MAJOR" in cat else "minor" if "MINOR" in cat else "",
                "title": a.get("assignment", ""), "due": a.get("due_date", ""),
                "score": percent(a) if st in ("done", "zero") else None, "st": st,
                "ts": rules.is_teacher_scored(a.get("assignment", "")),
                "new": bool(last_check) and st in ("done", "zero") and key not in prev_scored,
            })
        items.sort(key=lambda i: i["due"] or "9999")
        low = moods.get(name.lower()) or ("hungry" if level is not None and level <= 5 else "sleepy")
        kids.append({
            "id": sid, "name": name, "gradeLabel": f"{_ordinal(level)} grade" if level else "",
            "low": low, "term": term,
            "checkpoints": [TERM_LABEL.get(t, t) for t in present],
            "subjects": subjects, "specials": specials, "items": items,
        })

    kids.sort(key=lambda k: k["name"])
    if state_dir is None:
        state = family._empty()
        family.ensure_season(state, today)
    else:
        state = family.load(state_dir)
        if not state["rewards"].get("season_start"):
            # Save the first season's start once, so the golden bar doesn't reset every month.
            state = family.update(state_dir, lambda d: family.ensure_season(d, today))
    return {
        "scraped": scraped, "today": data_day,
        "now": (now or datetime.now()).date().isoformat(),
        "lastCheck": last_check, "kids": kids,
        "writeoffs": writeoffs.load(state_dir) if state_dir is not None else {}, "family": family.public(state),
        "reasons": writeoffs.REASONS, "stages": STAGES, "rules": rules.to_dict(),
        "defaultPin": not os.getenv("DASH_PARENT_PIN"),
    }
