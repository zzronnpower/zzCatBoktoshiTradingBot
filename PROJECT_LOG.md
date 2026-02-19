# PROJECT_LOG

Last updated: 2026-02-19 (ASTER websocket fallback + overlay tests)
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

EMA strategy override (latest):

- Entry remains: EMA20 cross above EMA50 with RSI in 50-70 on closed 15m candle.
- Position management now uses R-multiple model:
  - `SL = 1R`
  - `TP = 2R`
  - Trailing stop activates after `>= 1R` profit and exits on `>= 1R` drawdown from peak PnL.
- Hard exit on closed-candle `EMA20 cross down EMA50`.
- One position per symbol enforced for EMA strategy (no duplicate LONG on same coin).

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

### M22 - Strategy selector and EMA-RSI (Phase 1, ETH only)

- Added second strategy implementation in `BoktoshiBotModule/strategy.py`:
  - `EMA_RSI_15M_ETH_ONLY`
  - Entry condition: EMA20 cross above EMA50 with RSI band filter (50-70), closed 15m candle.
- Added strategy registry and active strategy state to `BoktoshiBotModule/bot_runner.py`:
  - `MA50_4H_CROSSUP_3C_LONG_ONLY`
  - `EMA_RSI_15M_ETH_ONLY`
- Active strategy is persisted in KV (`active_strategy`) and restored on startup.
- Added strategy APIs:
  - `GET /api/strategies`
  - `POST /api/strategy/select`
- Updated `/api/status` to expose active strategy id/name/entry.
- Updated Manual page strategy control with strategy dropdown + `Apply Strategy` button.
- Phase 1 scope keeps strategy trading pair ETH-only; BTC multi-symbol strategy scope deferred.

### M23 - Manual bot settings save error fix

- Fixed backend bug in `app/main.py` where `/api/bot/settings` response path was broken after strategy endpoint insertion, causing 500 `ResponseValidationError`.
- Fixed frontend JSON parsing in `app/templates/manual.html` to safely handle non-JSON error bodies and show readable message.
- Verified `POST /api/bot/settings` now returns valid JSON (HTTP 200).

### M24 - Manual strategy control button UX

- Updated `/manual` strategy control button states based on runtime strategy state:
  - When strategy is `running`: `Resume` is disabled (gray), `Pause` is enabled.
  - When strategy is `paused`: `Pause` is disabled (gray), `Resume` is enabled.
- Added `syncStrategyButtons()` in `app/templates/manual.html` and wired it to live status refresh.

### M25 - UI theme system (Default + Pinky)

- Added global theme engine with user-selectable themes:
  - `Default` (current dark look)
  - `Pinky` (beige/pink retro palette)
- Added shared script `app/static/theme.js`:
  - injects a floating theme selector (`Theme: Default | Pinky`)
  - persists user preference in `localStorage`
  - emits `themechange` event for dynamic components
- Extended `app/static/app.css` with theme tokens and `[data-theme="pinky"]` overrides.
- Updated UI pages to include theme script:
  - `app/templates/index.html`
  - `app/templates/manual.html`
  - `app/templates/eth_chart.html`
  - `app/templates/aster_trading.html`
  - `app/templates/chatlog.html`
- Updated ASTER chart/trading styling to consume theme variables and avoid hardcoded dark-only colors.
- Chart canvas colors now react to theme switch via `themechange` listener.

### M26 - Theme apply hotfix (Pinky not visually switching)

- Added robust Pinky selector support in CSS:
  - `html[data-theme="pinky"]`
  - `body.theme-pinky`
- Updated `theme.js` to also toggle `body.theme-pinky` for compatibility.
- Added fallback initialization for cases where script loads after `DOMContentLoaded`.

### M27 - Add third theme: Light Green

- Added new global theme variant `Light Green` to theme engine.
- Updated `app/static/theme.js`:
  - supported theme ids: `default`, `pinky`, `light-green`
  - theme selector now includes `Light Green`
  - generalized body class sync to `theme-*` class pattern
- Updated `app/static/app.css` with `light-green` token palette:
  - sage/olive light background
  - green-muted text/line/accent
  - chart/input/button color tokens tuned for readability

### M28 - ChatLog readability on Pinky/Light Green

- Improved text contrast in `app/templates/chatlog.html` for light themes.
- Chat bubble message text is now brighter on `Pinky` and `Light Green`.
- Sender label (`User`/`Assistant`) color also adjusted for readability.

### M29 - Docker container name rename

- Updated Docker Compose container name from `mtc-bot` to `CatBoktoshiTradingBot`.
- Service key remains `mtc-bot`; runtime container display name now matches project naming.

### M30 - Strategy overlay API + ASTER chart MA50/Entry/SL/TP visuals

- Added strategy overlay API endpoint:
  - `GET /api/strategy/overlay`
- Overlay data source is Hyperliquid candles (strategy-consistent source), ETHUSDT-only.
- API now returns:
  - MA50 line points (`ma50`)
  - historical MA50 cross-up entry markers (`entry_markers`)
  - live strategy-position levels (`entry_price`, `stop_loss`, `take_profit`) when open
- Updated `ASTER Chart` UI (`app/templates/eth_chart.html`):
  - MA50 overlay line on chart
  - entry markers on candles
  - live Entry/SL/TP price lines when strategy position is open
  - overlay status note that explains ETH-only + 4H requirement

### M31 - Regression tests for owner mapping and pause/resume/manual close flows

- Added test suite `tests/test_bot_runner_flows.py` covering:
  - stale owner ID cleanup in position reconciliation
  - pause/resume status sync to KV (`bot_status`, `strategy_state`)
  - manual close guard (reject strategy-owned position id)
  - close-by-selected manual position and ID list update behavior
- Tests focus on core runtime safety paths for mixed owner model (strategy + manual).

### M32 - EMA strategy risk model upgrade (2R TP + trailing + EMA cross-down exit)

- Updated `EMA_RSI_15M_ETH_ONLY` runtime behavior in `BoktoshiBotModule/bot_runner.py`:
  - `takeProfit` at open is now set to `2R` (where `R = capital * SL_CAPITAL_PCT`).
  - trailing stop mode is activated after unrealized PnL reaches `>= 1R`.
  - trailing stop exits when drawdown from peak unrealized PnL reaches `>= 1R`.
  - immediate full exit when `EMA20` crosses below `EMA50` on closed 15m candle.
- Added EMA exit signal evaluator in `BoktoshiBotModule/strategy.py`:
  - `evaluate_exit_ema_cross_down_15m(...)`
- Added one-position-per-symbol guard for EMA strategy to prevent duplicate longs on the same coin.
- Extended `/api/status` strategy metadata with EMA-specific risk mode fields:
  - `risk_mode`, `tp_r_multiple`, `trailing_activation_r`
- Expanded tests in `tests/test_bot_runner_flows.py`:
  - trailing activation and trailing-stop exit behavior
  - EMA cross-down forced exit path
  - one-position-per-symbol guard path

### M33 - Manual tab: EMA runtime status + buy/sell signal summary

- Updated `GET /api/status` in `app/main.py` to include EMA runtime state payload under:
  - `strategy.ema_runtime`
  - sourced from KV key `ema_strategy_state`
- Updated `/manual` page (`app/templates/manual.html`) with:
  - EMA runtime block showing risk mode, trailing status, and `R / peak uPnL`
  - strategy behavior summary section describing buy/sell conditions in plain language
- Manual summary now explicitly documents:
  - BUY: EMA20 cross above EMA50 + RSI 50-70 on closed 15m candle
  - no repaint (closed-candle-only evaluation)
  - SELL: EMA20 cross down exit, SL 1R, TP 2R, trailing stop after 1R activation
  - one-position-per-symbol policy

### M34 - Dropdown readability fix (all themes)

- Updated global select/dropdown color tokens in `app/static/app.css`.
- All dropdown controls now use green background palette with high-contrast text to avoid white-on-white option text.
- Applied consistently for:
  - normal select controls (`.kv-row select`, `.card select`)
  - chart symbol dropdown option palette via shared tokens
  - floating theme selector (`.theme-dock select`)

### M35 - Manual summary panel prominence + stronger dropdown CSS fallback

- Moved EMA runtime + strategy summary from inside `Strategy Control` card into a dedicated visible card:
  - `Strategy Summary (EMA)` in `app/templates/manual.html`
- This makes the buy/sell explanation and live runtime state easier to locate at first glance.
- Strengthened dropdown styling fallback in `app/static/app.css`:
  - added `!important` on select/option color rules
  - added `-webkit-text-fill-color` and `color-scheme: dark`
- Goal: improve compatibility where native dropdown popup ignored normal CSS and stayed white.

### M36 - Docker dev hot-reload profile

- Added new development compose override file: `docker-compose.dev.yml`.
- Keeps existing production-like `docker-compose.yml` unchanged.
- Dev profile now mounts source folders into container for live code sync:
  - `./app -> /app/app`
  - `./BoktoshiBotModule -> /app/BoktoshiBotModule`
  - `./AsterTradingModule -> /app/AsterTradingModule`
- Dev profile runs Uvicorn with auto-reload and explicit reload directories.
- Added `WATCHFILES_FORCE_POLLING=true` in dev profile to improve file-change detection in Docker/WSL environments.

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
- `GET /api/strategy/overlay`

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

## 12) Latest Update (2026-02-19)

- Moved `Strategy Summary (EMA)` out of `app/templates/manual.html` into a dedicated page/tab: `app/templates/strategy_summary.html`.
- Added new route `GET /strategy-summary` in `app/main.py` and top nav link `Tóm tắt Strategy` on Manual + Strategy Summary pages.
- Translated strategy summary content to Vietnamese and added a more visual card style (status chip, highlighted rule rows) in `app/static/app.css`.

## 13) Latest Update (2026-02-19)

- Fixed Vietnamese diacritics on `/strategy-summary` so all UI labels and strategy rules display proper accented text.
- Updated runtime/status/error strings in `app/templates/strategy_summary.html` (for example: `Đang tải`, `Tạm dừng`, `Không tải được dữ liệu`).

## 14) Latest Update (2026-02-19)

- Rewrote Strategy Summary content to focus on `MA50 4H CrossUp 3 Candles (ETH Only)` with full Vietnamese description sections (idea, entry, filters, SL/TP, pros/cons, fit, operation mindset).
- Updated `app/templates/strategy_summary.html` header and quick-info block to reflect MA50 4H strategy context.
- Added runtime note behavior: if active strategy is not MA50, page still shows MA50 strategy documentation and displays a notice.

## 15) Latest Update (2026-02-19)

- Fixed regression on `/strategy-summary`: content now switches correctly by active strategy ID from `/api/status`.
- Added dual rendering branches in `app/templates/strategy_summary.html`:
  - `MA50_4H_CROSSUP_3C_LONG_ONLY` -> full MA50 4H Vietnamese summary.
  - `EMA_RSI_15M_ETH_ONLY` -> EMA/RSI 15m summary + runtime trailing/R metrics.
- Replaced hardcoded MA50-only header/meta with dynamic title/subtitle/meta rows so UI follows current strategy.

## 16) Latest Update (2026-02-19)

- Updated EMA strategy summary content on `/strategy-summary` to include additional long take-profit logic:
  - take profit when RR reaches 1.5R-2R, or RSI reaches 70, or EMA cross down as final exit.
  - clarified trailing-stop usage to lock profits while still allowing trend continuation.

## 17) Latest Update (2026-02-19)

- Added dev-only Docker compose override `docker-compose.dev.yml` for hot reload without changing production-like compose.
- Dev override now mounts source folders (`app/`, `BoktoshiBotModule/`, `AsterTradingModule/`) into container.
- Dev override runs Uvicorn with `--reload` and explicit `--reload-dir` values.
- Added `WATCHFILES_FORCE_POLLING=true` in dev override to improve file change detection on Docker Desktop + WSL.

## 18) Latest Update (2026-02-19)

- Fixed ASTER Chart strategy overlay mismatch when active strategy is `EMA_RSI_15M_ETH_ONLY`.
- Updated `/api/strategy/overlay` in `app/main.py` to be strategy-aware:
  - MA50 strategy returns MA50 line + MA50 x3 entry markers on required timeframe `4h`.
  - EMA strategy returns EMA20/EMA50 lines + EMA/RSI entry markers on required timeframe `15m`.
  - Endpoint now returns `required_interval` and disables overlay when current chart timeframe does not match strategy timeframe.
- Added indicator helpers in `BoktoshiBotModule/strategy.py`:
  - `build_ema_series(...)`
  - `detect_ema_rsi_long_markers(...)`
- Updated chart UI in `app/templates/eth_chart.html`:
  - supports dynamic overlay lines (MA50 vs EMA20/EMA50)
  - requests overlay by current timeframe and shows clear hint when timeframe mismatch occurs.

## 19) Latest Update (2026-02-19)

- Added ASTER market websocket integration to chart page (`app/templates/eth_chart.html`):
  - combined stream connection to `wss://fstream.asterdex.com/stream` for:
    - `<symbol>@depth10@100ms`
    - `<symbol>@markPrice@1s`
  - live websocket orderbook rendering with auto-reconnect and exponential backoff.
- Added resilient REST fallback behavior for orderbook:
  - if websocket disconnects or has no fresh updates, REST depth polling remains active.
  - orderbook status now clearly indicates websocket vs REST source.
- Added browser cleanup hook to close websocket on page unload.
- Added regression test file `tests/test_strategy_overlay.py` to validate overlay behavior:
  - EMA strategy requires `15m` and returns EMA lines.
  - MA50 strategy requires `4h` and returns MA50 line.
- Verification notes:
  - `python3 -m compileall app BoktoshiBotModule tests` passed.
  - `pytest` is not installed in current local environment (`No module named pytest`).
