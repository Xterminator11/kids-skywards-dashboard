"""The short text for the daily family alert (iMessage / SMS).

Plain rules, no AI. For each child it lists:
  - work due in the next ALERT_DUE_DAYS days (default 2) that has no score yet
  - how many items are past due with no score
Written-off, excused and weekly teacher-scored items are left out, like on the dashboard.
Returns "" when there is nothing to say, so no message goes out on quiet days.

The Docker container only builds the text (GET /api/alert-text on the dashboard, or
`python -m gradebook alert-text`). Sending happens on the Mac itself:
deploy/send-alerts.sh uses the Messages app.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .build import build_payload
from .rules import Rules


def _today() -> date:
    return datetime.now(ZoneInfo(os.getenv("TZ", "America/Chicago"))).date()


def alert_text(
    data_dir: Path,
    state_dir: Path | None = None,
    rules: Rules | None = None,
    today: date | None = None,
    due_days: int | None = None,
    url: str | None = None,
) -> str:
    rules = rules or Rules.from_env()
    today = today or _today()
    due_days = due_days if due_days is not None else int(os.getenv("ALERT_DUE_DAYS", "2"))
    url = url if url is not None else os.getenv("ALERT_LINK", "http://kids-dashboard.local")
    payload = build_payload(Path(data_dir), rules, state_dir=state_dir)
    if not payload["kids"]:
        return ""

    lines: list[str] = []
    anything = False
    for kid in payload["kids"]:
        name = kid["name"]
        items = [i for i in payload["items"] if i["k"] == name and not i["wo"] and not i["ts"]]
        soon = []
        late = 0
        for i in items:
            if i["st"] not in ("open", "overdue") or not i["d"]:
                continue
            due = date.fromisoformat(i["d"])
            days = (due - today).days
            if days < 0:
                late += 1
            elif days <= due_days:
                soon.append((due, i))
        soon.sort(key=lambda x: x[0])
        if not soon and not late:
            lines.append(f"{name}: all clear ✓")
            continue
        anything = True
        lines.append(f"{name}:")
        for due, i in soon:
            when = "today" if due == today else "tomorrow" if due == today + timedelta(days=1) else due.strftime("%a")
            lines.append(f"  • {i['n']} ({i['c']}) due {when}")
        if late:
            lines.append(f"  • {late} past due with no score")

    if not anything:
        return ""
    header = f"📚 Homework check, {today.strftime('%a %b')} {today.day}"
    scraped = date.fromisoformat(payload["today"])
    footer = []
    if (today - scraped).days >= 2:
        footer.append(f"(Skyward data is from {scraped.strftime('%b')} {scraped.day}; the last check may have failed.)")
    if url:
        footer.append(url)
    return "\n".join([header, *lines, *footer])
