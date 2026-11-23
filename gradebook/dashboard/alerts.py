"""The short text for the daily family alert (iMessage / SMS), in the creatures' voices.

Plain rules, no AI: fixed sentences with names and numbers filled in. For each child:
  - missing work this term, one line per class, said by that class's creature (using the
    name the kid gave it), which is "hungry" or "sleepy" just like on the island
  - work due in the next ALERT_DUE_DAYS days (default 2) that has no score yet
  - how many older items from earlier terms are still past due
  - "all clear" with a dancing creature when there's nothing
Written-off, excused and weekly teacher-scored items are left out, like on the dashboard,
and so is anything the kid already tapped "I did it!" on or asked to have written off.
Each child gets their own lines; the kids are never compared.
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

from .kids import build_kids_payload
from .rules import Rules

# Default creature names and emoji, matching kids.html.
CREATURES = {
    "owl": ("Hoot", "🦉"), "axolotl": ("Bloop", "🦎"), "armadillo": ("Dilly", "🦔"),
    "bunny": ("Pages", "🐰"), "fox": ("Fiddle", "🦊"), "bear": ("Bruno", "🐻"),
    "bug": ("Snap", "🐞"), "robot": ("Pixel", "🤖"), "chick": ("Peep", "🐤"),
    "elephant": ("Trunky", "🐘"), "monkey": ("Momo", "🐵"), "giraffe": ("Stretch", "🦒"),
    "lion": ("Leo", "🦁"), "car": ("Zoom", "🚗"), "dog": ("Biscuit", "🐶"), "cat": ("Mochi", "🐱"),
}


def _today() -> date:
    return datetime.now(ZoneInfo(os.getenv("TZ", "America/Chicago"))).date()


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def kid_lines(kid: dict, fam: dict, wo: dict, today: date, due_days: int) -> tuple[list[str], bool]:
    """The lines for one child, and whether there's anything to do."""
    name = fam["profiles"].get(kid["id"], {}).get("name") or kid["name"]
    subjects = {s["id"]: s for s in kid["subjects"]}

    def creature(sub_id: str) -> tuple[str, str] | None:
        s = subjects.get(sub_id)
        if not s:
            return None
        saved = fam["creatures"].get(f"{kid['id']}:{sub_id}", {})
        default_name, emoji = CREATURES.get(saved.get("sp") or s["sp"], ("Buddy", "⭐"))
        return saved.get("name") or default_name, emoji

    def waiting(i: dict) -> bool:
        """Still on the kid's list: not written off, not teacher-scored, not claimed or asked about."""
        req = fam["requests"].get(i["key"], {})
        return (i["st"] in ("open", "overdue") and not i["ts"] and i["key"] not in wo
                and i["key"] not in fam["claims"] and req.get("status") != "pending" and bool(i["due"]))

    late_now: dict[str, list[dict]] = {}
    older, soon = 0, []
    for i in kid["items"]:
        if not waiting(i):
            continue
        days = (date.fromisoformat(i["due"]) - today).days
        if days < 0:
            if i["term"] == kid["term"]:
                late_now.setdefault(i["sub"], []).append(i)
            else:
                older += 1
        elif days <= due_days:
            soon.append(i)

    best = max(kid["subjects"], key=lambda s: s["grade"], default=None)
    c = creature(best["id"]) if best else None
    party = f" {c[0]} is dancing {c[1]}🎉" if c else " 🎉"
    if not late_now and not soon:
        lines = [f"{name}: all clear{' this term' if older else ''}!{party}"]
        if older:
            lines.append(f"  • Still {_plural(older, 'older one', 'older ones')} from earlier terms, past due with no score.")
        return lines, bool(older)

    mood = kid["low"]
    lines = [f"{name}:"]
    for sub_id, items in sorted(late_now.items(), key=lambda kv: -len(kv[1])):
        label = subjects.get(sub_id, {}).get("label", items[0].get("course", "class"))
        what = f"{items[0]['title']} ({label}) is past due" if len(items) == 1 else f"{len(items)} past due in {label}"
        it = "it" if len(items) == 1 else "them"
        c = creature(sub_id)
        if not c:
            lines.append(f"  • {what}.")
        elif mood == "hungry":
            lines.append(f"  • {c[0]} {c[1]} is hungry: {what}. Turn {it} in to feed {c[0]}!")
        else:
            lines.append(f"  • {c[0]} {c[1]} is snoozing 💤 {what}. Turn {it} in and {c[0]} wakes up!")
    for i in sorted(soon, key=lambda i: i["due"]):
        due = date.fromisoformat(i["due"])
        when = "today" if due == today else "tomorrow" if due == today + timedelta(days=1) else due.strftime("%a")
        label = subjects.get(i["sub"], {}).get("label", "")
        what = f"{i['title']} ({label}) is due {when}" if label else f"{i['title']} is due {when}"
        c = creature(i["sub"])
        lines.append(f"  • {c[0]} {c[1]} says: {what}." if c else f"  • {what}.")
    if older:
        lines.append(f"  • Plus {_plural(older, 'older one', 'older ones')} from earlier terms, past due with no score.")
    return lines, True


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
    url = url if url is not None else os.getenv("ALERT_LINK", "https://kids-dashboard.local")
    payload = build_kids_payload(Path(data_dir), state_dir, rules)
    if not payload["kids"]:
        return ""

    lines: list[str] = []
    anything = False
    for kid in payload["kids"]:
        kl, todo = kid_lines(kid, payload["family"], payload["writeoffs"], today, due_days)
        lines += kl
        anything = anything or todo

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
