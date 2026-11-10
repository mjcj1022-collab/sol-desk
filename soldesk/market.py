"""Market data sources.

MockMarket      – offline simulation with realistic memecoin behaviour (rugs, pumps, slow bleeds).
                  Lets you test the whole pipeline with zero network and zero money.
LiveDataMarket  – real Solana pairs from DexScreener + safety data from RugCheck.
                  Still PAPER money: nothing is ever signed or sent on-chain.
"""
from __future__ import annotations

import random
import string
import time
from typing import Dict, List

from .models import Pair


class MarketSource:
    def discover(self) -> List[Pair]: ...
    def prices(self, pair_addresses: List[str]) -> Dict[str, float]: ...
    def enrich(self, pair: Pair) -> Pair: ...
    def close(self) -> None: ...


# ---------------------------------------------------------------------------------------------
# Mock market
# ---------------------------------------------------------------------------------------------
class _SimToken:
    FATES = [("rug", 0.30), ("bleed", 0.35), ("chop", 0.20), ("pump", 0.15)]

    def __init__(self, rng: random.Random, tick_s: float):
        self.rng = rng
        self.tick_s = tick_s
        self.symbol = "".join(rng.choice(string.ascii_uppercase) for _ in range(rng.randint(4, 6)))
        self.mint = "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(44))
        self.pair_address = "P" + self.mint[:43]
        r, acc = rng.random(), 0.0
        for fate, p in self.FATES:
            acc += p
            if r <= acc:
                self.fate = fate
                break
        self.age_min = rng.uniform(5, 80 * 60)
        self.price = rng.uniform(0.0002, 0.02)
        self.supply = rng.choice([1e9, 1e9, 1e8])
        self.liquidity = rng.uniform(15_000, 400_000)
        self.vol_1h = rng.uniform(5_000, 900_000)
        self.change_1h = rng.uniform(-40, 160)
        self.rugged = False
        self.ticks = 0
        self.prev_price = self.price
        bad = self.fate == "rug"
        # Rugs usually (not always!) leave fingerprints the filter can catch.
        self.mint_revoked = rng.random() > (0.35 if bad else 0.03)
        self.freeze_revoked = rng.random() > (0.30 if bad else 0.03)
        self.lp_locked_pct = rng.uniform(0, 60) if (bad and rng.random() < 0.5) else rng.uniform(85, 100)
        self.top10_pct = rng.uniform(20, 60) if bad else rng.uniform(8, 32)
        self.dev_pct = rng.uniform(0, 12) if bad else rng.uniform(0, 4)
        self.bundled_pct = rng.uniform(5, 40) if bad else rng.uniform(0, 14)
        self.holders = rng.randint(150, 9000)
        self.smart = rng.randint(0, 4) if self.fate == "pump" else rng.randint(0, 3)

    def step(self):
        self.ticks += 1
        self.age_min += self.tick_s / 60
        self.prev_price = self.price
        rng = self.rng
        if self.rugged:
            self.price *= rng.uniform(0.97, 1.0)
            return
        drift = {"rug": 0.005, "bleed": -0.005, "chop": -0.001, "pump": 0.006}[self.fate]
        vol = {"rug": 0.03, "bleed": 0.025, "chop": 0.035, "pump": 0.04}[self.fate]
        if self.fate == "rug" and rng.random() < 0.04:  # sudden pull
            self.rugged = True
            self.price *= rng.uniform(0.05, 0.25)
            self.liquidity *= 0.05
            return
        self.price *= max(0.5, 1 + rng.gauss(drift, vol))
        self.vol_1h = max(1000, self.vol_1h * rng.uniform(0.9, 1.12))
        self.holders += rng.randint(-5, 25 if self.fate == "pump" else 8)

    def to_pair(self) -> Pair:
        mcap = self.price * self.supply
        buys = int(self.vol_1h / self.rng.uniform(80, 400))
        # rugs fake buy pressure (wash/bundled buys) -> the ratio alone is NOT a tell
        ratio = {"pump": 1.3, "rug": 1.4, "chop": 1.15, "bleed": 1.0}[self.fate]
        sells = max(1, int(buys / (ratio * self.rng.uniform(0.75, 1.25))))
        return Pair(
            symbol=self.symbol, mint=self.mint, pair_address=self.pair_address, price=self.price,
            age_min=self.age_min, mcap=mcap, liquidity=self.liquidity, vol_1h=self.vol_1h,
            change_1h=self.change_1h, buys_1h=buys, sells_1h=sells,
            vol_5m=self.vol_1h / 12 * self.rng.uniform(0.6, 1.6),
            change_5m=(self.price / self.prev_price - 1) * 100 * 5,
            url=f"mock://{self.symbol}",
        )


class MockMarket(MarketSource):
    def __init__(self, seed: int | None = None, tick_s: float = 15.0):
        self.rng = random.Random(seed)
        self.tick_s = tick_s
        self.tokens: Dict[str, _SimToken] = {}

    def _advance(self):
        for t in self.tokens.values():
            t.step()
        for _ in range(self.rng.randint(1, 4)):  # new launches each tick
            t = _SimToken(self.rng, self.tick_s)
            self.tokens[t.pair_address] = t

    def discover(self) -> List[Pair]:
        self._advance()
        return [t.to_pair() for t in self.tokens.values() if t.ticks <= 1]

    def prices(self, pair_addresses: List[str]) -> Dict[str, float]:
        return {a: self.tokens[a].price for a in pair_addresses if a in self.tokens}

    def enrich(self, pair: Pair) -> Pair:
        t = self.tokens[pair.pair_address]
        pair.mint_revoked, pair.freeze_revoked = t.mint_revoked, t.freeze_revoked
        pair.lp_locked_pct, pair.top10_pct = t.lp_locked_pct, t.top10_pct
        pair.dev_pct, pair.bundled_pct = t.dev_pct, t.bundled_pct
        pair.holders = t.holders
        pair.holder_growth_pct = self.rng.uniform(0, 35) if t.fate in ("pump", "rug") else self.rng.uniform(-5, 25)
        pair.smart_wallets = t.smart
        return pair


# ---------------------------------------------------------------------------------------------
# Live data (DexScreener + RugCheck), paper money only
# ---------------------------------------------------------------------------------------------
class LiveDataMarket(MarketSource):
    DEX = "https://api.dexscreener.com"
    RUG = "https://api.rugcheck.xyz/v1"

    def __init__(self):
        import httpx  # imported lazily so mock mode needs no deps
        self.http = httpx.Client(timeout=15, headers={"User-Agent": "sol-desk/0.1"})
        self.seen: set[str] = set()

    def _get(self, url: str):
        r = self.http.get(url)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _to_pair(p: dict) -> Pair:
        now_ms = time.time() * 1000
        tx = (p.get("txns") or {}).get("h1") or {}
        vol = p.get("volume") or {}
        chg = p.get("priceChange") or {}
        return Pair(
            symbol=(p.get("baseToken") or {}).get("symbol", "?"),
            mint=(p.get("baseToken") or {}).get("address", ""),
            pair_address=p.get("pairAddress", ""),
            price=float(p.get("priceUsd") or 0),
            age_min=(now_ms - (p.get("pairCreatedAt") or now_ms)) / 60000,
            mcap=float(p.get("marketCap") or p.get("fdv") or 0),
            liquidity=float((p.get("liquidity") or {}).get("usd") or 0),
            vol_1h=float(vol.get("h1") or 0),
            vol_5m=float(vol.get("m5") or 0),
            change_1h=float(chg.get("h1") or 0),
            change_5m=float(chg.get("m5") or 0),
            buys_1h=int(tx.get("buys") or 0),
            sells_1h=int(tx.get("sells") or 0),
            url=p.get("url", ""),
        )

    def discover(self) -> List[Pair]:
        mints: list[str] = []
        for path in ("/token-profiles/latest/v1", "/token-boosts/latest/v1"):
            try:
                for item in self._get(self.DEX + path):
                    if item.get("chainId") == "solana" and item.get("tokenAddress") not in mints:
                        mints.append(item["tokenAddress"])
            except Exception:
                continue
        fresh = [m for m in mints if m not in self.seen][:30]
        self.seen.update(fresh)
        if not fresh:
            return []
        pairs = self._get(f"{self.DEX}/tokens/v1/solana/{','.join(fresh)}") or []
        best: Dict[str, dict] = {}
        for p in pairs:
            m = (p.get("baseToken") or {}).get("address")
            liq = float((p.get("liquidity") or {}).get("usd") or 0)
            if m and (m not in best or liq > float((best[m].get("liquidity") or {}).get("usd") or 0)):
                best[m] = p
        return [self._to_pair(p) for p in best.values()]

    def prices(self, pair_addresses: List[str]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for i in range(0, len(pair_addresses), 30):
            chunk = pair_addresses[i:i + 30]
            data = self._get(f"{self.DEX}/latest/dex/pairs/solana/{','.join(chunk)}")
            for p in data.get("pairs") or []:
                out[p["pairAddress"]] = float(p.get("priceUsd") or 0)
        return out

    def enrich(self, pair: Pair) -> Pair:
        """Fill safety fields from RugCheck. Anything we can't read stays None -> Filter fails closed."""
        try:
            rep = self._get(f"{self.RUG}/tokens/{pair.mint}/report")
        except Exception:
            return pair
        pair.mint_revoked = rep.get("mintAuthority") in (None, "")
        pair.freeze_revoked = rep.get("freezeAuthority") in (None, "")
        holders = rep.get("topHolders") or []
        if holders:
            pair.top10_pct = sum(float(h.get("pct") or 0) for h in holders[:10])
        markets = rep.get("markets") or []
        locked = [float((m.get("lp") or {}).get("lpLockedPct") or 0) for m in markets]
        if locked:
            pair.lp_locked_pct = max(locked)
        supply = float((rep.get("token") or {}).get("supply") or 0)
        creator_bal = rep.get("creatorBalance")
        if creator_bal is not None and supply:
            pair.dev_pct = float(creator_bal) / supply * 100
        insiders = [h for h in holders if h.get("insider")]
        if holders:
            pair.bundled_pct = sum(float(h.get("pct") or 0) for h in insiders)
        pair.holders = rep.get("totalHolders")
        return pair

    def close(self) -> None:
        self.http.close()
