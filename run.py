"""sol-desk - six-agent Solana memecoin PAPER trader.

Examples
  python run.py                          # mock market, real-time, dashboard on :8787
  python run.py --fast --ticks 400       # mock market, simulated clock (~100 min of market in seconds)
  python run.py --mode live-data         # real DexScreener + RugCheck data, still paper money
  python run.py --backtest 200           # 200 independent mock nights -> honest distribution of outcomes
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time

from soldesk.config import Config
from soldesk.engine import Engine


def backtest(cfg: Config, nights: int, ticks: int) -> None:
    results = []
    for i in range(nights):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cfg.db_path = path
        from soldesk.market import MockMarket
        eng = Engine(cfg, market=MockMarket(seed=i, tick_s=cfg.tick_seconds), fast=True)
        eng.run(max_ticks=ticks)
        # close anything still open at the last price so equity is honest
        eq = eng.equity()
        trades = len(eng.ledger.all_closed())
        results.append((eq / cfg.starting_balance - 1) * 100)
        eng.ledger.db.close()
        os.remove(path)
        sys.stdout.write(f"\r  night {i + 1}/{nights}  last: {results[-1]:+.1f}%  trades: {trades}   ")
        sys.stdout.flush()
    results.sort()
    q = lambda p: results[min(len(results) - 1, int(p * len(results)))]
    print("\n\nBacktest over", nights, "simulated nights (", ticks, "ticks each )")
    print(f"  median  {statistics.median(results):+.1f}%")
    print(f"  mean    {statistics.mean(results):+.1f}%")
    print(f"  worst   {results[0]:+.1f}%   p10 {q(0.10):+.1f}%   p90 {q(0.90):+.1f}%   best {results[-1]:+.1f}%")
    print(f"  nights that made money: {sum(r > 0 for r in results)}/{nights}")
    print("\n  NOTE: the mock market is a toy. Use it to test the plumbing, not to predict returns.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["mock", "live-data"])
    ap.add_argument("--fast", action="store_true", help="mock only: simulated clock, no sleeping")
    ap.add_argument("--ticks", type=int, help="stop after N ticks")
    ap.add_argument("--no-dashboard", action="store_true")
    ap.add_argument("--fresh", action="store_true", help="delete the existing database first")
    ap.add_argument("--backtest", type=int, metavar="NIGHTS")
    args = ap.parse_args()

    cfg = Config.from_env()
    if args.mode:
        cfg.mode = args.mode

    if args.backtest:
        backtest(cfg, args.backtest, args.ticks or 400)
        return

    if args.fast and cfg.mode != "mock":
        sys.exit("--fast only works with the mock market")
    if args.fresh and os.path.exists(cfg.db_path):
        os.remove(cfg.db_path)

    print("=" * 62)
    print("  sol-desk  |  PAPER TRADING ONLY - no wallet, no real money")
    print(f"  mode={cfg.mode}  balance=${cfg.starting_balance:.2f}  tick={cfg.tick_seconds}s")
    print("=" * 62)

    if not args.no_dashboard:
        from soldesk.dashboard import serve
        serve(cfg.db_path, cfg.dashboard_port)
        print(f"  dashboard -> http://127.0.0.1:{cfg.dashboard_port}")

    eng = Engine(cfg, fast=args.fast)
    t0 = time.time()
    eng.run(max_ticks=args.ticks)
    s = eng.ledger.snapshot()["stats"]
    print(f"\nDone in {time.time() - t0:.1f}s  ticks={eng.ticks}")
    print(f"  equity ${eng.equity():.2f}  ({(eng.equity() / cfg.starting_balance - 1) * 100:+.1f}%)")
    print(f"  trades {s['trades']}  W {s['wins']} / L {s['losses']}  best {s['best']:+.2f}  worst {s['worst']:+.2f}")
    print(f"  scout saw {eng.scout.seen}, filter killed {eng.filter.killed}, analyst scored {eng.analyst.scored}")
    if not args.no_dashboard and args.ticks:
        print(f"  dashboard still up at http://127.0.0.1:{cfg.dashboard_port} - Ctrl+C to quit")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
