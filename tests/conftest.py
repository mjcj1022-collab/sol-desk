import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from soldesk.config import Config  # noqa: E402
from soldesk.models import Pair  # noqa: E402


@pytest.fixture(autouse=True)
def no_telegram(monkeypatch):
    """Tests must never send a real Telegram alert, even if a .env is present."""
    for k in ("SOLDESK_TG_TOKEN", "SOLDESK_TG_CHAT", "SOLDESK_TG_EVENTS"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def cfg(tmp_path):
    c = Config()  # defaults only; ignores any local .env
    c.db_path = str(tmp_path / "test.db")
    return c


def make_pair(**over):
    """A pair that passes every filter rule and scores well, unless overridden."""
    base = dict(
        symbol="GOOD", mint="mint1", pair_address="pair1", price=1.0,
        age_min=120, mcap=1_000_000, liquidity=150_000, vol_1h=200_000,
        change_1h=20, buys_1h=600, sells_1h=200, change_5m=5,
        mint_revoked=True, freeze_revoked=True, lp_locked_pct=100,
        top10_pct=15, dev_pct=1, bundled_pct=2, holders=900,
        holder_growth_pct=30, smart_wallets=3,
    )
    base.update(over)
    return Pair(**base)
