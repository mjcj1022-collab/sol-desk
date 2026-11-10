"""All tunable knobs in one place. Override any of them via environment variables or .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default, cast=float):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    if cast is bool:
        return raw.lower() in ("1", "true", "yes", "on")
    return cast(raw)


def load_dotenv(path: str = ".env") -> None:
    """Tiny .env loader so we don't need python-dotenv."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.split(" #", 1)[0].split("\t#", 1)[0]   # drop inline comments
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass
class Config:
    # --- mode ---
    mode: str = "mock"                  # "mock" (offline simulated market) or "live-data" (real DexScreener prices, paper money)
    starting_balance: float = 120.0
    tick_seconds: float = 15.0          # how often the loop runs
    db_path: str = "soldesk.db"
    dashboard_port: int = 8787
    dashboard_host: str = "127.0.0.1"   # cloud: 0.0.0.0 (then SOLDESK_DASH_PASSWORD is required)
    dash_password: str = ""
    weekly_report: bool = True          # send the edge report to Telegram every 7 days while running

    # --- scout ---
    min_age_min: float = 30.0
    max_age_hr: float = 72.0
    min_mcap: float = 300_000
    max_mcap: float = 20_000_000

    # --- filter (8 hard rules; one fail = killed) ---
    min_liquidity: float = 40_000
    min_vol_1h: float = 50_000
    max_top10_pct: float = 25.0
    max_dev_pct: float = 3.0
    max_bundled_pct: float = 10.0
    max_pump_1h_pct: float = 80.0
    min_lp_locked_pct: float = 90.0

    # --- analyst ---
    min_score: int = 70

    # --- executor / risk ---
    max_position_pct: float = 8.0       # % of balance per trade
    max_open_positions: int = 3
    stop_loss_pct: float = 6.0
    trail_activate_pct: float = 12.0
    trail_distance_pct: float = 5.0
    max_hold_min: float = 90.0
    slippage_pct: float = 1.5           # applied on entry AND exit
    fee_pct: float = 0.3                # swap/priority fees per side
    daily_loss_limit_pct: float = 20.0  # kill switch: stop opening trades past this drawdown

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        c = cls()
        for f in c.__dataclass_fields__.values():
            cast = type(getattr(c, f.name))
            setattr(c, f.name, _env("SOLDESK_" + f.name.upper(), getattr(c, f.name), cast))
        return c
