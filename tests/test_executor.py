"""Paper fills must always be worse than the quoted price, and the stop must exist at entry."""
from soldesk.agents import PaperExecutor
from soldesk.ledger import Ledger
from tests.conftest import make_pair


def test_buy_applies_slippage_fee_and_stop(cfg):
    ex = PaperExecutor(cfg, Ledger(cfg.db_path))
    p = make_pair(price=2.0)
    pos = ex.buy(p, balance=100.0, now=0)
    assert pos.size_usd == 100.0 * cfg.max_position_pct / 100
    assert pos.entry_price > p.price                       # paid above quote
    assert pos.qty * pos.entry_price < pos.size_usd        # fee taken
    assert abs(pos.stop_price - pos.entry_price * (1 - cfg.stop_loss_pct / 100)) < 1e-12


def test_position_size_cap(cfg):
    ex = PaperExecutor(cfg, Ledger(cfg.db_path))
    pos = ex.buy(make_pair(), balance=1000.0, now=0)
    assert pos.size_usd <= 1000.0 * cfg.max_position_pct / 100 + 1e-9


def test_tiny_balance_refuses(cfg):
    ex = PaperExecutor(cfg, Ledger(cfg.db_path))
    assert ex.buy(make_pair(), balance=5.0, now=0) is None


def test_round_trip_at_same_price_loses_money(cfg):
    """With slippage + fees on both sides, a flat trade must be a loss. Guards against optimistic fills."""
    ledger = Ledger(cfg.db_path)
    ex = PaperExecutor(cfg, ledger)
    p = make_pair(price=1.0)
    pos = ex.buy(p, balance=100.0, now=0)
    proceeds = ex.sell(pos, price=1.0, reason="test", now=60)
    assert proceeds < pos.size_usd
    closed = ledger.all_closed()
    assert len(closed) == 1 and closed[0]["pnl"] < 0 and closed[0]["reason"] == "test"
