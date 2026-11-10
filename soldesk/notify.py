"""Telegram alerts. Optional: does nothing unless SOLDESK_TG_TOKEN and SOLDESK_TG_CHAT are set.

Setup (2 minutes):
  1. In Telegram, message @BotFather -> /newbot -> copy the token.
  2. Send any message to your new bot, then open
     https://api.telegram.org/bot<TOKEN>/getUpdates  and copy "chat":{"id": ...}.
  3. Put both in .env:
       SOLDESK_TG_TOKEN=123456:ABC...
       SOLDESK_TG_CHAT=987654321
"""
from __future__ import annotations

import json
import os
import queue
import threading
import urllib.request


class Notifier:
    # which event kinds trigger a message; override with SOLDESK_TG_EVENTS=ENTER,WIN,LOSS,...
    DEFAULT_EVENTS = {"START", "ENTER", "WIN", "LOSS", "SKIP", "ERROR"}
    ICON = {"START": "🟣", "ENTER": "⚡", "WIN": "🟢", "LOSS": "🔴", "SKIP": "🛑", "ERROR": "⚠️"}

    def __init__(self, token: str | None = None, chat: str | None = None, events: set[str] | None = None):
        self.token = token if token is not None else os.getenv("SOLDESK_TG_TOKEN", "")
        self.chat = chat if chat is not None else os.getenv("SOLDESK_TG_CHAT", "")
        env_events = os.getenv("SOLDESK_TG_EVENTS")
        self.events = events or ({e.strip().upper() for e in env_events.split(",")} if env_events
                                 else self.DEFAULT_EVENTS)
        self.enabled = bool(self.token and self.chat)
        self.sent: list[str] = []          # kept for tests / debugging
        self._q: "queue.Queue[str]" = queue.Queue()
        self._last_skip = ""
        if self.enabled:
            threading.Thread(target=self._worker, daemon=True).start()

    def event(self, kind: str, symbol: str, detail: str, equity: float | None = None) -> None:
        if kind not in self.events:
            return
        if kind == "SKIP":                 # only alert on the kill switch, and only once per reason
            if "kill switch" not in detail or detail == self._last_skip:
                return
            self._last_skip = detail
        coin = f" ${symbol}" if symbol else ""
        text = f"{self.ICON.get(kind, '•')} [PAPER] {kind}{coin}\n{detail}"
        if equity is not None:
            text += f"\nequity ${equity:.2f}"
        self.sent.append(text)
        if self.enabled:
            self._q.put(text)

    def _worker(self) -> None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        while True:
            text = self._q.get()
            body = json.dumps({"chat_id": self.chat, "text": text, "disable_web_page_preview": True}).encode()
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=10).read()
            except Exception:
                pass  # alerts must never break trading
