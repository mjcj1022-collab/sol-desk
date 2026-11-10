"""End-to-end on the offline mock market: invariants that must hold on every run."""
import pytest

from soldesk.engine import Engine
from soldesk.market import MockMarket


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_mock_run_invariants(cfg, seed):
    eng = Engine(cfg, market=MockMarket(seed=seed, tick_s=cfg.tick_seconds), fast=True)
    max_seen = 0
    for _ in range(300):
        eng.tick()
        eng.clock += cfg.tick_seconds
        max_seen = max(max_seen, len(eng.positions))
        assert eng.cash >= -1e-9, "cash went negative"
        for p in eng.positions.values():
            assert p.size_usd <= cfg.starting_balance * cfg.max_position_pct / 100 * 1.5
            assert p.stop_price > 0
    assert max_seen <= cfg.max_open_positions
    errors = [r for r in eng.ledger.db.execute("SELECT detail FROM events WHERE kind='ERROR'")]
    assert not errors, [dict(r) for r in errors]
    for t in eng.ledger.all_closed():
        assert t["reason"] in {"stop", "trail", "time"}
    eng.ledger.db.close()


def test_no_new_entries_after_kill_switch(cfg):
    eng = Engine(cfg, market=MockMarket(seed=7, tick_s=cfg.tick_seconds), fast=True)
    eng.cash = cfg.starting_balance * (1 - cfg.daily_loss_limit_pct / 100) - 1
    before = len(eng.ledger.all_closed()) + len(eng.positions)
    for _ in range(100):
        eng.tick()
        eng.clock += cfg.tick_seconds
    assert len(eng.positions) == 0
    enters = eng.ledger.db.execute("SELECT COUNT(*) FROM events WHERE kind='ENTER'").fetchone()[0]
    assert enters == 0 and before == 0
    eng.ledger.db.close()


def test_never_imports_wallet_code():
    """Paper only: nothing in the package should touch signing / wallet libraries."""
    import pathlib
    src = " ".join(p.read_text(encoding="utf-8") for p in pathlib.Path("soldesk").glob("*.py"))
    for banned in ("solders", "solana.rpc", "Keypair", "private_key", "sign_transaction"):
        assert banned not in src, banned
