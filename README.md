# sol-desk

A six-agent Solana memecoin trader that runs on **paper money only**. Nothing in this repo connects a wallet or signs a transaction.

```
SCOUT ──► FILTER ──► ANALYST ──► EXECUTOR ──► RISK ──► LOGGER
new pairs  8 hard     score      paper fill    stop -6%   SQLite +
30m–72h    rules,     0–100,     w/ slippage   trail +12% dashboard
$300k–20M  fail-closed  ≥70 only   + fees        90m max
```

## Run it (Windows PowerShell)

```powershell
cd sol-desk
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

py run.py --fast --ticks 400 --fresh     # offline mock market, results in ~2s, dashboard stays up
py run.py --mode live-data --fresh       # REAL DexScreener + RugCheck data, paper money
py run.py --backtest 200                 # 200 simulated nights -> distribution of outcomes
```

Open **http://127.0.0.1:8787** for the dashboard. On macOS or Linux, use `python3` instead of `py`.

## Modes

| mode | prices | safety data | money |
|---|---|---|---|
| `mock` | simulated (rugs, pumps, bleeds) | simulated | paper |
| `live-data` | DexScreener (free, no key) | RugCheck (free, no key) | paper |

In `live-data` mode the filter **fails closed**. If RugCheck can't confirm a rule (for example mint authority or LP lock), the coin is killed.

## Telegram alerts

Get a ping on your phone for every entry, win, loss, kill switch and error:

1. In Telegram, message **@BotFather** → `/newbot` → copy the token.
2. Message your new bot once, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy the `chat.id`.
3. Put both in `.env` as `SOLDESK_TG_TOKEN` and `SOLDESK_TG_CHAT`.

If those two aren't set, alerts are off. An alert that fails to send never stops trading.

## Run it in the cloud (Render)

`render.yaml` deploys the bot as an always-on service so it doesn't depend on your PC. The trade log lives on a
persistent disk, and a restart or redeploy resumes where it left off: same cash, same open positions with their stops.

- Cost: Starter plan (~$7/mo) + 1 GB disk. The free plan sleeps when idle, which would stop the bot.
- Dashboard: the service URL, behind a password (any username). Render generates `SOLDESK_DASH_PASSWORD`; see it under Environment.
- Telegram: paste `SOLDESK_TG_TOKEN` and `SOLDESK_TG_CHAT` when Render asks.
- Weekly report: sent to Telegram every 7 days automatically (`SOLDESK_WEEKLY_REPORT=false` to turn off).

Only run one copy at a time (PC *or* cloud), or you'll get two sets of alerts.

## Edge report

Once the bot has been running a while, check whether it actually has an edge:

```
py report.py              # all trades
py report.py --days 7     # last week
py report.py --telegram   # also send it to your phone
```

It reports trades, win rate, profit factor, average trade, max drawdown, a bootstrap 90% range on the
average trade, and what the same trades would have made at 3% and 5% slippage. The verdict line is one of
NOT ENOUGH DATA (<30 trades), LOSING, NO PROVEN EDGE, FRAGILE EDGE (dies at 5% slippage) or EDGE LOOKS REAL.

## Tuning

Copy `.env.example` to `.env`. Every knob lives in `soldesk/config.py` and can be overridden as `SOLDESK_<NAME>`.

## Files

- `soldesk/market.py`: `MockMarket` and `LiveDataMarket` (DexScreener + RugCheck)
- `soldesk/agents.py`: Scout, Filter, Analyst, PaperExecutor, Risk
- `soldesk/engine.py`: the loop and handoffs
- `soldesk/ledger.py`: Logger (SQLite)
- `soldesk/notify.py`: Telegram alerts
- `soldesk/dashboard.py` + `static/index.html`: local dashboard
- `run.py`: CLI

## Before you ever consider real money

1. Run `live-data` for **2–4 weeks**. Judge it on the number of trades and the worst drawdown, not on the best night.
2. Paper fills are optimistic. Real Jupiter fills on thin pools are worse, and MEV bots will front-run you. Raise `SLIPPAGE_PCT` to 3–5 and check whether you're still profitable.
3. Mock-mode results mean nothing about real returns. That mode only exists to test the plumbing.
4. A real executor (Jupiter swap API + a burner wallet holding only what you can lose) is deliberately **not** included.

Not financial advice.
