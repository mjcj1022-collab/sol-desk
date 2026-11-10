"""The loop that wires the six agents together with hard handoffs."""
from __future__ import annotations

import time
from typing import Dict, Optional

from .agents import Analyst, Filter, PaperExecutor, Risk, Scout
from .config import Config
from .ledger import Ledger
from .market import LiveDataMarket, MarketSource, MockMarket
from .models import Position
from .notify import Notifier


class Engine:
    def __init__(self, cfg: Config, market: Optional[MarketSource] = None, fast: bool = False):
        self.cfg = cfg
        self.fast = fast  # mock: don't actually sleep, advance a simulated clock instead
        self.market = market or (MockMarket(tick_s=cfg.tick_seconds) if cfg.mode == "mock" else LiveDataMarket())
        self.ledger = Ledger(cfg.db_path)
        self.notifier = Notifier()
        self.scout = Scout(cfg, self.market)
        self.filter = Filter(cfg, self.market)
        self.analyst = Analyst(cfg)
        self.executor = PaperExecutor(cfg, self.ledger)
        self.risk = Risk(cfg)
        self.positions: Dict[int, Position] = {}
        self.cash = cfg.starting_balance
        self.start_ts = time.time()
        self.clock = self.start_ts
        self.ticks = 0
        self.ledger.set("config", {k: getattr(cfg, k) for k in cfg.__dataclass_fields__})
        self._log(self.clock, "START", "", f"mode={cfg.mode} balance=${cfg.starting_balance:.2f} (PAPER)")

    # ------------------------------------------------------------------
    def _log(self, ts: float, kind: str, symbol: str = "", detail: str = "") -> None:
        self.ledger.log(ts, kind, symbol, detail)
        eq = self.equity() if hasattr(self, "positions") else self.cfg.starting_balance
        self.notifier.event(kind, symbol, detail, eq)

    def now(self) -> float:
        return self.clock if self.fast else time.time()

    def equity(self) -> float:
        return self.cash + sum(p.qty * p.last_price for p in self.positions.values())

    def _manage_open(self) -> None:
        if not self.positions:
            return
        prices = self.market.prices([p.pair_address for p in self.positions.values()])
        for pid, pos in list(self.positions.items()):
            price = prices.get(pos.pair_address)
            if price is None:
                continue
            reason = self.risk.check(pos, price, self.now())
            if reason:
                proceeds = self.executor.sell(pos, price, reason, self.now())
                self.cash += proceeds
                pnl = proceeds - pos.size_usd
                kind = "WIN" if pnl > 0 else "LOSS"
                self._log(self.now(), kind, pos.symbol,
                                f"{pnl:+.2f} ({pnl / pos.size_usd * 100:+.1f}%) exit={reason}")
                del self.positions[pid]

    def _hunt(self) -> None:
        for pair in self.scout.run():
            ok, why = self.filter.run(pair)
            if not ok:
                self._log(self.now(), "KILL", pair.symbol, why)
                continue
            score, _ = self.analyst.run(pair)
            if score < self.cfg.min_score:
                self._log(self.now(), "SCORE", pair.symbol, f"{score} < {self.cfg.min_score} dropped")
                continue
            self._log(self.now(), "SCORE", pair.symbol, f"{score} -> executor")
            if any(p.mint == pair.mint for p in self.positions.values()):
                continue
            allowed, why = self.risk.can_open(self.equity(), self.cfg.starting_balance, len(self.positions))
            if not allowed:
                self._log(self.now(), "SKIP", pair.symbol, why)
                continue
            pos = self.executor.buy(pair, self.cash, self.now())
            if pos:
                self.cash -= pos.size_usd
                self.positions[pos.id] = pos
                self._log(self.now(), "ENTER", pair.symbol,
                                f"${pos.size_usd:.2f} @ {pos.entry_price:.8f} stop -{self.cfg.stop_loss_pct}% set")

    def _publish(self) -> None:
        self.ledger.set("live", {
            "mode": self.cfg.mode, "running": True, "ticks": self.ticks,
            "cash": self.cash, "equity": self.equity(), "start_balance": self.cfg.starting_balance,
            "started_at": self.start_ts, "now": self.now(),
            "agents": {"scout_seen": self.scout.seen, "filter_killed": self.filter.killed,
                       "analyst_scored": self.analyst.scored, "risk_stops": self.risk.stops,
                       "open": len(self.positions)},
            "positions": [{"symbol": p.symbol, "entry": p.entry_price, "last": p.last_price,
                           "stop": p.stop_price, "pnl_pct": p.pnl_pct, "size": p.size_usd,
                           "trailing": p.trailing} for p in self.positions.values()],
        })

    def tick(self) -> None:
        self.ticks += 1
        try:
            self._manage_open()   # risk first: protect what's open
            self._hunt()
        except Exception as e:   # network blips etc. never kill the loop
            self._log(self.now(), "ERROR", "", repr(e)[:200])
        self._publish()

    def run(self, max_ticks: Optional[int] = None) -> None:
        try:
            while max_ticks is None or self.ticks < max_ticks:
                self.tick()
                if self.fast:
                    self.clock += self.cfg.tick_seconds
                else:
                    time.sleep(self.cfg.tick_seconds)
        except KeyboardInterrupt:
            pass
        finally:
            live = self.ledger.get("live", {})
            live["running"] = False
            self.ledger.set("live", live)
            self.market.close()
