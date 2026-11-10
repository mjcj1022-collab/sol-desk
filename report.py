"""Edge report: reads the trade log and says, honestly, whether the strategy has an edge.

  py report.py                 # all trades in soldesk.db
  py report.py --days 7        # last 7 days only
  py report.py --telegram      # also send the summary to your phone (uses .env)
  py report.py --db other.db   # a different database

It does not trust the headline P&L. It asks three questions:
  1. Are there enough trades to say anything?           (fewer than 30 = no)
  2. Is the average trade positive beyond luck?          (bootstrap 90% confidence interval)
  3. Does it survive worse fills?                        (re-prices every trade at 3% and 5% slippage)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import statistics
import sys
import time
import urllib.request
from typing import Dict, List, Optional

MIN_TRADES = 30


def load(db_path: str, days: Optional[float]) -> tuple[List[Dict], Dict]:
    if not os.path.exists(db_path):
        sys.exit(f"No database at {db_path}. Run the bot first.")
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    sql = "SELECT * FROM positions WHERE closed_at IS NOT NULL"
    args: tuple = ()
    if days:
        sql += " AND closed_at >= ?"
        args = (time.time() - days * 86400,)
    trades = [dict(r) for r in db.execute(sql + " ORDER BY closed_at", args)]
    row = db.execute("SELECT value FROM state WHERE key='config'").fetchone()
    cfg = json.loads(row[0]) if row else {}
    db.close()
    return trades, cfg


def reprice(t: Dict, slip_old: float, slip_new: float, fee: float) -> float:
    """P&L of the same trade if fills had been slip_new% worse on each side instead of slip_old%."""
    quote_in = t["entry_price"] / (1 + slip_old / 100)
    quote_out = t["exit_price"] / (1 - slip_old / 100)
    qty = t["size_usd"] * (1 - fee / 100) / (quote_in * (1 + slip_new / 100))
    proceeds = qty * quote_out * (1 - slip_new / 100) * (1 - fee / 100)
    return proceeds - t["size_usd"]


def max_drawdown(pnls: List[float], start: float) -> float:
    eq = peak = start
    worst = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        worst = max(worst, (peak - eq) / peak * 100 if peak else 0)
    return worst


def bootstrap_ci(xs: List[float], n: int = 4000, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(xs, k=len(xs))) for _ in range(n))
    return means[int(0.05 * n)], means[int(0.95 * n) - 1]


def analyse(trades: List[Dict], cfg: Dict) -> Dict:
    start = float(cfg.get("starting_balance", 120.0))
    slip = float(cfg.get("slippage_pct", 1.5))
    fee = float(cfg.get("fee_pct", 0.3))
    pnls = [t["pnl"] for t in trades]
    pcts = [t["pnl"] / t["size_usd"] * 100 for t in trades if t["size_usd"]]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    r: Dict = {
        "trades": len(trades), "start": start, "slippage": slip,
        "realized": sum(pnls),
        "return_pct": sum(pnls) / start * 100 if start else 0,
        "win_rate": len(wins) / len(pnls) * 100 if pnls else 0,
        "avg_win": statistics.fmean(wins) if wins else 0,
        "avg_loss": statistics.fmean(losses) if losses else 0,
        "profit_factor": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else float("inf") if wins else 0,
        "expectancy_pct": statistics.fmean(pcts) if pcts else 0,
        "max_dd_pct": max_drawdown(pnls, start),
        "exits": {},
        "stress": {},
        "ci": None,
    }
    for t in trades:
        r["exits"][t["reason"]] = r["exits"].get(t["reason"], 0) + 1
    if trades:
        for s in (3.0, 5.0):
            if s > slip:
                r["stress"][s] = sum(reprice(t, slip, s, fee) for t in trades)
    if len(pcts) >= 2:
        r["ci"] = bootstrap_ci(pcts)
    r["verdict"] = verdict(r)
    return r


def verdict(r: Dict) -> str:
    if r["trades"] < MIN_TRADES:
        return f"NOT ENOUGH DATA - {r['trades']} trades, need {MIN_TRADES}+. Keep it running."
    lo, hi = r["ci"]
    stress5 = r["stress"].get(5.0)
    if hi < 0:
        return "LOSING - the average trade is negative even on the optimistic end. No edge."
    if lo <= 0:
        return "NO PROVEN EDGE - results are within what luck alone could produce."
    if stress5 is not None and stress5 <= 0:
        return "FRAGILE EDGE - positive on paper, but gone at 5% slippage. Real fills will likely kill it."
    return "EDGE LOOKS REAL - positive beyond luck and survives 5% slippage. Still paper; keep watching drawdown."


def render(r: Dict, label: str) -> str:
    L = [f"sol-desk edge report ({label}) - PAPER",
         "-" * 44,
         f"trades        {r['trades']}"]
    if r["trades"]:
        pf = "inf" if r["profit_factor"] == float("inf") else f"{r['profit_factor']:.2f}"
        L += [
            f"realized      ${r['realized']:+.2f}  ({r['return_pct']:+.1f}% of ${r['start']:.0f})",
            f"win rate      {r['win_rate']:.0f}%   avg win ${r['avg_win']:+.2f} / avg loss ${r['avg_loss']:+.2f}",
            f"profit factor {pf}",
            f"avg trade     {r['expectancy_pct']:+.2f}% of position",
        ]
        if r["ci"]:
            L.append(f"  90% range   {r['ci'][0]:+.2f}% .. {r['ci'][1]:+.2f}%  (bootstrap)")
        L.append(f"max drawdown  {r['max_dd_pct']:.1f}%")
        L.append("exits         " + ", ".join(f"{k} {v}" for k, v in sorted(r["exits"].items())))
        for s, v in r["stress"].items():
            L.append(f"at {s:.0f}% slip   ${v:+.2f}   (logged at {r['slippage']:g}%)")
    L += ["-" * 44, r["verdict"]]
    return "\n".join(L)


def send_telegram(text: str) -> bool:
    from soldesk.config import load_dotenv
    load_dotenv()
    token, chat = os.getenv("SOLDESK_TG_TOKEN", ""), os.getenv("SOLDESK_TG_CHAT", "")
    if not (token and chat):
        print("Telegram not configured (.env SOLDESK_TG_TOKEN / SOLDESK_TG_CHAT) - skipped.")
        return False
    body = json.dumps({"chat_id": chat, "text": "📊 " + text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception as e:
        print("Telegram send failed:", e)
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=None, help="database path (default: SOLDESK_DB_PATH or soldesk.db)")
    ap.add_argument("--days", type=float, help="only trades closed in the last N days")
    ap.add_argument("--telegram", action="store_true", help="also send the report to Telegram")
    args = ap.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    db = args.db or os.getenv("SOLDESK_DB_PATH") or "soldesk.db"
    trades, cfg = load(db, args.days)
    label = f"last {args.days:g} days" if args.days else "all time"
    text = render(analyse(trades, cfg), label)
    print(text)
    if args.telegram:
        send_telegram(text)


if __name__ == "__main__":
    main()
