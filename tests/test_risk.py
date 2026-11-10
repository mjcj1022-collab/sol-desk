"""Risk rules: hard stop, trailing stop, max hold, position cap, kill switch."""
from soldesk.agents import Risk
from soldesk.models import Position


def pos(entry=1.0, cfg=None, opened_at=0.0):
    stop = entry * (1 - cfg.stop_loss_pct / 100)
    return Position(1, "T", "m", "p", entry, 10.0, 10.0, stop, entry, opened_at=opened_at, last_price=entry)


def test_hard_stop(cfg):
    r, p = Risk(cfg), pos(cfg=cfg)
    assert r.check(p, 0.97, now=60) is None              # -3%: hold
    assert r.check(p, 1 - cfg.stop_loss_pct / 100, now=120) == "stop"
    assert r.stops == 1


def test_trailing_activates_and_ratchets(cfg):
    r, p = Risk(cfg), pos(cfg=cfg)
    assert r.check(p, 1.05, now=60) is None
    assert not p.trailing
    assert r.check(p, 1 + cfg.trail_activate_pct / 100, now=120) is None
    assert p.trailing
    r.check(p, 1.30, now=180)
    expected = 1.30 * (1 - cfg.trail_distance_pct / 100)
    assert abs(p.stop_price - expected) < 1e-9
    r.check(p, 1.25, now=240)                             # pullback: stop never moves down
    assert abs(p.stop_price - expected) < 1e-9
    assert r.check(p, expected - 0.001, now=300) == "trail"


def test_trailing_locks_profit(cfg):
    r, p = Risk(cfg), pos(cfg=cfg)
    r.check(p, 1.20, now=60)
    assert p.stop_price > p.entry_price                   # a 20% winner can't turn into a loss


def test_max_hold(cfg):
    r, p = Risk(cfg), pos(cfg=cfg, opened_at=0)
    assert r.check(p, 1.01, now=(cfg.max_hold_min - 1) * 60) is None
    assert r.check(p, 1.01, now=cfg.max_hold_min * 60) == "time"


def test_stop_beats_time(cfg):
    r, p = Risk(cfg), pos(cfg=cfg, opened_at=0)
    assert r.check(p, 0.5, now=cfg.max_hold_min * 60) == "stop"


def test_max_open_positions(cfg):
    r = Risk(cfg)
    assert r.can_open(100, 100, cfg.max_open_positions - 1)[0]
    ok, why = r.can_open(100, 100, cfg.max_open_positions)
    assert not ok and "max open" in why


def test_kill_switch(cfg):
    r = Risk(cfg)
    start = 100.0
    just_above = start * (1 - (cfg.daily_loss_limit_pct - 0.5) / 100)
    at_limit = start * (1 - cfg.daily_loss_limit_pct / 100)
    assert r.can_open(just_above, start, 0)[0]
    ok, why = r.can_open(at_limit, start, 0)
    assert not ok and "kill switch" in why
