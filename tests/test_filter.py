"""The Filter must fail closed: any missing safety data or any broken rule kills the coin."""
import pytest

from soldesk.agents import Filter
from tests.conftest import make_pair


class StubMarket:
    def enrich(self, p):
        return p


@pytest.fixture
def flt(cfg):
    return Filter(cfg, StubMarket())


def test_clean_pair_passes(flt):
    ok, why = flt.run(make_pair())
    assert ok, why


@pytest.mark.parametrize("field", ["mint_revoked", "freeze_revoked", "lp_locked_pct",
                                   "top10_pct", "dev_pct", "bundled_pct"])
def test_missing_safety_data_fails_closed(flt, field):
    ok, why = flt.run(make_pair(**{field: None}))
    assert not ok
    assert "no data" in why


@pytest.mark.parametrize("over", [
    {"mint_revoked": False},
    {"freeze_revoked": False},
    {"lp_locked_pct": 50},
    {"liquidity": 10_000},
    {"vol_1h": 1_000},
    {"top10_pct": 60},
    {"dev_pct": 10},
    {"bundled_pct": 40},
    {"change_1h": 300},
])
def test_each_rule_kills(flt, over):
    ok, _ = flt.run(make_pair(**over))
    assert not ok


def test_kill_counter(flt):
    flt.run(make_pair(dev_pct=50))
    flt.run(make_pair(top10_pct=None))
    flt.run(make_pair())
    assert flt.killed == 2


def test_exactly_eight_rules(flt):
    assert len(flt.rules(make_pair())) == 8
