from soldesk.agents import Analyst, Scout
from tests.conftest import make_pair


def test_score_range_and_threshold(cfg):
    a = Analyst(cfg)
    good, _ = a.run(make_pair())
    bad, _ = a.run(make_pair(buys_1h=50, sells_1h=400, change_5m=-10, holder_growth_pct=0,
                             smart_wallets=0, liquidity=20_000))
    assert 0 <= bad < cfg.min_score <= good <= 100


def test_weights_sum_to_one():
    assert abs(sum(Analyst.WEIGHTS.values()) - 1.0) < 1e-9


def test_scout_window(cfg):
    class M:
        def discover(self):
            return [make_pair(symbol="OK"),
                    make_pair(symbol="YOUNG", age_min=5),
                    make_pair(symbol="OLD", age_min=cfg.max_age_hr * 60 + 1),
                    make_pair(symbol="SMALL", mcap=10_000),
                    make_pair(symbol="BIG", mcap=50_000_000)]
    assert [p.symbol for p in Scout(cfg, M()).run()] == ["OK"]
