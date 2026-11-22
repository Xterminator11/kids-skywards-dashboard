"""Plain, rule-based metrics for the family dashboard.

No AI or model calls: every number and alert comes from fixed rules over the scraped
CSVs, so building the dashboard is free and gives the same answer every time.
All thresholds live in `Rules` and can be changed in .env (see `Rules.from_env`).
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from datetime import date

# Order in which Skyward terms appear during the fall semester.
PROGRESS_TERMS = ["PR1", "PR2", "PR3", "PR4"]
QUARTER_TERMS = ["1ST", "2ND"]


@dataclass(frozen=True)
class Rules:
    """The settings block. Change these in .env with the DASH_* names below."""

    failing_below: float = 70      # DASH_FAILING_BELOW: red "failing" alert
    watch_below: float = 80        # DASH_WATCH_BELOW: amber "below a B" alert
    strong_at: float = 90          # DASH_STRONG_AT: green "doing well"
    drop_points: float = 10        # DASH_DROP_POINTS: quarter-over-quarter drop worth flagging
    gap_points: float = 10         # DASH_GAP_POINTS: tests vs daily-work gap worth explaining
    # DASH_TEACHER_SCORED: items the teacher scores weekly (hidden by default in lists)
    teacher_scored_pattern: str = r"participation|good character|rehearsal week"

    @classmethod
    def from_env(cls) -> "Rules":
        def num(name: str, default: float) -> float:
            value = os.getenv(name, "").strip()
            return float(value) if value else default

        d = cls()
        return cls(
            failing_below=num("DASH_FAILING_BELOW", d.failing_below),
            watch_below=num("DASH_WATCH_BELOW", d.watch_below),
            strong_at=num("DASH_STRONG_AT", d.strong_at),
            drop_points=num("DASH_DROP_POINTS", d.drop_points),
            gap_points=num("DASH_GAP_POINTS", d.gap_points),
            teacher_scored_pattern=os.getenv("DASH_TEACHER_SCORED", "").strip()
            or d.teacher_scored_pattern,
        )

    def is_teacher_scored(self, name: str) -> bool:
        return bool(re.search(self.teacher_scored_pattern, name, re.IGNORECASE))

    def to_dict(self) -> dict:
        return asdict(self)


def _num(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def percent(row: dict) -> float | None:
    """Score as a percent: points earned / possible, else the score itself if numeric."""
    earned, possible = _num(row.get("points_earned")), _num(row.get("points_possible"))
    if earned is not None and possible:
        return round(earned / possible * 100, 1)
    return _num(row.get("score"))


def item_state(row: dict, today: date) -> str:
    """One of: exempt, done, zero, overdue, open.

    Excused work (a teacher's "Excused" note) is exempt: never a zero or past due.

    "overdue" means no score and the due date is before `today`. Skyward can't tell
    "not turned in" from "not graded yet", so overdue may include ungraded work.
    """
    if row.get("status") == "exempt" or "excused" in (row.get("flags") or "").split(";"):
        return "exempt"
    if (row.get("score") or "").strip():
        return "zero" if percent(row) == 0 else "done"
    due = row.get("due_date") or ""
    if due and date.fromisoformat(due) < today:
        return "overdue"
    return "open"


def _avg(values: list[float]) -> int | None:
    return round(sum(values) / len(values)) if values else None


def course_summaries(
    grades: list[dict], assignments: list[dict], student: str, today: date, rules: Rules
) -> list[dict]:
    """One row per course for `student`: current grade, change, trend and work counts."""
    by_course: dict[str, dict] = {}
    for g in grades:
        if g["student"] != student:
            continue
        c = by_course.setdefault(g["course"], {"course": g["course"], "teacher": g.get("teacher", ""), "terms": {}})
        c["terms"][g["term"]] = g["grade"]

    rows = []
    for c in by_course.values():
        terms = c["terms"]
        q1, q2 = _num(terms.get("1ST")), _num(terms.get("2ND"))
        current = q2 if q2 is not None else q1
        progress = [(t, _num(terms.get(t))) for t in PROGRESS_TERMS if _num(terms.get(t)) is not None]
        quarters = [(t, _num(terms.get(t))) for t in QUARTER_TERMS if _num(terms.get(t)) is not None]
        series = progress if len(progress) >= 3 else quarters

        items = [a for a in assignments if a["student"] == student and a["course"] == c["course"]]
        states = [(a, item_state(a, today)) for a in items]
        scored = [(a, percent(a)) for a, s in states if s in ("done", "zero") and percent(a) is not None]
        rows.append({
            "course": c["course"],
            "teacher": c["teacher"],
            "current": current,
            "q1": q1,
            "q2": q2,
            "change": (q2 - q1) if q1 is not None and q2 is not None else None,
            "series": series,
            "letter": None if current is not None else (terms.get("2ND") or terms.get("1ST") or terms.get("SM1")),
            "zeros": sum(1 for _, s in states if s == "zero"),
            "late": sum(
                1 for a, s in states
                if s == "overdue" and not rules.is_teacher_scored(a.get("assignment", ""))
            ),
            "tests_avg": _avg([p for a, p in scored if "MAJOR" in (a.get("category") or "").upper()]),
            "daily_avg": _avg([p for a, p in scored if "MINOR" in (a.get("category") or "").upper()]),
        })
    # Numeric grades first, worst first; letter-grade classes (specials) last.
    rows.sort(key=lambda r: (r["current"] is None, r["current"] if r["current"] is not None else 0))
    return rows


def _fmt(n: float) -> str:
    return f"{n:g}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def lagging_alerts(courses: list[dict], rules: Rules, pretty=lambda s: s) -> list[dict]:
    """Turn course rows into plain-language alerts, worst first.

    Rules, in order (a course gets at most one alert):
      1. failing:  current grade below failing_below                     -> red
      2. dropped:  2nd quarter is drop_points or more below the 1st       -> amber
      3. watch:    current grade below watch_below                        -> amber
    Plus one green line listing classes at or above strong_at.
    Each alert explains itself with zeros, past-due counts and the tests-vs-daily gap.
    """
    alerts = []
    for r in courses:
        cur = r["current"]
        if cur is None:
            continue
        name = pretty(r["course"])
        facts = []
        dropped = r["change"] is not None and r["change"] <= -rules.drop_points
        if r["change"] is not None and r["change"] < 0 and (cur < rules.failing_below or not dropped):
            pts = _fmt(-r["change"])
            facts.append(f"Down {pts} point{'' if pts == '1' else 's'} from {_fmt(r['q1'])} last quarter.")
        if r["zeros"]:
            facts.append(f"{_plural(r['zeros'], 'zero')} this term.")
        if r["late"]:
            facts.append(f"{_plural(r['late'], 'item')} past due with no score.")
        t, d = r["tests_avg"], r["daily_avg"]
        if t is not None and d is not None:
            if d - t >= rules.gap_points:
                facts.append(f"Tests and projects ({t}) are well below daily work ({d}), "
                             "which points to understanding more than effort.")
            elif t - d >= rules.gap_points:
                facts.append(f"Daily work ({d}) is well below tests ({t}), "
                             "which points to effort or organization.")

        if cur < rules.failing_below:
            alerts.append({"level": "bad", "rank": 300 - cur,
                           "title": f"{name} is failing at {_fmt(cur)}.", "why": " ".join(facts)})
        elif dropped:
            alerts.append({"level": "warn", "rank": 200 - r["change"] - 100,
                           "title": f"{name} dropped {_fmt(-r['change'])} points, from {_fmt(r['q1'])} to {_fmt(r['q2'])}.",
                           "why": " ".join(facts) or "Nothing missing, so check recent test scores."})
        elif cur < rules.watch_below:
            alerts.append({"level": "warn", "rank": rules.watch_below - cur,
                           "title": f"{name} is at {_fmt(cur)}, below a B.",
                           "why": " ".join(facts) or "Nothing missing, so the scores themselves are the issue."})

    strong = [pretty(r["course"]) for r in courses if r["current"] is not None and r["current"] >= rules.strong_at]
    if strong:
        alerts.append({"level": "good", "rank": -1,
                       "title": f"Doing well in {', '.join(strong)}.", "why": "Worth saying out loud at dinner."})
    alerts.sort(key=lambda a: a["rank"], reverse=True)
    return alerts
