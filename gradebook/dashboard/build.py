"""Build the family dashboard: data/site/index.html, one self-contained page.

Reads grades_latest.csv and assignments_latest.csv, works out the metrics with the
rules in rules.py, and writes them into template.html. The page needs no server code:
open the file, or let docker compose serve it on your home network.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from datetime import date, datetime
from pathlib import Path

from . import writeoffs
from .rules import Rules, course_summaries, item_state, lagging_alerts, percent

log = logging.getLogger(__name__)

TEMPLATE = Path(__file__).with_name("template.html")
KEEP_UPPER = {"PE", "ELAR", "TX", "STEAM", "MV", "DOK", "LAB", "II", "III"}


def pretty_course(name: str) -> str:
    """'HONORS MATH 7A' -> 'Honors Math 7A'; keeps short acronyms and drops a trailing ' A'."""
    words = []
    for w in name.split():
        words.append(w if w in KEEP_UPPER or any(ch.isdigit() for ch in w) else w.capitalize())
    out = " ".join(words)
    out = out.replace("4TH ", "4th ", 1) if out.startswith("4TH ") else out
    return out[:-2] if out.endswith(" A") else out


def first_name(student: str) -> str:
    return student.split()[0].capitalize() if student.strip() else student


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_payload(
    data_dir: Path, rules: Rules | None = None, state_dir: Path | None = None, interactive: bool = False
) -> dict:
    """Everything the page shows. Written-off assignments (state_dir/writeoffs.json) are
    left out of every count, average and alert, and listed separately so they can be
    restored. `interactive` turns on the write-off buttons (only when served)."""
    rules = rules or Rules()
    grades = _read(data_dir / "grades_latest.csv")
    assignments = _read(data_dir / "assignments_latest.csv")
    written_off = writeoffs.load(state_dir) if state_dir else {}
    stamps = [r["scraped_at"] for r in assignments + grades if r.get("scraped_at")]
    scraped = max(stamps) if stamps else datetime.now().isoformat(timespec="seconds")
    today = date.fromisoformat(scraped[:10])
    counted = [a for a in assignments if writeoffs.item_key(a) not in written_off]

    students = sorted({r["student"] for r in grades} | {r["student"] for r in assignments})
    kids = []
    for student in students:
        courses = course_summaries(grades, counted, student, today, rules)
        for c in courses:
            c["name"] = pretty_course(c["course"])
        kids.append({
            "name": first_name(student),
            "courses": courses,
            "alerts": lagging_alerts(courses, rules, pretty_course),
        })

    items = []
    for a in assignments:
        key = writeoffs.item_key(a)
        items.append({
            "key": key,
            "k": first_name(a["student"]),
            "c": pretty_course(a["course"]),
            "cat": a.get("category", ""),
            "n": a.get("assignment", ""),
            "d": a.get("due_date", ""),
            "p": percent(a),
            "st": item_state(a, today),
            "f": a.get("flags", ""),
            "note": a.get("notes", ""),
            "ts": rules.is_teacher_scored(a.get("assignment", "")),
            "wo": key in written_off,
            "wo_reason": written_off.get(key, {}).get("reason", ""),
            "wo_comment": written_off.get(key, {}).get("comment", ""),
        })
    return {"scraped": scraped, "today": today.isoformat(), "kids": kids, "items": items,
            "rules": rules.to_dict(), "interactive": interactive, "reasons": writeoffs.REASONS}


def render(payload: dict) -> str:
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", data)


def build_dashboard(data_dir: Path, rules: Rules | None = None, state_dir: Path | None = None) -> Path:
    """Write data_dir/site/index.html (read-only copy, no write-off buttons) and return its path."""
    data_dir = Path(data_dir)
    site = data_dir / "site"
    site.mkdir(parents=True, exist_ok=True)
    html = render(build_payload(data_dir, rules or Rules.from_env(), state_dir=state_dir))
    fd, tmp = tempfile.mkstemp(dir=site, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(html)
    os.chmod(tmp, 0o644)
    out = site / "index.html"
    os.replace(tmp, out)
    log.info("Dashboard written to %s", out)
    return out
