"""LOGGER agent: writes every kill, score, entry and exit to SQLite. The dashboard reads from here."""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Dict, List

from .models import Pair

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL, kind TEXT NOT NULL, symbol TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT, mint TEXT, pair_address TEXT,
    entry_price REAL, size_usd REAL, qty REAL, stop_price REAL,
    opened_at REAL, closed_at REAL, exit_price REAL, proceeds REAL, pnl REAL, reason TEXT
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
"""


class Ledger:
    def __init__(self, path: str):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ---------- state ----------
    def set(self, key: str, value: Any) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(value)))
            self.db.commit()

    def get(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    # ---------- events ----------
    def log(self, ts: float, kind: str, symbol: str = "", detail: str = "") -> None:
        with self.lock:
            self.db.execute("INSERT INTO events (ts,kind,symbol,detail) VALUES (?,?,?,?)",
                            (ts, kind, symbol, detail))
            self.db.commit()

    # ---------- positions ----------
    def open_position(self, p: Pair, fill: float, size: float, qty: float, stop: float, now: float) -> int:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO positions (symbol,mint,pair_address,entry_price,size_usd,qty,stop_price,opened_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (p.symbol, p.mint, p.pair_address, fill, size, qty, stop, now))
            self.db.commit()
            return int(cur.lastrowid)

    def close_position(self, pid: int, fill: float, proceeds: float, pnl: float, reason: str, now: float) -> None:
        with self.lock:
            self.db.execute(
                "UPDATE positions SET closed_at=?, exit_price=?, proceeds=?, pnl=?, reason=? WHERE id=?",
                (now, fill, proceeds, pnl, reason, pid))
            self.db.commit()

    # ---------- reads for dashboard / reports ----------
    def snapshot(self) -> Dict[str, Any]:
        q = self.db.execute
        closed = [dict(r) for r in q("SELECT * FROM positions WHERE closed_at IS NOT NULL ORDER BY closed_at")]
        wins = [r for r in closed if r["pnl"] > 0]
        return {
            "state": {r["key"]: json.loads(r["value"]) for r in q("SELECT * FROM state")},
            "open": [dict(r) for r in q("SELECT * FROM positions WHERE closed_at IS NULL")],
            "closed": closed[-50:],
            "stats": {
                "trades": len(closed),
                "wins": len(wins),
                "losses": len(closed) - len(wins),
                "best": max((r["pnl"] for r in closed), default=0),
                "worst": min((r["pnl"] for r in closed), default=0),
                "realized": sum(r["pnl"] for r in closed),
            },
            "events": [dict(r) for r in q("SELECT * FROM events ORDER BY id DESC LIMIT 60")],
        }

    def all_closed(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT * FROM positions WHERE closed_at IS NOT NULL")]
