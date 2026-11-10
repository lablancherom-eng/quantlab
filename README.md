# QuantLab v2 — Live Paper Trading + Quant Research Portfolio

**Two separate, clearly identified environments:**

1. **LIVE PAPER** — real US equity IEX quotes and a REAL Alpaca paper-account balance/positions/orders, with an optional live-running **long-only SPY momentum strategy**. All broker executions are SIMULATED by Alpaca; no orders reach any real exchange.
2. **RESEARCH** — the existing fully disclosed synthetic pairs backtest, risk analytics and Black–Scholes pricing tools. Synthetic data must never be described as market or paper-trading performance.

> This software is educational, not financial advice. No live money integration is included. The site deliberately displays dashes (—) until genuine Alpaca PAPER credentials are configured on the server. No fake market prices, order records, or portfolio balances are inserted into the live dashboard.

## Quick start (Mac/Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`. Live dashboard: home page. API: `/api/live`. Documentation: `/docs`.

## Connect genuine paper trading data

1. Create a FREE **Alpaca Paper Only** account at https://app.alpaca.markets/ and generate **PAPER** API credentials. Do not use real-money brokerage keys.
2. Store these **on your server only**, using your hosting provider's protected environment-variable controls (never in JavaScript, the repository or screenshots):

| Variable | Value |
|---|---|
| `ALPACA_PAPER_KEY_ID` | Your paper account key ID |
| `ALPACA_PAPER_SECRET_KEY` | Your paper secret |
| `PAPER_AUTO_TRADE` | `false` at first; `true` only after reviewing the code and consciously opting in |

3. Restart the backend. With valid credentials, the dashboard automatically refreshes broker state and market quotes every 15 seconds. Each API read is cached for 10 seconds.
4. **Check `/api/live` and the UI before enabling any automated simulated orders.**

For a local test, export variables in your terminal session (do not paste credentials into any chat):

```bash
export ALPACA_PAPER_KEY_ID='YOUR_PAPER_KEY_ID'
export ALPACA_PAPER_SECRET_KEY='YOUR_PAPER_SECRET_KEY'
export PAPER_AUTO_TRADE='false'
uvicorn main:app --reload
```

### What “real time” actually means here

- The **real market data** come from Alpaca's free **IEX** feed (only one US exchange, **not the consolidated US market**). Quote timestamps show when the last trade was observed. When the US session is closed, the UI explicitly says so, and the last available prices are **not marked live**.
- The webpage **polls every 15 seconds**, and the optional server-side trading algorithm polls **every 60 seconds during the regular US session**. It is near-real-time, **not tick-by-tick/HFT**, and market-data rights and feed coverage vary by plan.
- The broker's paper account records are genuine API responses; orders are **simulations**, so real fills and market impact may differ. Paper fills do not establish live trading performance.
- The momentum model uses real minute price bars to calculate a 20-bar moving average. This recent history is needed to compute the signal; **no synthetic or old historical series are used for live trades**.
- The display includes quote timestamps to reveal stale data; the server refuses to place paper orders when its bar feed is stale.
- Displaying or redistributing licensed market data on a publicly accessible website may require extra provider permissions. Review Alpaca's terms before sharing the public dashboard with recruiters.

## Optional server-side algorithm (disabled by default)

The bot is a **long-only SPY 20-bar simple moving-average** teaching strategy, NOT the synthetic pair-trading research backtest.

- Detects a `LONG` signal when the latest IEX 1-minute close is >0.1% above the mean of the previous 20 bars, and `FLAT` when below by >0.1%; does nothing inside the deadband.
- Checks broker market clock, rejects stale/incomplete IEX bars, detects pending orders, and refuses blocked accounts.
- **Buy** at most **10% of current paper equity**, additionally capped at **$10,000** (whole shares, one SPY long position only). **Sell** no more shares than already held, never opens shorts and does not use derivatives.
- One submitted paper order per **hour** maximum (plus deterministic `client_order_id` for duplicate protection). Market order fill conditions are simulated by Alpaca.
- **No visitor-accessible POST /order endpoint**. All keys live server-side. There is no code path to the real-money trade host.
- Turn on using `PAPER_AUTO_TRADE=true` **only after you review and accept the simulated trading rules**; turn it off again to stop new paper decisions. Open positions remain open when you stop the bot—check the paper brokerage dashboard.

**Important:** for reliable continuous operation, deploy to a **single always-on instance**, NOT an idle-suspending free web service; free Render web services can sleep/restart, and a bot running in their web process cannot guarantee continual execution. Avoid multiple instances because duplicate workers could run. For robust long-term tracking, a separate worker with persistent logs and alerts is preferable. This is a research MVP, not a production trading platform.

## Deployment

Upload the folder contents to your own GitHub repository (never upload secrets), then in Render select **New > Web Service** and configure:

- Python runtime
- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Service instance: single instance only; continuous bot requires **always-on** hosting
- Server environment variables: `ALPACA_PAPER_KEY_ID`, `ALPACA_PAPER_SECRET_KEY`, `PAPER_AUTO_TRADE` (start `false`)

`render.yaml` contains the same basic deployment setup. A public URL only exists **after** deployment through your hosting account.

## Endpoints

- `/api/live`: read-only public view of authentic IEX market prices, Alpaca paper account, positions/orders, strategy status
- `/api/health`: integration and flag status (never returns secrets)
- `/api/backtest`: synthetic backtest; clearly disclosed
- `/api/options`: Black–Scholes theoretical pricing
- `/docs`: interactive API documentation

## Run tests

```bash
pip install pytest
pytest -q
```

## Code layout

```
main.py            FastAPI app, public read-only routes
live.py            Alpaca IEX data and PAPER ONLY broker adapter, private opt-in worker
engine.py          Synthetic backtester and Black–Scholes
site/index.html    Responsive UI including separate live dashboard
site/style.css     Styling
site/app.js        Charts, research forms, 15-second live display refresh
requirements.txt   App dependencies
render.yaml        Optional Render blueprint
tests/             Offline tests (no API credentials required)
```

## Limitations / disclosure

- Not a production-quality risk engine: no persistent audit log, standalone task queue, broker reconciliation beyond API state, portfolio-wide exposure controls, fill-aware rebalancing, or guaranteed exactly-once execution across redeploys.
- Model remains simplistic and unvalidated out-of-sample. There is no claim that the 20-bar momentum signal is profitable.
- Account `equity_history` is data returned from the broker, not synthetic research performance. When absent, the dashboard plots **nothing**.
- Server clock, feed entitlements, paper-market availability, and account restrictions may influence results. Alpaca Paper Only users can receive IEX data, but full SIP consolidated feeds require the appropriate data plan.
- This application does not interact with live traders, execute trades against other people, or connect to an exchange. It sends *paper* orders to the broker's simulated execution service.
