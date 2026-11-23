"""What the family chose in kids mode, saved in STATE_DIR/family.json.

Kept apart from the scraped data, so a new scrape never wipes it:

    claims     "I did it!" taps: {item key: {"kid": student id, "at": "2026-11-23"}}
               A claim turns "verified" by itself once Skyward shows a score.
    requests   "Can't do this?" asks waiting for a grown-up, or turned down:
               {item key: {"kid", "reason", "note", "status": "pending"|"declined", "at", "decided_at"}}
               An approved ask moves to writeoffs.json (see writeoffs.py) and leaves here.
    profiles   {student id: {"name", "pic": {"type": "char", "sp": "lion"} or
               {"type": "photo", "data": "data:image/jpeg;base64,..."}, "theme"}}
    creatures  {student id + ":" + course id: {"sp": "lion", "name": "Leo"}}
    rewards    {"tiers": [{"stars": 100, "reward": "Pizza night"}, ...],
                "season_start": "2026-11-01", "redeemed": [{"stars", "reward", "at"}]}
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import date
from pathlib import Path

FILE_NAME = "family.json"
SPECIES = {"owl", "axolotl", "armadillo", "bunny", "fox", "bear", "bug", "robot", "chick",
           "elephant", "monkey", "giraffe", "lion", "car", "dog", "cat"}
THEMES = {"berry", "teal", "grape", "ocean", "sunset", "leaf"}
REASONS = {"turned_in", "excused", "cannot_complete", "other"}
DEFAULT_TIERS = [{"stars": 100, "reward": "Pizza night"}, {"stars": 200, "reward": "Netflix House"}]
MAX_PHOTO = 150_000          # characters of a data: URL (a 240 px JPEG is ~20-40 KB)
_lock = threading.RLock()


class Invalid(ValueError):
    """Bad input from the page; the server answers 400 with this message."""


def _empty() -> dict:
    return {"claims": {}, "requests": {}, "profiles": {}, "creatures": {},
            "rewards": {"tiers": [dict(t) for t in DEFAULT_TIERS], "season_start": "", "redeemed": []}}


def load(state_dir: Path) -> dict:
    try:
        data = json.loads((Path(state_dir) / FILE_NAME).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    base = _empty()
    if isinstance(data, dict):
        for k in base:
            if isinstance(data.get(k), type(base[k])):
                base[k] = data[k]
    base["rewards"] = {**_empty()["rewards"], **base["rewards"]}
    return base


def save(state_dir: Path, data: dict) -> None:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=state_dir, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, state_dir / FILE_NAME)


def ensure_season(data: dict, today: date) -> None:
    """The first season starts on the 1st of the current month."""
    if not data["rewards"].get("season_start"):
        data["rewards"]["season_start"] = today.replace(day=1).isoformat()


def public(data: dict) -> dict:
    return data


def _text(v, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n].strip()


def _key(v) -> str:
    k = _text(v, 120)
    if not k:
        raise Invalid("missing key")
    return k


def update(state_dir: Path, fn) -> dict:
    """Load, change with fn(data), save, return the new data (one writer at a time)."""
    with _lock:
        data = load(state_dir)
        fn(data)
        save(state_dir, data)
        return data


# ---- kid actions (no PIN) ----

def claim(state_dir, key, kid, today: date) -> dict:
    key, kid = _key(key), _key(kid)
    return update(state_dir, lambda d: d["claims"].__setitem__(key, {"kid": kid, "at": today.isoformat()}))


def unclaim(state_dir, key) -> dict:
    key = _key(key)
    return update(state_dir, lambda d: d["claims"].pop(key, None))


def request_writeoff(state_dir, key, kid, reason, note, today: date) -> dict:
    key, kid = _key(key), _key(kid)
    reason = reason if reason in REASONS else "other"
    return update(state_dir, lambda d: d["requests"].__setitem__(
        key, {"kid": kid, "reason": reason, "note": _text(note, 200), "status": "pending", "at": today.isoformat()}))


def cancel_request(state_dir, key) -> dict:
    key = _key(key)
    return update(state_dir, lambda d: d["requests"].pop(key, None) if d["requests"].get(key, {}).get("status") == "pending" else None)


def set_profile(state_dir, kid, name, pic, theme) -> dict:
    kid = _key(kid)
    prof: dict = {"name": _text(name, 20)}
    if isinstance(pic, dict) and pic.get("type") == "photo":
        data_url = str(pic.get("data", ""))
        if not re.fullmatch(r"data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+", data_url) or len(data_url) > MAX_PHOTO:
            raise Invalid("photo must be a small JPEG or PNG")
        prof["pic"] = {"type": "photo", "data": data_url}
    elif isinstance(pic, dict) and pic.get("sp") in SPECIES:
        prof["pic"] = {"type": "char", "sp": pic["sp"]}
    if theme in THEMES:
        prof["theme"] = theme

    def fn(d):
        if not prof["name"] and "pic" not in prof and "theme" not in prof:
            d["profiles"].pop(kid, None)
        else:
            d["profiles"][kid] = prof
    return update(state_dir, fn)


def set_creature(state_dir, kid, subject, sp=None, name=None) -> dict:
    k = f"{_key(kid)}:{_key(subject)}"

    def fn(d):
        c = d["creatures"].setdefault(k, {})
        if sp is not None:
            if sp not in SPECIES:
                raise Invalid("unknown character")
            c["sp"] = sp
            c.pop("name", None)          # a new character gets its own name
        if name is not None:
            c["name"] = _text(name, 16)
            if not c["name"]:
                c.pop("name")
        if not c:
            d["creatures"].pop(k)
    return update(state_dir, fn)


# ---- grown-up actions (PIN) ----

def decide_request(state_dir, key, approve: bool, today: date, item: dict | None = None) -> dict:
    """Approve: the item goes to writeoffs.json (by "kid") and leaves the requests list.
    Turn down: it stays here as "declined" so the kid sees it's back on their list."""
    from . import writeoffs
    key = _key(key)

    def fn(d):
        req = d["requests"].get(key)
        if not req or req.get("status") != "pending":
            raise Invalid("no request waiting for that item")
        if approve:
            writeoffs.add(state_dir, key, {**(item or {}), "reason": req["reason"], "comment": req.get("note", ""),
                                           "by": "kid", "requested_at": req.get("at", "")})
            d["requests"].pop(key)
            d["claims"].pop(key, None)
        else:
            req.update(status="declined", decided_at=today.isoformat())
    return update(state_dir, fn)


def set_tiers(state_dir, tiers) -> dict:
    clean = []
    for t in tiers if isinstance(tiers, list) else []:
        try:
            stars = int(t.get("stars"))
        except (TypeError, ValueError, AttributeError):
            continue
        reward = _text(t.get("reward"), 40)
        if stars > 0 and reward:
            clean.append({"stars": min(stars, 100_000), "reward": reward})
    if not clean:
        raise Invalid("add at least one reward with a star level")
    clean.sort(key=lambda t: t["stars"])
    return update(state_dir, lambda d: d["rewards"].__setitem__("tiers", clean[:12]))


def redeem(state_dir, stars, today: date) -> dict:
    def fn(d):
        tier = next((t for t in d["rewards"]["tiers"] if t["stars"] == int(stars)), None)
        if not tier:
            raise Invalid("no reward at that level")
        if any(r["stars"] == tier["stars"] for r in d["rewards"]["redeemed"]):
            return
        d["rewards"]["redeemed"].append({**tier, "at": today.isoformat()})
    return update(state_dir, fn)


def new_season(state_dir, today: date) -> dict:
    def fn(d):
        d["rewards"]["season_start"] = today.isoformat()
        d["rewards"]["redeemed"] = []
    return update(state_dir, fn)
