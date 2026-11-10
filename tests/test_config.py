from soldesk.config import Config


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)          # no .env here
    monkeypatch.setenv("SOLDESK_STOP_LOSS_PCT", "4.5")
    monkeypatch.setenv("SOLDESK_MAX_OPEN_POSITIONS", "2")
    c = Config.from_env()
    assert c.stop_loss_pct == 4.5 and c.max_open_positions == 2


def test_safe_defaults():
    c = Config()
    assert c.stop_loss_pct > 0 and c.max_position_pct <= 10
    assert c.slippage_pct > 0 and c.fee_pct > 0
    assert c.max_open_positions >= 1 and c.daily_loss_limit_pct <= 25
