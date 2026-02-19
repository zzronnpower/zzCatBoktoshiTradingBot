# PROJECT_LOG

Last updated: 2026-02-19 (manual open positions coin column)
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
- Bot runner loop: `BoktoshiBotModule/bot_runner.py` (compat shim at `app/bot_runner.py`)
- Storage: SQLite (`app/storage.py`)
- Exchange execution API (Boktoshi): `BoktoshiBotModule/mtc_client.py`
- Exchange execution API (ASTER futures manual): `AsterTradingModule/client.py`, `AsterTradingModule/service.py`
- Market data:
  - Strategy candles: Hyperliquid (`BoktoshiBotModule/hyperliquid_client.py`)
  - ASTER chart market feed: ASTER (`app/aster_client.py`)
- Frontend pages:
  - Dashboard `/`
  - Manual control `/manual`
  - ASTER chart `/aster-chart` (alias: `/eth-chart`)
  - ASTER trading `/aster-trading`
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
- AsterTrading is isolated from Boktoshi flow and only uses USDT futures on ASTER.
- Strategy engine remains ETHUSDT-only.
- Manual panel now supports whitelist symbols with up to 3 manual positions.

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

### M9 - AsterTrading module (independent, with DRY_RUN)

- Added standalone `AsterTradingModule` service layer for ETHUSDT futures execution.
- Added dedicated tab/page `/aster-trading` with:
  - Account overview block (equity + margin)
  - Trading panel (Market / Limit / Stop Limit)
  - Editable pre-order risk parameters with defaults:
    - leverage 5x
    - notional 400 USDT
    - margin ~80 USDT
    - SL 5%
    - risk ~20 USDT
  - Explicit DRY_RUN selector per order request
- Added ASTER trading APIs:
  - `GET /api/aster-trading/account-overview`
  - `POST /api/aster-trading/order-preview`
  - `POST /api/aster-trading/place-order`
  - `POST /api/aster-trading/close-position`
  - `GET /api/aster-trading/open-positions`
  - `GET /api/aster-trading/open-orders`
  - `GET /api/aster-trading/trade-history`
  - `GET /api/aster-trading/pnl-history`
- Moved Boktoshi core modules into `BoktoshiBotModule/` and kept compatibility shims under `app/`.
- Updated Dockerfile to include `BoktoshiBotModule/` and `AsterTradingModule/`.

### M10 - Separate module env files

- Added `BoktoshiBotModule/.env` for Boktoshi strategy/runtime variables.
- Added `AsterTradingModule/.env` for ASTER futures trading variables and API credentials.
- Updated `docker-compose.yml` to load both env files via `env_file`.
- Updated README quick start and safety notes to use module-scoped env files.

### M11 - BotStatus pause/resume sync fix

- Fixed Boktoshi status state in `BoktoshiBotModule/bot_runner.py` so `bot_status` mirrors strategy pause/resume state.
- `bot_status` now writes `paused` when strategy is paused and `running` when resumed.
- Updated immediate writes inside pause/resume handlers to remove UI lag between action and next loop tick.

### M12 - Module env loader fallback

- Added startup env-file fallback loader in `app/main.py`:
  - reads `BoktoshiBotModule/.env`
  - reads `AsterTradingModule/.env`
  - only sets variables that are not already present in process env.
- This prevents `MTC_API_KEY is missing` when runtime does not inject module env files as expected.
- Updated `.gitignore` to ignore module env files:
  - `BoktoshiBotModule/.env`
  - `AsterTradingModule/.env`

### M13 - Dashboard bot status source fix

- Fixed Dashboard "Account Overview -> Bot status" value in `app/templates/index.html`.
- The field now reflects local strategy state (`running` / `paused`) from `/api/status`.
- Added a separate row `Exchange bot status` to preserve remote account status (`active`, etc.) from API account payload.

### M14 - Manual settings editor for strategy/manual trade config

- Added editable settings block on `/manual` for:
  - Size (BOKS)
  - Leverage (x)
  - Stoploss (%)
  - Take Profit (%)
- Added APIs:
  - `GET /api/bot/settings` (returns current runtime values)
  - `POST /api/bot/settings` (saves and applies new values)
- Inputs now auto-load current values on page load and periodic refresh (no empty fields).
- Settings are applied live in `BotRunner`, persisted to KV (`cfg_*` keys), and reloaded on startup.

### M15 - Position tables: add Margin + Size columns

- Updated Open Positions tables in both Dashboard and Manual pages.
- Added columns:
  - `Margin`: capital in use for position
  - `Size`: total exposure (`margin * leverage`)
- Added robust frontend fallback calculation when API position payload lacks direct `margin`/`size` fields.
- Renamed Bot Settings label from `Size (BOKS)` to `Margin (BOKS)` for consistent terminology.
- Removed redundant `Exchange bot status` row from Dashboard Account Overview.

### M16 - ASTER Chart rename + USDT symbol dropdown

- Renamed chart tab label from `ETH Chart` to `ASTER Chart` across navigation.
- Added route alias `/aster-chart` while keeping `/eth-chart` for backward compatibility.
- Added ASTER symbols endpoint:
  - `GET /api/aster/symbols` (USDT pairs only, status=TRADING)
- Updated chart page to support:
  - symbol search + dropdown list (USDT pairs only)
  - dynamic reload of overview, candles, and orderbook by selected symbol
  - persisted symbol selection using `localStorage`

### M17 - ASTER symbol dropdown UX refinement

- Fixed dropdown visual style in chart page to match dark theme (`select` + `option` colors).
- Updated `/api/aster/symbols` ordering:
  - top 10 USDT symbols ranked by 24h `quoteVolume` descending first
  - remaining symbols sorted alphabetically after top 10

### M18 - ASTER OI/Funding display stability

- Removed countdown text rewrite in `ASTER Chart` OI/Funding tile to prevent line jumping.
- OI/Funding now shows stable value format: `Open Interest / FundingRate%`.
- Added `white-space: nowrap` on OI/Funding value for consistent single-line display.

### M19 - Manual multi-pair panel and close-by-position flow

- Updated Manual page `Force Open` card to `Manual Trade Panel`.
- Added manual symbol dropdown for LONG open (whitelist):
  - `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `XRPUSDT`, `HYPEUSDT`, `PUMPUSDT`, `DOGEUSDT`
- Added config preview text in Manual panel that auto-reflects current Bot Settings (Margin/Leverage/SL/TP).
- Renamed open button to `OPEN Manual LONG Position`.
- Manual ownership model changed from single position id to multi-id list (max 3 manual positions).
- Added close-by-position behavior:
  - Manual page now provides a dropdown of currently open manual positions.
  - `POST /api/manual/close-position` now closes selected `position_id` only.
- Dashboard label changed from `Open Positions (ETH)` to `Open Positions`.
- Strategy loop/rules remain ETHUSDT-only and unchanged.

### M20 - ASTER symbol ordering policy update

- Updated `/api/aster/symbols` ordering logic for ASTER Chart dropdown:
  - Pinned first (in exact fixed order):
    - `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `XRPUSDT`, `HYPEUSDT`, `PUMPUSDT`, `DOGEUSDT`
  - Remaining USDT pairs are sorted by 24h `quoteVolume` descending.

### M21 - Manual open positions table label refinement

- In `/manual` `Current Open Positions`, replaced first column from `Position ID` to `Coin`.
- Both `Strategy Position` and `Manual Position` tables now show trade coin name in first column.
- Position ID remains available in the close-position dropdown for precise manual close selection.

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
- `GET /api/aster/symbols`

ASTER trading data/actions:

- `GET /api/aster-trading/account-overview`
- `POST /api/aster-trading/order-preview`
- `POST /api/aster-trading/place-order`
- `POST /api/aster-trading/close-position`
- `GET /api/aster-trading/open-positions`
- `GET /api/aster-trading/open-orders`
- `GET /api/aster-trading/trade-history`
- `GET /api/aster-trading/pnl-history`

Pages:

- `/`
- `/manual`
- `/aster-chart` (alias: `/eth-chart`)
- `/aster-trading`
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

ASTER trading env keys:

- `ASTER_TRADE_BASE_URL`
- `ASTER_API_KEY`
- `ASTER_API_SECRET`
- `ASTER_SYMBOL` (fixed ETHUSDT intent)
- `ASTER_LEVERAGE`
- `ASTER_STOP_LOSS_PCT`
- `ASTER_TAKE_PROFIT_PCT`
- `ASTER_RISK_PER_TRADE_USDT`
- `ASTER_POSITION_NOTIONAL_USDT`
- `ASTER_MARGIN_PER_TRADE_USDT`
- `ASTER_RECV_WINDOW_MS`
- `ASTER_DRY_RUN`

## 8) Known Issues / Observations

- ASTER depth endpoint can intermittently return 502.
  - Mitigations already added: retries, fallback limit, UI tolerance.
- Chart is intentionally "inspired by" Hyperliquid, not a direct clone.
- API key was shared in chat earlier; rotation is recommended for security.
- For ASTER trading, keep `ASTER_DRY_RUN=true` until order-preview and filters are validated in UI.

## 9) Auto Update Rule

- AGENT must auto-update both files after every code change batch:
  - `PROJECT_LOG.md`
  - `app/templates/chatlog.html`
- This rule is persistent and does not require user reminder.

## 10) Suggested Next Steps

Priority upgrades:

1. Add MA50 overlay and entry/SL/TP markers directly on ASTER chart.
2. Add websocket market stream for smoother orderbook/ticker updates.
3. Add tests for dual-owner position mapping/reconciliation.
4. Add tests for pause/resume and manual action flows.
5. Add daily archive of logs/equity snapshots.

## 11) Session Resume Instructions

When a new assistant session starts:

1. Read this file (`PROJECT_LOG.md`) fully.
2. Read `app/templates/chatlog.html` for conversation intent and constraints.
3. Validate runtime quickly:
   - `docker compose up --build -d`
   - check `/api/status`
   - visit `/manual`, `/aster-chart`, and `/aster-trading`
4. Continue from section "Suggested Next Steps" unless user gives new direction.
