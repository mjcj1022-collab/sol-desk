"""The six agents. Each has exactly one job and hands off to the next.

SCOUT -> FILTER -> ANALYST -> EXECUTOR -> RISK -> LOGGER
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .config import Config
from .ledger import Ledger
from .market import MarketSource
from .models import Pair, Position


# ---------------------------------------------------------------- SCOUT
class Scout:
    """Finds fresh pairs inside the age / market-cap window."""

    def __init__(self, cfg: Config, market: MarketSource):
        self.cfg, self.market = cfg, market
        self.seen = 0

    def run(self) -> List[Pair]:
        found = self.market.discover()
        self.seen += len(found)
        c = self.cfg
        return [p for p in found
                if c.min_age_min <= p.age_min <= c.max_age_hr * 60
                and c.min_mcap <= p.mcap <= c.max_mcap]


# ---------------------------------------------------------------- FILTER
class Filter:
    """8 hard rules. One fail = killed. Unknown data = fail (fail closed)."""

    def __init__(self, cfg: Config, market: MarketSource):
        self.cfg, self.market = cfg, market
        self.killed = 0

    def rules(self, p: Pair) -> List[Tuple[str, Optional[bool]]]:
        c = self.cfg
        def chk(v, cond):
            return None if v is None else bool(cond(v))
        return [
            ("mint/freeze revoked", None if p.mint_revoked is None or p.freeze_revoked is None
                                    else (p.mint_revoked and p.freeze_revoked)),
            ("LP burned/locked",    chk(p.lp_locked_pct, lambda v: v >= c.min_lp_locked_pct)),
            ("liquidity",           p.liquidity >= c.min_liquidity),
            ("1h volume",           p.vol_1h >= c.min_vol_1h),
            ("top10 holders",       chk(p.top10_pct, lambda v: v <= c.max_top10_pct)),
            ("dev holdings",        chk(p.dev_pct, lambda v: v <= c.max_dev_pct)),
            ("bundled launch",      chk(p.bundled_pct, lambda v: v <= c.max_bundled_pct)),
            ("1h pump cap",         p.change_1h <= c.max_pump_1h_pct),
        ]

    def run(self, p: Pair) -> Tuple[bool, str]:
        self.market.enrich(p)
        for name, ok in self.rules(p):
            if ok is None:
                self.killed += 1
                return False, f"{name}: no data"
            if not ok:
                self.killed += 1
                return False, name
        return True, "8/8 rules"


# ---------------------------------------------------------------- ANALYST
class Analyst:
    """Scores survivors 0-100. Only >= min_score gets handed to the Executor."""

    WEIGHTS = {"momentum": 0.22, "buy_sell": 0.20, "unique_buyers": 0.15,
               "holder_growth": 0.15, "liq_mcap": 0.13, "smart_wallets": 0.15}

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.scored = 0

    @staticmethod
    def _clamp(x: float) -> float:
        return max(0.0, min(100.0, x))

    def components(self, p: Pair) -> Dict[str, Optional[float]]:
        ratio = p.buys_1h / max(1, p.sells_1h)
        liq_ratio = p.liquidity / max(1, p.mcap)
        return {
            # positive but not parabolic 5m move, backed by volume
            "momentum": self._clamp(50 + p.change_5m * 4 - max(0, p.change_5m - 15) * 6),
            "buy_sell": self._clamp((ratio - 0.8) / 1.0 * 100),
            "unique_buyers": self._clamp(p.buys_1h / 6),
            "holder_growth": None if p.holder_growth_pct is None else self._clamp(p.holder_growth_pct * 2.5),
            "liq_mcap": self._clamp(liq_ratio / 0.15 * 100),
            "smart_wallets": self._clamp(p.smart_wallets * 25) if p.smart_wallets else None,
        }

    def run(self, p: Pair) -> Tuple[int, Dict[str, Optional[float]]]:
        self.scored += 1
        comps = self.components(p)
        avail = {k: v for k, v in comps.items() if v is not None}
        wsum = sum(self.WEIGHTS[k] for k in avail)
        score = sum(self.WEIGHTS[k] * v for k, v in avail.items()) / wsum if wsum else 0
        return int(round(score)), comps


# ---------------------------------------------------------------- EXECUTOR (paper)
class PaperExecutor:
    """Simulates fills with slippage + fees. NEVER touches a wallet."""

    def __init__(self, cfg: Config, ledger: Ledger):
        self.cfg, self.ledger = cfg, ledger

    def buy(self, p: Pair, balance: float, now: float) -> Optional[Position]:
        c = self.cfg
        size = balance * c.max_position_pct / 100
        if size < 1:
            return None
        fill = p.price * (1 + c.slippage_pct / 100)
        fee = size * c.fee_pct / 100
        qty = (size - fee) / fill
        stop = fill * (1 - c.stop_loss_pct / 100)  # stop is set BEFORE entry is recorded
        pos_id = self.ledger.open_position(p, fill, size, qty, stop, now)
        return Position(pos_id, p.symbol, p.mint, p.pair_address, fill, size, qty, stop, fill,
                        opened_at=now, last_price=fill)

    def sell(self, pos: Position, price: float, reason: str, now: float) -> float:
        c = self.cfg
        fill = price * (1 - c.slippage_pct / 100)
        gross = pos.qty * fill
        proceeds = gross * (1 - c.fee_pct / 100)
        pnl = proceeds - pos.size_usd
        self.ledger.close_position(pos.id, fill, proceeds, pnl, reason, now)
        return proceeds


# ---------------------------------------------------------------- RISK
class Risk:
    """Guards every open position: hard stop, trailing stop, max hold time, daily kill switch."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.stops = 0

    def check(self, pos: Position, price: float, now: float) -> Optional[str]:
        c = self.cfg
        pos.last_price = price
        if price > pos.peak_price:
            pos.peak_price = price
        gain = (pos.peak_price / pos.entry_price - 1) * 100
        if not pos.trailing and gain >= c.trail_activate_pct:
            pos.trailing = True
        if pos.trailing:
            pos.stop_price = max(pos.stop_price, pos.peak_price * (1 - c.trail_distance_pct / 100))
        if price <= pos.stop_price:
            self.stops += 1
            return "trail" if pos.trailing else "stop"
        if (now - pos.opened_at) / 60 >= c.max_hold_min:
            return "time"
        return None

    def can_open(self, balance: float, start: float, open_count: int) -> Tuple[bool, str]:
        if open_count >= self.cfg.max_open_positions:
            return False, "max open positions"
        if (1 - balance / start) * 100 >= self.cfg.daily_loss_limit_pct - 1e-9:  # tolerance: 80.00000000000001 must still trip
            return False, "daily loss limit hit — kill switch"
        return True, ""
