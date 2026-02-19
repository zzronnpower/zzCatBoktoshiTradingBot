# zzCatBoktoshiTradingBot

Trading bot for Boktoshi MechaTradeClub using Hyperliquid OHLC data.

## Strategy (v1)

- Pair: `ETHUSDT` only
- Timeframe: `4H`
- Entry: price crosses above `MA50` and the last 3 consecutive 4H candles close above MA50
- Side: `LONG` only (no short)
- Margin: `100 BOKS`
- Leverage: `5x`
- Risk:
  - Stop loss when unrealized PnL reaches `-1%` of total capital
  - Take profit when unrealized PnL reaches `+3%` of total capital

## Dashboard Data

- Account snapshot
- Open positions
- Trade history (local + remote)
- PnL history (equity curve)
- Signal diagnostics
- Logs
- ASTER Chart tab (ASTER-only market data)
- AsterTrading tab (ASTER futures manual trading)

## Quick Start (Docker)

1) Configure module env files:

- `BoktoshiBotModule/.env`
- `AsterTradingModule/.env`

2) Run:

```bash
docker compose up --build
```

Open: http://localhost:8000
ASTER Chart: http://localhost:8000/aster-chart

## Local Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API Endpoints

- `/api/status`
- `/api/account`
- `/api/open-positions`
- `/api/trade-history`
- `/api/pnl-history`
- `/api/signals`
- `/api/logs`
- `/api/aster/overview`
- `/api/aster/klines`
- `/api/aster/depth`
- `/api/aster/symbols`
- `/api/aster-trading/account-overview`
- `/api/aster-trading/order-preview`
- `/api/aster-trading/place-order`
- `/api/aster-trading/close-position`
- `/api/aster-trading/open-positions`
- `/api/aster-trading/open-orders`
- `/api/aster-trading/trade-history`
- `/api/aster-trading/pnl-history`

## Safety Notes

- Start with `DRY_RUN=true` to validate behavior.
- Set `DRY_RUN=false` only after reviewing logs/signals.
- Keep API keys only in `BoktoshiBotModule/.env` and `AsterTradingModule/.env`, never commit them.
- For ASTER manual trading, keep `ASTER_DRY_RUN=true` first and only switch to `false` when preview checks are stable.
