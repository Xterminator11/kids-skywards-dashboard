"""A tiny web server for the family dashboard (standard library only).

Kids mode is the front door; the grown-up view sits behind a PIN (DASH_PARENT_PIN).

    GET  /                        kids mode: profile picker, creature island, grown-up view
    GET  /classic                 the original parent dashboard (grown-ups only)
    GET  /api/kids                everything kids mode shows, as JSON
    GET  /api/alert-text          today's family alert as plain text ("" when nothing to say)

  Anyone on the home network (the kids' tablets):
    POST /api/claim               {"key", "kid"}       "I did it!"
    POST /api/unclaim             {"key"}
    POST /api/request             {"key", "kid", "reason", "note"}   "Can't do this?"
    POST /api/request/cancel      {"key"}
    POST /api/profile             {"kid", "name", "pic", "theme"}
    POST /api/creature            {"kid", "subject", "sp" | "name"}

  Grown-ups (after POST /api/parent/unlock {"pin"}, which sets a cookie for 12 hours):
    POST /api/parent/lock
    POST /api/request/decide      {"key", "approve": true|false}
    POST /api/writeoffs           {"key", "student", "course", "assignment", "due_date", "reason", "comment"}
    POST /api/writeoffs/remove    {"key"}
    POST /api/rewards/tiers       {"tiers": [{"stars", "reward"}]}
    POST /api/rewards/redeem      {"stars"}
    POST /api/rewards/new-season  {}

Every kids-mode POST answers with the same JSON as GET /api/kids, so the page redraws
from the saved state. Meant for your home network only: don't expose it to the internet.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import threading
import time
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from . import family, writeoffs
from .build import build_payload, render
from .kids import build_kids_payload
from .rules import Rules

log = logging.getLogger(__name__)
MAX_BODY = 4096
MAX_PROFILE_BODY = 200_000
KIDS_TEMPLATE = Path(__file__).with_name("kids.html")
SESSION_SECONDS = 12 * 3600
COOKIE = "kids_parent"


def _today() -> date:
    return datetime.now(ZoneInfo(os.getenv("TZ", "America/Chicago"))).date()


def render_kids(payload: dict) -> str:
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    return KIDS_TEMPLATE.read_text(encoding="utf-8").replace("__KIDS_DATA__", data)


class ParentLock:
    """PIN check with a short lockout after repeated wrong tries, and 12-hour sessions."""

    def __init__(self, pin: str):
        self.pin = pin
        self.sessions: dict[str, float] = {}
        self.fails: list[float] = []
        self._lock = threading.Lock()

    def unlock(self, pin: str) -> str | None:
        with self._lock:
            now = time.time()
            self.fails = [t for t in self.fails if now - t < 300]
            if len(self.fails) >= 5:
                raise PermissionError("Too many wrong tries. Wait 5 minutes.")
            if not hmac.compare_digest(str(pin), self.pin):
                self.fails.append(now)
                return None
            token = secrets.token_urlsafe(24)
            self.sessions = {t: exp for t, exp in self.sessions.items() if exp > now}
            self.sessions[token] = now + SESSION_SECONDS
            return token

    def ok(self, token: str | None) -> bool:
        with self._lock:
            return bool(token) and self.sessions.get(token, 0) > time.time()

    def lock(self, token: str | None) -> None:
        with self._lock:
            self.sessions.pop(token or "", None)


def make_handler(data_dir: Path, state_dir: Path, rules: Rules, pin: str | None = None):
    lock = ParentLock(pin or os.getenv("DASH_PARENT_PIN") or "1234")

    def kids_payload() -> dict:
        return build_kids_payload(data_dir, state_dir, rules, now=datetime.now())

    def find_item(key: str) -> dict:
        """Details of one assignment for writeoffs.json (student, course, name, due date)."""
        p = kids_payload()
        for k in p["kids"]:
            for i in k["items"]:
                if i["key"] == key:
                    sub = next((s for s in k["subjects"] if s["id"] == i["sub"]), {})
                    return {"student": k["name"], "course": sub.get("course", ""), "assignment": i["title"], "due_date": i["due"]}
        return {}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str, headers: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj, headers: dict | None = None) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json", headers)

        def _token(self) -> str | None:
            for part in (self.headers.get("Cookie") or "").split(";"):
                name, _, value = part.strip().partition("=")
                if name == COOKIE:
                    return value
            return None

        def _parent(self) -> bool:
            return lock.ok(self._token())

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                p = kids_payload()
                p["parent"] = self._parent()
                self._send(200, render_kids(p).encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/classic":
                if not self._parent():
                    return self._send(302, b"", "text/plain", {"Location": "/#grownups"})
                html = render(build_payload(data_dir, rules, state_dir=state_dir, interactive=True))
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/kids":
                p = kids_payload()
                p["parent"] = self._parent()
                self._json(200, p)
            elif path == "/api/writeoffs":
                if not self._parent():
                    return self._json(403, {"error": "grown-ups only"})
                self._json(200, writeoffs.load(state_dir))
            elif path == "/api/alert-text":
                from .alerts import alert_text
                self._send(200, alert_text(data_dir, state_dir, rules).encode("utf-8"), "text/plain; charset=utf-8")
            elif path == "/health":
                self._send(200, b"ok", "text/plain")
            else:
                self._send(404, b"Not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            limit = MAX_PROFILE_BODY if path == "/api/profile" else MAX_BODY
            length = int(self.headers.get("Content-Length") or 0)
            if length > limit:
                return self._json(413, {"error": "too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._json(400, {"error": "send a JSON object"})
            today = _today()
            try:
                return self._route(path, body, today)
            except family.Invalid as e:
                return self._json(400, {"error": str(e)})
            except PermissionError as e:
                return self._json(429, {"error": str(e)})

        def _route(self, path: str, b: dict, today: date) -> None:
            S = state_dir
            # Kid actions
            kid_routes = {
                "/api/claim": lambda: family.claim(S, b.get("key"), b.get("kid"), today),
                "/api/unclaim": lambda: family.unclaim(S, b.get("key")),
                "/api/request": lambda: family.request_writeoff(S, b.get("key"), b.get("kid"), b.get("reason"), b.get("note"), today),
                "/api/request/cancel": lambda: family.cancel_request(S, b.get("key")),
                "/api/profile": lambda: family.set_profile(S, b.get("kid"), b.get("name"), b.get("pic"), b.get("theme")),
                "/api/creature": lambda: family.set_creature(S, b.get("kid"), b.get("subject"), b.get("sp"), b.get("name")),
            }
            if path in kid_routes:
                kid_routes[path]()
                return self._kids_ok()

            if path == "/api/parent/unlock":
                token = lock.unlock(str(b.get("pin", ""))[:20])
                if not token:
                    return self._json(403, {"error": "That's not the PIN."})
                cookie = f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_SECONDS}"
                log.info("Grown-up view unlocked")
                return self._kids_ok({"Set-Cookie": cookie}, parent=True)
            if path == "/api/parent/lock":
                lock.lock(self._token())
                return self._kids_ok({"Set-Cookie": f"{COOKIE}=; Path=/; Max-Age=0"}, parent=False)

            if not self._parent():
                return self._json(403, {"error": "Grown-ups only. Unlock with the PIN first."})
            key = str(b.get("key", "")).strip()
            if path == "/api/request/decide":
                family.decide_request(S, key, bool(b.get("approve")), today, item=find_item(key))
                log.info("Write-off request %s %s", key, "approved" if b.get("approve") else "declined")
            elif path == "/api/writeoffs":
                if not key or len(key) > 300:
                    return self._json(400, {"error": "missing key"})
                writeoffs.add(S, key, {**find_item(key), **{k: v for k, v in b.items() if k != "by"}})
                family.update(S, lambda d: (d["requests"].pop(key, None), d["claims"].pop(key, None)))
                log.info("Wrote off %s", key)
            elif path == "/api/writeoffs/remove":
                writeoffs.remove(S, key)
                log.info("Restored %s", key)
            elif path == "/api/rewards/tiers":
                family.set_tiers(S, b.get("tiers"))
            elif path == "/api/rewards/redeem":
                family.redeem(S, b.get("stars"), today)
            elif path == "/api/rewards/new-season":
                family.new_season(S, today)
            else:
                return self._json(404, {"error": "not found"})
            return self._kids_ok()

        def _kids_ok(self, headers: dict | None = None, parent: bool | None = None) -> None:
            p = kids_payload()
            p["parent"] = self._parent() if parent is None else parent
            p["count"] = len(p["writeoffs"])
            self._json(200, p, headers)

        def log_message(self, fmt, *args) -> None:
            log.debug("%s %s", self.address_string(), fmt % args)

    return Handler


def serve(data_dir: Path, state_dir: Path, port: int = 8787, host: str = "0.0.0.0") -> None:
    rules = Rules.from_env()
    pin = os.getenv("DASH_PARENT_PIN", "")
    if not pin:
        log.warning("DASH_PARENT_PIN is not set: the grown-up PIN is 1234. Set it in .env.")
    elif not (pin.isdigit() and len(pin) == 4):
        log.warning("DASH_PARENT_PIN should be exactly 4 digits: the keypad on the page takes 4.")
    server = ThreadingHTTPServer((host, port), make_handler(Path(data_dir), Path(state_dir), rules))
    log.info("Dashboard at http://%s:%d (family choices saved in %s)", host, port, Path(state_dir))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
