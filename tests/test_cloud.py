"""Cloud-readiness: restarts resume state, the exposed dashboard is password-protected, weekly report fires."""
import base64
import socket
import urllib.error
import urllib.request

import pytest

from soldesk.dashboard import serve
from soldesk.engine import Engine
from soldesk.market import MockMarket


def run(cfg, seed, ticks):
    eng = Engine(cfg, market=MockMarket(seed=seed, tick_s=cfg.tick_seconds), fast=True)
    for _ in range(ticks):
        eng.tick()
        eng.clock += cfg.tick_seconds
    return eng


def test_restart_resumes_cash_and_positions(cfg):
    a = run(cfg, seed=4, ticks=400)
    assert a.ledger.all_closed(), "need some trades for this test"
    cash, open_ids = a.cash, set(a.positions)
    a.ledger.db.close()
    b = Engine(cfg, market=MockMarket(seed=99, tick_s=cfg.tick_seconds), fast=True)
    assert abs(b.cash - cash) < 1e-6
    assert set(b.positions) == open_ids
    for p in b.positions.values():
        assert p.stop_price > 0
    b.ledger.db.close()


def test_fresh_db_starts_at_starting_balance(cfg):
    e = Engine(cfg, market=MockMarket(seed=1), fast=True)
    assert e.cash == cfg.starting_balance and not e.positions
    e.ledger.db.close()


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_public_dashboard_requires_password(cfg):
    with pytest.raises(SystemExit):
        serve(cfg.db_path, _free_port(), host="0.0.0.0", password="")


def test_dashboard_basic_auth(cfg):
    port = _free_port()
    srv = serve(cfg.db_path, port, host="127.0.0.1", password="hunter2")
    base = f"http://127.0.0.1:{port}"
    try:
        assert urllib.request.urlopen(base + "/healthz").read() == b"ok"
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/api/state")
        assert e.value.code == 401
        for pw, ok in (("wrong", False), ("hunter2", True)):
            req = urllib.request.Request(base + "/api/state", headers={
                "Authorization": "Basic " + base64.b64encode(f"me:{pw}".encode()).decode()})
            if ok:
                assert urllib.request.urlopen(req).status == 200
            else:
                with pytest.raises(urllib.error.HTTPError):
                    urllib.request.urlopen(req)
    finally:
        srv.shutdown()


def test_weekly_report_schedule(cfg, monkeypatch):
    sent = []
    monkeypatch.setattr("soldesk.report.send_telegram", lambda text: sent.append(text) or True)
    e = Engine(cfg, market=MockMarket(seed=1), fast=False)
    e.notifier.enabled = True
    e._maybe_weekly_report()                       # first call only arms the timer
    assert not sent
    e._maybe_weekly_report()
    assert not sent                                # not a week yet
    e.ledger.set("last_report_ts", e.ledger.get("last_report_ts") - 8 * 86400)
    e._maybe_weekly_report()
    assert len(sent) == 1 and "edge report" in sent[0]
    e.ledger.db.close()
