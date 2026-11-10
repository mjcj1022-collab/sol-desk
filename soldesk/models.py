from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Pair:
    """A token pair as seen by the Scout. Safety fields are filled in by the Filter's data lookup."""
    symbol: str
    mint: str
    pair_address: str
    price: float
    age_min: float
    mcap: float
    liquidity: float
    vol_1h: float
    change_1h: float
    buys_1h: int
    sells_1h: int
    url: str = ""
    # momentum history (filled across ticks)
    vol_5m: float = 0.0
    change_5m: float = 0.0
    # safety data (from RugCheck in live-data mode, simulated in mock mode)
    mint_revoked: Optional[bool] = None
    freeze_revoked: Optional[bool] = None
    lp_locked_pct: Optional[float] = None
    top10_pct: Optional[float] = None
    dev_pct: Optional[float] = None
    bundled_pct: Optional[float] = None
    holders: Optional[int] = None
    holder_growth_pct: Optional[float] = None
    smart_wallets: int = 0


@dataclass
class Position:
    id: int
    symbol: str
    mint: str
    pair_address: str
    entry_price: float
    size_usd: float
    qty: float
    stop_price: float
    peak_price: float
    opened_at: float = field(default_factory=time.time)
    trailing: bool = False
    last_price: float = 0.0

    @property
    def pnl_pct(self) -> float:
        return (self.last_price / self.entry_price - 1) * 100 if self.entry_price else 0.0
