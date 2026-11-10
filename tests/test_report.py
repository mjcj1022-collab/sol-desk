import report


def trade(pnl, size=10.0, entry=1.015, exit_=1.0, reason="stop"):
    return {"pnl": pnl, "size_usd": size, "entry_price": entry, "exit_price": exit_, "reason": reason}


CFG = {"starting_balance": 100.0, "slippage_pct": 1.5, "fee_pct": 0.3}


def test_too_few_trades():
    r = report.analyse([trade(1.0)] * 5, CFG)
    assert r["verdict"].startswith("NOT ENOUGH DATA")


def test_clear_loser():
    r = report.analyse([trade(-0.6)] * 40, CFG)
    assert r["verdict"].startswith("LOSING")


def test_coin_flip_has_no_proven_edge():
    ts = [trade(0.5 if i % 2 else -0.5) for i in range(40)]
    assert report.analyse(ts, CFG)["verdict"].startswith("NO PROVEN EDGE")


def test_strong_edge_survives_stress():
    ts = [trade(4.0, entry=1.015, exit_=1.5, reason="trail")] * 30 + [trade(-0.8)] * 10
    r = report.analyse(ts, CFG)
    assert r["stress"][5.0] > 0
    assert r["verdict"].startswith("EDGE LOOKS REAL")


def test_reprice_identity_and_direction():
    # entry/exit logged at 1.5% slip; repricing at 1.5% must match the logged math
    t = {"size_usd": 10.0, "entry_price": 1.015, "exit_price": 1.2 * 0.985}
    same = report.reprice(t, 1.5, 1.5, 0.3)
    qty = 10.0 * 0.997 / 1.015
    assert abs(same - (qty * 1.2 * 0.985 * 0.997 - 10.0)) < 1e-9
    assert report.reprice(t, 1.5, 5.0, 0.3) < same


def test_drawdown():
    assert report.max_drawdown([10, -20, 5], 100) == (110 - 90) / 110 * 100


def test_reads_real_engine_db(cfg):
    from soldesk.engine import Engine
    from soldesk.market import MockMarket
    eng = Engine(cfg, market=MockMarket(seed=3, tick_s=cfg.tick_seconds), fast=True)
    eng.run(max_ticks=300)
    eng.ledger.db.close()
    trades, saved = report.load(cfg.db_path, None)
    text = report.render(report.analyse(trades, saved), "test")
    assert "sol-desk edge report" in text and saved["slippage_pct"] == cfg.slippage_pct
