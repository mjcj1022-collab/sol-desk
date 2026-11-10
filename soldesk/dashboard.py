"""Tiny stdlib web server: serves the dashboard page and /api/state from the SQLite ledger."""
from __future__ import annotations

import base64
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .ledger import Ledger

STATIC = os.path.join(os.path.dirname(__file__), "static")


def serve(db_path: str, port: int, host: str = "127.0.0.1", password: str = "") -> ThreadingHTTPServer:
    """Local by default. When exposed (cloud), a password is required: HTTP basic auth, any username."""
    if host not in ("127.0.0.1", "localhost") and not password:
        raise SystemExit("Refusing to expose the dashboard without SOLDESK_DASH_PASSWORD set.")
    ledger = Ledger(db_path)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authed(self) -> bool:
            if not password:
                return True
            h = self.headers.get("Authorization", "")
            if h.startswith("Basic "):
                try:
                    _, _, pw = base64.b64decode(h[6:]).decode().partition(":")
                    if hmac.compare_digest(pw, password):
                        return True
                except Exception:
                    pass
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="sol-desk"')
            self.end_headers()
            return False

        def do_GET(self):
            if self.path == "/healthz":
                return self._send(200, b"ok", "text/plain")
            if not self._authed():
                return
            if self.path.startswith("/api/state"):
                self._send(200, json.dumps(ledger.snapshot(), default=float).encode(), "application/json")
            elif self.path in ("/", "/index.html"):
                with open(os.path.join(STATIC, "index.html"), "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain")

    srv = ThreadingHTTPServer((host, port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
