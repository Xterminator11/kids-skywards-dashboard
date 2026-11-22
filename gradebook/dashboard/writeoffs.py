"""Assignments the family has written off (old work that can't be made up).

Kept in STATE_DIR/writeoffs.json, separate from the scraped data, so a new scrape never
brings them back. Each entry is keyed by student id + assignment id:

    {"120121:3152510": {"student": "...", "course": "...", "assignment": "...",
                        "due_date": "2026-10-06", "reason": "excused",
                        "comment": "Teacher said it doesn't count",
                        "written_off_at": "2026-11-22T09:10:00"}}
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path

FILE_NAME = "writeoffs.json"
# Why something was written off (shown in the page's drop-down). Unknown values become "other".
REASONS = {
    "turned_in": "Turned in",
    "excused": "Excused",
    "cannot_complete": "Cannot be completed",
    "other": "Other",
}
MAX_COMMENT = 500
_lock = threading.Lock()


def item_key(row: dict) -> str:
    """Stable id for one assignment of one student, across scrapes."""
    if row.get("assignment_id"):
        return f"{row.get('student_id', '')}:{row['assignment_id']}"
    return ":".join(row.get(k, "") for k in ("student_id", "course_id", "assignment", "due_date"))


def load(state_dir: Path) -> dict[str, dict]:
    path = Path(state_dir) / FILE_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(state_dir: Path, data: dict[str, dict]) -> None:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=state_dir, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, state_dir / FILE_NAME)


def add(state_dir: Path, key: str, details: dict) -> dict[str, dict]:
    with _lock:
        data = load(state_dir)
        data[key] = {
            **{k: str(details.get(k, ""))[:200] for k in ("student", "course", "assignment", "due_date")},
            "reason": reason if (reason := str(details.get("reason", ""))) in REASONS else "other",
            "comment": str(details.get("comment", "")).strip()[:MAX_COMMENT],
            "written_off_at": datetime.now().isoformat(timespec="seconds"),
        }
        _save(state_dir, data)
        return data


def remove(state_dir: Path, key: str) -> dict[str, dict]:
    with _lock:
        data = load(state_dir)
        if data.pop(key, None) is not None:
            _save(state_dir, data)
        return data
