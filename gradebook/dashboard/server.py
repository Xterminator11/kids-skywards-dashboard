"""A tiny web server for the dashboard (standard library only).

    GET  /                      the dashboard, built fresh from the latest CSVs
    GET  /api/alert-text        today's family alert as plain text ("" when nothing to say)
    POST /api/writeoffs         {"key": ..., "student": ..., "course": ..., "assignment": ..., "due_date": ...}
    POST /api/writeoffs/remove  {"key": ...}

Meant for your home network. Anyone who can reach the port can view the page and
write items off, so don't expose it to the internet.
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import writeoffs
from .build import build_payload, render
from .rules import Rules

log = logging.getLogger(__name__)
MAX_BODY = 4096


def make_handler(data_dir: Path, state_dir: Path, rules: Rules):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                html = render(build_payload(data_dir, rules, state_dir=state_dir, interactive=True))
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/writeoffs":
                self._json(200, writeoffs.load(state_dir))
            elif path == "/api/alert-text":
                from .alerts import alert_text
                self._send(200, alert_text(data_dir, state_dir, rules).encode("utf-8"), "text/plain; charset=utf-8")
            elif path == "/health":
                self._send(200, b"ok", "text/plain")
            else:
                self._send(404, b"Not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._json(413, {"error": "too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                key = str(body.get("key", "")).strip()
            except (ValueError, AttributeError):
                return self._json(400, {"error": "send JSON with a key"})
            if not key or len(key) > 300:
                return self._json(400, {"error": "missing key"})
            if self.path == "/api/writeoffs":
                data = writeoffs.add(state_dir, key, body)
                log.info("Wrote off %s", key)
            elif self.path == "/api/writeoffs/remove":
                data = writeoffs.remove(state_dir, key)
                log.info("Restored %s", key)
            else:
                return self._json(404, {"error": "not found"})
            self._json(200, {"count": len(data)})

        def log_message(self, fmt, *args) -> None:
            log.debug("%s %s", self.address_string(), fmt % args)

    return Handler


def serve(data_dir: Path, state_dir: Path, port: int = 8787, host: str = "0.0.0.0") -> None:
    rules = Rules.from_env()
    server = ThreadingHTTPServer((host, port), make_handler(Path(data_dir), Path(state_dir), rules))
    log.info("Dashboard at http://%s:%d (write-offs saved in %s)", host, port, Path(state_dir) / writeoffs.FILE_NAME)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
