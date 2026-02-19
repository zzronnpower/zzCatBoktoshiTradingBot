# PROJECT_LOG

Last updated: 2026-02-19 (owner-split positions update)
Project: `zzCatBoktoshiTradingBot`

## 1) Project Intent

Build a deployable ETHUSDT trading bot with:

- Automated strategy execution (long-only for current version)
- Strong risk controls
- Operator-friendly dashboard
- Manual override controls
- Persistent logs/history for traceability

## 2) High-Level Architecture

- Backend: FastAPI (`app/main.py`)
- Bot runner loop: `app/bot_runner.py`
- Storage: SQLite (`app/storage.py`)
- Exchange execution API: Boktoshi MTC (`app/mtc_client.py`)
- Market data:
  - Strategy candles: Hyperliquid (`app/hyperliquid_client.py`)
  - ETH chart tab market feed: ASTER (`app/aster_client.py`)
- Frontend pages:
  - Dashboard `/`
  - Manual control `/manual`
  - ETH chart `/eth-chart`
  - Chat log `/chatlog`

## 3) Trading Rules (Current)

- Pair: ETHUSDT only
- Side: LONG only
- Entry signal:
  - MA50 on 4H
  - Cross up + 3 consecutive closes above MA50
- Position config:
  - Margin: 100 BOKS
  - Leverage: x5
- Exit:
  - SL target: -1% of total capital
  - TP target: +3% of total capital

Important (latest):

- App now supports up to 2 ETH LONG positions at once by owner scope:
  - 1 strategy-owned position
  - 1 manual-owned position
- Manual and strategy positions are tracked by dedicated owner position IDs.

## 4) Runtime Safety Controls

- `DRY_RUN` mode supported (recommended before live)
- API retry/backoff in clients
- Internal trade rate guard (< 10 requests/min target)
- Max position checks and duplicate signal guard
- Strategy pause/resume state with logs

## 5) Implemented Features and Milestones

### M1 - Foundation and rename

- Renamed project from `mtc_bot` to `zzCatBoktoshiTradingBot`
- Updated build log and root references

### M2 - Core bot implementation

- Added robust MTC API client with error handling
- Implemented strategy + risk modules
- Extended DB schema for logs, trades, signals, equity snapshots, kv
- Added bot runner orchestration loop

### M3 - Dashboard improvements

- Reworked UI from raw JSON dump to readable operator dashboard
- Added KPI cards, tables, and log timeline
- Improved auto-refresh behavior (timeouts, anti-overlap, retry state)

### M4 - Manual control console

- Added `/manual` page
- Added force open LONG ETHUSDT
- Added close ETHUSDT position(s)
- Added strategy controls:
  - Pause Running Bot
  - Resume Bot
- Added explicit logs for pause/resume actions

### M5 - Chat history and planning docs

- Added chat log page `/chatlog`
- Added `Plan.html` and improved transcript tracking
- Chat log updated continuously with user/assistant milestones

### M6 - ETH Chart (ASTER-only)

- Added ASTER market data adapter (`app/aster_client.py`)
- Added API routes:
  - `/api/aster/overview`
  - `/api/aster/klines`
  - `/api/aster/depth`
- Added `/eth-chart` page with:
  - Candlestick + volume (Lightweight Charts)
  - Timeframe switching
  - Stats strip (mark/index/change/volume/OI/funding)
  - Orderbook and spread panel
- Added resilience for orderbook/depth instability:
  - Retry/fallback in ASTER client
  - UI-level status separation for chart/orderbook

### M7 - Dashboard position detail enhancement

- Added `StopLoss` column in Open Positions table on dashboard

### M8 - Owner-split dual position model

- Refactored position ownership model in `BotRunner`:
  - Strategy position ID stored separately
  - Manual position ID stored separately
- Strategy and manual can each hold one ETHUSDT LONG simultaneously.
- Strategy risk auto-close applies only to strategy-owned position.
- Manual close endpoint now closes only manual-owned position.
- Added dedicated endpoint for closing strategy-owned position manually.
- Dashboard and manual page now show strategy/manual positions separately.
- Added `TP Price` next to `StopLoss` in position tables.

## 6) Current Endpoints (Operational)

Core:

- `GET /api/status`
- `GET /api/account`
- `GET /api/open-positions`
- `GET /api/trade-history`
- `GET /api/pnl-history`
- `GET /api/signals`
- `GET /api/logs`

Manual controls:

- `POST /api/manual/force-open-long`
- `POST /api/manual/close-position`
- `POST /api/manual/close-strategy-position`
- `POST /api/bot/pause`
- `POST /api/bot/resume`

ASTER chart data:

- `GET /api/aster/overview`
- `GET /api/aster/klines`
- `GET /api/aster/depth`

Pages:

- `/`
- `/manual`
- `/eth-chart`
- `/chatlog`

## 7) Environment and Config

Main env keys used:

- `MTC_API_KEY`
- `MTC_BASE_URL`
- `ASTER_BASE_URL`
- `DB_PATH`
- `POLL_SECONDS`
- `DRY_RUN`
- `MARGIN_BOKS`
- `LEVERAGE`
- `SL_CAPITAL_PCT`
- `TP_CAPITAL_PCT`
- `MAX_POSITIONS`

## 8) Known Issues / Observations

- ASTER depth endpoint can intermittently return 502.
  - Mitigations already added: retries, fallback limit, UI tolerance.
- Chart is intentionally "inspired by" Hyperliquid, not a direct clone.
- API key was shared in chat earlier; rotation is recommended for security.

## 9) Suggested Next Steps

Priority upgrades:

1. Add MA50 overlay and entry/SL/TP markers directly on ETH chart.
2. Add websocket market stream for smoother orderbook/ticker updates.
3. Add tests for dual-owner position mapping/reconciliation.
4. Add tests for pause/resume and manual action flows.
5. Add daily archive of logs/equity snapshots.

## 10) Session Resume Instructions

When a new assistant session starts:

1. Read this file (`PROJECT_LOG.md`) fully.
2. Read `app/templates/chatlog.html` for conversation intent and constraints.
3. Validate runtime quickly:
   - `docker compose up --build -d`
   - check `/api/status`
   - visit `/manual` and `/eth-chart`
4. Continue from section "Suggested Next Steps" unless user gives new direction.
