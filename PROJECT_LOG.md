# PROJECT_LOG

Last updated: 2026-03-02 (manual same-symbol stacking + per-order overrides)
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

Latest runtime update (2026-02-25):

- Strategy engine now supports 2 runtime modes from Manual page:
  - `Apply Strategy` -> run single selected strategy.
  - `Run All Strategy` -> run both MA50 + EMA/RSI simultaneously.
- Both strategies are now evaluated on fixed symbol basket: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`.
- Pause/Resume remains global for strategy engine and preserves current mode on resume.
- Manual symbol whitelist now includes `TAOUSDT`.
- ASTER chart symbol pin list now includes `TAOUSDT` directly under `SOLUSDT`.

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

## 20) Latest Update (2026-02-19)

- Added manual SHORT open flow with same runtime config profile as LONG (margin/leverage/SL%/TP%).
- Implemented inverse SHORT risk target builder in `BoktoshiBotModule/risk.py`:
  - `stopLoss` above entry, `takeProfit` below entry.
- Refactored manual open path in `BoktoshiBotModule/bot_runner.py`:
  - new shared `manual_force_open(side=...)`
  - wrappers: `manual_force_open_long(...)` and `manual_force_open_short(...)`
  - added strict target-direction guards before API submit:
    - LONG requires `stopLoss < entry < takeProfit`
    - SHORT requires `takeProfit < entry < stopLoss`
- Added no-hedge protection for manual open:
  - rejects opening SHORT when opposite LONG is open on same symbol.
  - rejects opening LONG when opposite SHORT is open on same symbol.
  - keeps one manual-owned position per symbol regardless side.
- Added API endpoint `POST /api/manual/force-open-short` in `app/main.py`.
- Updated Manual page UI (`app/templates/manual.html`):
  - now has both `OPEN Manual LONG Position` and `OPEN Manual SHORT Position` actions.
  - updated panel description to reflect no-hedge behavior.
- Added tests:
  - `tests/test_risk_short.py` for directional LONG vs SHORT risk targets.
  - extended `tests/test_bot_runner_flows.py` for manual SHORT payload + no-hedge checks.
- Verification notes:
  - `python3 -m compileall app BoktoshiBotModule tests` passed.

## 21) Latest Update (2026-02-19)

- Updated manual open trade comment text sent to MTC API (`app/main.py`) with styled, side-specific message and trailing period:
  - LONG: `zzCatzz from the Matrix is opening a LONG position on {PAIR}.`
  - SHORT: `zzCatzz from the Matrix is opening a SHORT position on {PAIR}.`
- Updated manual open payload builder (`BoktoshiBotModule/bot_runner.py`) to use provided comment verbatim (no extra side/symbol suffix appended).
- This applies to both manual endpoints:
  - `POST /api/manual/force-open-long`
  - `POST /api/manual/force-open-short`

## 22) Latest Update (2026-02-19)

- Updated manual close trade comment text sent to MTC API (`app/main.py`) for `POST /api/manual/close-position`:
  - `zzCatzz has exit the Maxtrix. ﾏﾄﾘｯｸｽ ﾏﾄﾘｯｸｽ ﾏﾄﾘｯｸｽ`

## 23) Latest Update (2026-02-19)

- Expanded ASTER Chart overlay scope from ETH-only to top 10 symbols in the ranked dropdown list.
- Updated overlay backend (`app/main.py`):
  - validates symbol against first 10 results from `get_usdt_symbols_ranked(...)`.
  - computes overlay candles on selected symbol coin (not hardcoded ETH).
  - keeps strategy timeframe constraints (`MA50 -> 4h`, `EMA -> 15m`).
  - raises overlay candle cap from 600 to 1000 bars.
- Updated chart frontend (`app/templates/eth_chart.html`):
  - added Overlay toggle button with default OFF state.
  - overlay requests and auto-refresh only run when toggle is ON.
  - overlay request limit increased to 1000.
  - kline chart request limit increased from 400 to 1000.
  - when OFF, overlay data/markers are cleared and status shows disabled hint.
  - when symbol is outside top 10, status clearly reports availability constraint.
- Updated overlay tests (`tests/test_strategy_overlay.py`):
  - mock ranked symbol list for deterministic behavior.
  - added test that rejects symbols outside top 10.
- Verification notes:
  - `python3 -m compileall app BoktoshiBotModule tests` passed.

## 24) Latest Update (2026-02-19)

- Added new backend action to close all manual-owned positions in one click:
  - `BotRunner.manual_close_all_positions(...)` in `BoktoshiBotModule/bot_runner.py`.
  - Supports both LONG and SHORT manual positions.
  - Keeps ownership safety: closes only position IDs in `manual_position_ids`.
  - Returns structured result with `closed`, `failed`, `closed_ids`, and `errors`.
- Added API endpoint:
  - `POST /api/manual/close-all-positions` in `app/main.py`.
  - Uses existing Matrix-style close comment text.
- Updated Manual UI (`app/templates/manual.html`):
  - Added orange button `Close All Manual Pos` next to `Manual Close Position`.
  - Added confirm dialog and action handler to call the new endpoint.
- Added regression test in `tests/test_bot_runner_flows.py`:
  - verifies close-all closes only manual-owned positions and clears manual ownership IDs.

## 25) Latest Update (2026-02-19)

- Added workflow note in `AGENTS.md` to auto-run dev stack after each coding task without asking user first.
- Standardized command for post-change bring-up:
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`
- Executed stack command immediately after implementing close-all control update; container remains running.

## 26) Latest Update (2026-02-22)

- Updated ASTER Chart default timeframe to `4h` on first load in `app/templates/eth_chart.html`.
- Extended timeframe button set on chart toolbar with:
  - `3D` (`3d` interval)
  - `1W` (`1w` interval)
- Kept existing behavior for all other chart refresh and overlay flows unchanged.

## 27) Latest Update (2026-02-22)

- Enhanced ASTER Chart with a separate toggleable position layer:
  - Added new button `Open Position Overlay` (independent from `Strategy Overlay`).
  - The position layer now reads runtime positions from `GET /api/open-positions`.
  - It renders live price lines per open position on selected symbol:
    - `Entry`
    - `SL`
    - `TP`
  - Supports both owners:
    - strategy-owned position
    - manual-owned positions (multi-position list)
  - Status line now shows per-position summary including side (`LONG/SHORT`) and `uPnL`.
- Fixed ASTER Chart viewport reset issue:
  - `fitContent()` is no longer applied on every periodic kline refresh.
  - Chart now keeps current zoom/scroll view during auto-refresh.
  - `fitContent()` is applied only when needed (initial load or when changing symbol/timeframe).

## 28) Latest Update (2026-02-22)

- Improved ASTER Chart real-time candle behavior in `app/templates/eth_chart.html`:
  - Added websocket kline stream subscription per selected symbol + timeframe (`@kline_<interval>`).
  - Chart now updates live candle and volume via `series.update(...)` from websocket ticks.
  - Kline REST polling remains as fallback, reduced to a slower sync interval (30s) to avoid overriding live updates.
  - On timeframe switch, websocket reconnect now follows the new interval.
- Simplified `Open Position Overlay` status text to avoid line-jump noise:
  - Removed long Entry/TP/SL summary text from status line.
  - Status now shows only per-position `uPnL` rows (strategy/manual, side) with bold orange highlight.

## 29) Latest Update (2026-02-22)

- Updated ASTER Chart `Open Position Overlay` unit label from `USDT` to `BOKS` for per-position `uPnL` text in `app/templates/eth_chart.html`.

## 30) Latest Update (2026-02-25)

- Dashboard history now tracks closed-trade realized PnL flow instead of unrealized equity snapshots:
  - `GET /api/trade-history` now returns `closed_trades` sourced from normalized remote history.
  - `GET /api/pnl-history` now returns realized PnL rows per closed trade (`realized_pnl`, `commission`, `fees`, `net`).
- Added persistent journal storage table `journal_entries` with upsert/update helpers in `app/storage.py`:
  - supports source sync, paging, search, summary aggregation, and notes/tags updates.
- Added new standalone tab/page: `Bokoshi Trading Journal` (`/journal`):
  - rich journal table with date/time, symbol, side, qty, entry/exit, commission, fees, net, notes, tags.
  - search by notes/tags/symbol, configurable page size, previous/next paging.
  - summary strip: fills, best, worst, qty, gross, commission, fees, net, wins, losses.
  - notes/tags editable per row via `PATCH /api/journal/{entry_id}`.
- Dashboard UX update for long history lists:
  - Trade History and PnL History now paginate client-side at 20 rows/page with prev/next controls.
  - Trade History table now includes realized PnL and net columns for closed trades.
- Navigation updated across main pages to include `Bokoshi Trading Journal` tab.
- Dev stack auto-run completed after code update:
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`
  - status: `CatBoktoshiTradingBot-dev` is running.

## 31) Latest Update (2026-02-25)

- Adjusted implementation to match final user requirements:
  - Dashboard `PnL History` rolled back to legacy equity snapshots (`unrealized`, `balance`, `total_equity`) from `equity_curve`.
  - Dashboard `Trade History` keeps closed-trade realized flow and removes `Net` column.
  - Trade History now shows `Entry`, `Exit`, `Qty`, `Realized PnL`, and `Source`.
- Improved closed-trade extraction in `app/main.py` for better Journal/Trade History fill rate:
  - wider schema normalization for realized/entry/exit/qty fields.
  - fallback quantity derivation from `margin * leverage / entry_price` when possible.
  - local OPEN/CLOSE pairing fallback added to backfill `entry_price`, `qty`, and realized estimate when enough data exists.
  - if cached `last_history` is empty, backend now attempts live `get_history(limit=300)` and refreshes cache.
- `Boktoshi Trading Journal` page updated to requested layout/content:
  - keeps trade-centric columns: Date, Time, Symbol, Side, Entry, Exit, Qty, Realized PnL, Notes.
  - removes Net, Commission, Fees, and Options columns.
  - Notes now supports inline Edit -> input -> Save/Cancel and persists via `PATCH /api/journal/{entry_id}`.
  - summary strip simplified to fills, best/worst PnL, qty, total PnL, wins/losses.
- Naming cleanup across navigation labels:
  - unified title/tab text to `Boktoshi Trading Journal`.
- Dev stack re-run after modifications:
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`
  - status remains running.

## 32) Latest Update (2026-02-25)

- Implemented full follow-up bundle from latest discussion:
  - Dashboard Trade History now uses trade-sized notional column `Size (BOKS)` (not `Qty`).
  - Dashboard Trade History source now uses business labels (`Manual`, `Strategy`, `Stra closed Manually`, fallback `Unknown`) instead of internal `local_close`.
  - Dashboard PnL History remains in unrealized equity mode and now paginates with shorter viewport target (10 rows per page on UI pager logic).
- Journal upgraded for operations clarity:
  - Added `Source` column with same label set as Dashboard.
  - Replaced `Qty` with `Size (BOKS)` for easier position sizing readout.
  - Notes remain editable inline via Edit -> Save/Cancel and persisted through `PATCH /api/journal/{entry_id}`.
- Added stronger close-trade reconciliation in backend (`app/main.py`):
  - source/mode inference from close payload comment/note patterns.
  - computes `size_boks` from entry*qty with fallback to notional or margin*leverage.
  - stale-recovery flow now creates synthetic closed trades when an open order id disappears from active positions without close callback.
  - this recovers missing entries like prior `PUMPUSDT` close visibility gap.
- Added lightweight sync throttling for journal rebuild:
  - `_sync_journal_snapshot()` now uses `kv.journal_last_sync_ts` (20s TTL) to avoid expensive repeated history reconciliation on rapid page/API refresh.
- Enriched bot close writes (`BoktoshiBotModule/bot_runner.py`):
  - close events now include `source` and `close_mode` metadata in stored notes payload for more reliable Journal source labeling later.
- Runtime checks confirmed:
  - `PUMP` recovered row now appears in both `/api/trade-history` and `/api/journal` with `source_label=Manual`, `size_boks=1000.0`, and recovery reason.

## 33) Latest Update (2026-02-25)

- Added visual recovered-close badge on both Dashboard and Journal for faster incident review:
  - Dashboard Trade History Source cell now shows `Recovered` chip when row is stale-recovered.
  - Journal Source cell now shows same `Recovered` chip for parity.
  - chip includes tooltip with recovery reason (`close_reason`) to explain why the close was reconstructed.
- Added shared style in `app/static/app.css`:
  - `.recovered-chip` with amber warning tone to distinguish reconstructed rows from normal closes.

## 34) Latest Update (2026-02-25)

- Fixed major Journal/Trade History data integrity issues reported during close-test:
  - resolved duplicate close rows caused by unstable fallback `external_id` format using per-loop `idx`.
  - fallback close IDs are now stable (`local-close:<positionId>` when available, otherwise deterministic row fallback).
  - journal sync now uses exact-replace reconciliation (`replace_journal_entries`) to prune obsolete/legacy duplicate rows.
- Improved close enrichment fidelity:
  - close payloads now store a compact `close_snapshot` (entry/current/size/margin/leverage/uPnL, etc.) in `BoktoshiBotModule/bot_runner.py` for manual, strategy-manual, and strategy-auto close paths.
  - fallback parser now extracts entry/size/exit/pnl hints from close snapshot when upstream close response omits realized fields.
- Added clearer lifecycle visibility for incomplete close settlement:
  - API decoration now marks rows with `pending=1` when close exists but finalized realized data is not yet present from server history.
  - Dashboard/Journal render `Pending settlement` instead of blank realized cell.
- Source labeling reliability improved:
  - `Stra closed Manually` now persists correctly for strategy positions closed manually.
  - source inference now inspects nested raw notes text as additional hint.
- History fetch robustness improved:
  - live history sync now attempts paginated pulls (`offset` pages) before falling back to cached `last_history`.

## 35) Latest Update (2026-02-25)

- Implemented user-requested estimated close fallback + manual refresh control:
  - Added API endpoint `POST /api/journal/refresh` to force immediate reconciliation/sync and return refreshed count + pending count.
  - Added `Refresh Finalized PnL` button on Dashboard Trade History and Journal toolbar.
- Added estimated Exit/PnL projection when server history has not finalized close values yet:
  - response rows now expose `display_exit_price`, `display_realized_pnl`, `exit_estimated`, `realized_estimated`.
  - estimates use priority: close snapshot -> recent market price hints (ASTER mark/last) -> entry/size math.
  - UI now marks estimated values with `Estimated/Est` chips; unresolved rows keep `Pending settlement`.
- Fixed further close-data consistency:
  - added stable local close IDs (`local-close:<positionId>`), reducing duplicate row risk.
  - added close snapshot capture in bot close paths (manual/strategy/auto risk close) to preserve entry/current/size context at close time.
  - switched journal sync persistence to replacement mode (`replace_journal_entries`) so stale duplicate records are pruned.

## 36) Latest Update (2026-02-25)

- Journal summary metrics now include estimated PnL values (as requested):
  - `Total PnL`, `Best PnL`, `Worst PnL`, `Wins`, and `Losses` are computed from `display_realized_pnl`.
  - If real Boktoshi PnL exists it is used directly; otherwise estimated PnL is used for summary rollups.
- `GET /api/journal/summary` moved to decorated-row aggregation path in `app/main.py`:
  - reads rows, applies estimate enrichment, then aggregates in Python.
  - preserves summary keys used by current UI (`gross`, `best`, `worst`, etc.).
- Increased journal row fetch cap for summary scans:
  - `get_journal_entries` internal limit raised to 10,000 in `app/storage.py`.

## 37) Latest Update (2026-02-25)

- Fixed Trade History horizontal-scroll UX issue on Dashboard:
  - Root cause: table auto-refresh every ~3s rebuilt DOM and reset/interrupt scroll interaction.
  - Added interaction-aware rendering for History table in `app/templates/index.html`:
    - preserves `scrollLeft` across rerenders,
    - tracks hover/touch/scroll activity,
    - temporarily skips History rerender while user is actively scrolling.
- Result: user can scroll right to inspect columns without immediate snap-back refresh.

## 38) Latest Update (2026-02-25)

- Added strict runtime table retention caps (as requested):
  - `logs` capped to latest 100 rows.
  - `signals` capped to latest 100 rows.
  - `equity_curve` (PnL History source) capped to latest 100 rows.
- Implemented automatic pruning in `app/storage.py`:
  - trims after each insert (`add_log`, `add_signal`, `add_equity_snapshot`).
  - added shared helper `_trim_table_by_id(...)`.
  - added `trim_runtime_tables(db_path)` for one-shot cleanup.
- Startup now enforces cleanup immediately:
  - `app/main.py` startup flow calls `trim_runtime_tables(DB_PATH)` right after DB init.

## 39) Latest Update (2026-02-25)

- Created structured execution tracker: `CHECKLIST_CAI_THIEN_HE_THONG.md`.
  - includes phased roadmap (quick wins -> performance/data integrity -> test/release safety).
  - progress markers (`[ ]/[~]/[x]`) and running implementation journal.
- Implemented Phase 1.1 from checklist (decouple heavy sync from request path):
  - added background journal sync worker with lock in `app/main.py`:
    - `_run_journal_sync_task(...)`
    - `_trigger_journal_sync(...)`
  - `/api/trade-history`, `/api/journal`, `/api/journal/summary` now trigger async sync and return fast from local DB.
  - startup now runs warm-up journal sync in background.
  - `/api/journal/refresh` remains force-sync (blocking) for manual finalization refresh.
- Fixed estimate PnL persistence regression:
  - removed 2-hour cutoff in `_recent_market_price_hints(...)` so pending rows can continue showing estimated Exit/PnL until finalized data arrives.
- Continued checklist execution (Phase 1.2 partial):
  - Dashboard polling split into fast/slow lanes in `app/templates/index.html`:
    - fast lane (3s): status/account/open positions
    - slow lane (15s cache): trade history, pnl history, signals, logs
  - `Refresh Finalized PnL` button now invalidates slow cache to force immediate visible update.
- Runtime verification:
  - `GET /api/trade-history` stays low latency (single-digit to low-teens ms) after decoupling.
  - force refresh endpoint remains heavy by design (`POST /api/journal/refresh` ~seconds).

## 40) Latest Update (2026-02-25)

- Fixed estimate-PnL persistence behavior after optimization changes:
  - removed 2-hour cutoff from estimator symbol selection so pending closes can continue showing estimate over longer windows.
  - added startup forced sync warm-up to also prefill estimate price hints in background (`_run_journal_sync_task(force=True)`).
- Reduced unnecessary frontend rerenders on Dashboard (`app/templates/index.html`):
  - added hash-based change detection for Trade History, PnL History, Signals, Logs.
  - tables/lists only rerender when payload content actually changes.
  - combined with prior interaction-preserving scroll logic for smoother UX.
- Hardened SQLite runtime behavior (`app/storage.py`):
  - centralized DB connection helper with `timeout` + `PRAGMA busy_timeout`.
  - enabled `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` during DB init.
  - created indexes for hot query paths:
    - `idx_logs_ts`
    - `idx_signals_ts`
    - `idx_trades_ts_action`
    - `idx_equity_curve_ts`
    - `idx_journal_entries_close_ts`
    - `idx_journal_entries_source`
- Latency trade-off now explicit:
  - normal reads (`/api/trade-history`) remain fast after warm cache/background sync.
  - force refresh endpoint (`/api/journal/refresh`) still intentionally heavier due network hint pull and reconciliation.

## 41) Latest Update (2026-02-25)

- Continued checklist execution with finalize-retry and integrity monitoring:
  - Added pending finalize retry queue by `positionId` in `app/main.py`:
    - state persisted in KV (`journal_pending_finalize_state`)
    - exponential backoff retry scheduling (15s up to 900s)
    - 24h timeout window for stale unresolved entries
    - remote history fetch now conditionally triggered by due retries/TTL/force.
  - Added remote history sync cadence key (`journal_remote_history_last_sync_ts`) to reduce unnecessary live history pulls.
- Added integrity monitoring surfaces:
  - API endpoint `GET /api/system/integrity-report`:
    - duplicate external IDs
    - stale pending rows
    - missing core fields summary/examples
    - includes current pending finalize queue state.
  - Offline script `scripts/integrity_check.py` for direct DB scans (CLI JSON report).
- Preserved estimate visibility while keeping reads fast:
  - normal read endpoints avoid network hint fetches by default.
  - force refresh path still allows network hint enrichment.

## 42) Latest Update (2026-02-25)

- Continued next checklist phase with testability and safety improvements:
  - Added `tests/conftest.py` to inject repository root into `sys.path` and fix module imports for `app` / `BoktoshiBotModule`.
  - Added `pytest.ini` for stable test discovery (`testpaths=tests`).
- Added/extended tests for new system behaviors:
  - `tests/test_journal_helpers.py`
    - validates summary rollup uses `display_realized_pnl` (real + estimated) for best/worst/total/win/loss.
    - validates integrity report catches duplicate external IDs and stale/missing-core cases.
  - `tests/test_integrity_script.py`
    - validates integrity script excludes recovered rows from stale pending alarms.
- Test run status:
  - `pytest` now runs successfully with collection fixed.
  - latest run: `18 passed`.

## 43) Latest Update (2026-02-25)

- Continued next checklist phase with observability + resilience validation:
  - Added endpoint `GET /api/system/metrics` in `app/main.py`.
    - captures per-API request latency stats (`count`, `avg_ms`, `max_ms`, `last_ms`),
    - journal sync run metrics (`runs/success/errors/last_duration_ms/last_error`),
    - remote history fetch metrics (`fetch_runs/fetch_errors/last_fetch_count`),
    - pending finalize queue size.
  - Added lightweight request timing middleware for `/api/*` paths.
- Improved journal sync instrumentation:
  - sync routine now records success/error durations into metrics.
  - remote history fetch attempts/errors are counted for health visibility.
- Added and validated lock contention benchmark script:
  - `scripts/lock_contention_check.py` (multi-threaded KV read/write stress).
  - benchmark result (8 workers x 250 loops): `total_err=0`, confirming busy-timeout/WAL settings are effective in this workload.
- Added dedicated dedupe regression test:
  - `tests/test_journal_storage_dedupe.py` verifies `replace_journal_entries` update/prune semantics and stable dedup behavior.
- Test status update:
  - `pytest`: `19 passed`.

## 44) Latest Update (2026-02-25)

- Continued checklist execution with final observability/logging hardening:
  - Added structured trading logs in `BoktoshiBotModule/bot_runner.py` via helper:
    - `_log_structured(...)`
    - `_close_external_id(...)`
  - Core open/close lifecycle logs now include structured fields like:
    - `event`
    - `position_id`
    - `external_id` (`local-close:<positionId>`)
    - `error_code` (when failures happen)
  - Applied structured events to:
    - close submitted/failed/dry-run/rate-limited
    - manual open submitted/failed/dry-run
    - strategy open submitted/failed/skipped reasons
    - stale position-id cleanup events.
- Added observability test coverage:
  - new test file `tests/test_system_metrics.py` for `GET /api/system/metrics` payload contract.
- Test status update:
  - `pytest`: `20 passed`.

## 45) Latest Update (2026-02-25)

- Finalized current improvement program checklist:
  - marked deliverables section complete in `CHECKLIST_CAI_THIEN_HE_THONG.md`:
    - change documentation completed,
    - verification completed,
    - checklist status updates completed.
- Current checklist state now indicates no remaining unchecked technical phase items.

## 46) Latest Update (2026-02-25)

- Added next-cycle planning document: `NEXT_ROADMAP.md`.
  - defines post-checklist phases for architecture cleanup, UX/operations, data quality, CI/testing, and performance targets.
  - includes suggested execution order for next improvement wave.

## 47) Latest Update (2026-02-25)

- Executed full 5-phase roadmap implementation pass:
  - **Phase A (Architecture cleanup)**
    - introduced `app/services/journal_app_service.py`.
    - wired journal/trade-history/integrity read-model endpoints in `app/main.py` through service layer to reduce endpoint logic coupling.
  - **Phase B (UX + operations)**
    - Dashboard now includes `System Health` panel fed from `/api/system/metrics`.
    - added `Clear Stale Pending Queue` action (`POST /api/journal/clear-stale-pending`).
    - Journal page now supports quick filters: source / finalization state / recovered.
  - **Phase C (Data quality)**
    - journal row decoration now exposes:
      - `finalization_state` (`PENDING` / `ESTIMATED` / `FINALIZED`)
      - `estimated_source` (`snapshot` / `market_hint` / `formula` / `none`)
  - **Phase D (Test + CI)**
    - added GitHub Actions workflow `.github/workflows/pytest.yml`.
  - **Phase E (Performance targets)**
    - added `scripts/perf_targets_check.py` with target assertions:
      - `/api/trade-history` p95 < 40ms
      - `/api/journal` p95 < 25ms
      - `/api/journal/refresh` < 5000ms
    - local run passed all configured thresholds.
- Verification snapshot:
  - tests: `20 passed`.
  - smoke endpoints: metrics, journal filters, summary filters, clear-stale queue all return `200`.

## 48) Latest Update (2026-02-25)

- Manual strategy-close exchange comment is now aligned with manual close comment text.
  - Updated `POST /api/manual/close-strategy-position` in `app/main.py` to send:
    - `zzCatzz has exit the Maxtrix. ﾏﾄﾘｯｸｽ ﾏﾄﾘｯｸｽ ﾏﾄﾘｯｸｽ`
- Scope intentionally limited per request:
  - only exchange-bound `comment` string changed,
  - no changes to UI/API return message semantics.

## 49) Latest Update (2026-02-25)

- Updated close comments for both Manual and Strategy exits to a unified new phrase.
  - New close comment:
    - `The SuperBOT of zzCatzz has exited the ﾏﾄﾘｯｸｽ ﾏﾄﾘｯｸｽ ﾏﾄﾘｯｸｽ!`
- Applied to all close endpoints in `app/main.py`:
  - `POST /api/manual/close-position`
  - `POST /api/manual/close-all-positions`
  - `POST /api/manual/close-strategy-position`
- Scope intentionally unchanged:
  - only exchange-bound `comment` updated,
  - UI/API return messages remain the same.

## 50) Latest Update (2026-02-25)

- Manual strategy control UX updated per operator request:
  - Removed standalone `Run All Strategy` button from `/manual`.
  - Added dropdown option: `Run All Strategy Simultaneously`.
  - `Apply Strategy` now routes by selected value:
    - `RUN_ALL` -> `POST /api/strategy/run-all`
    - strategy id -> `POST /api/strategy/select`
  - Strategy Note text when selecting run-all option is now:
    - `Running All Strategies Simultaneously`

## 51) Latest Update (2026-02-25)

- Manual close UI on `/manual` was split into two separate cards:
  - `CLOSE MANUAL POSITION`
  - `CLOSE STRATEGY POSITION`
- Strategy close controls now support both single-select close and bulk close:
  - `POST /api/manual/close-strategy-position` now accepts optional JSON body `position_id` and closes the selected strategy-owned position.
  - Added `POST /api/manual/close-all-strategy-positions` to close all strategy-owned positions in one action.
- Backend strategy close flow in `BoktoshiBotModule/bot_runner.py` is no longer ETH-only:
  - resolves strategy-owned IDs from `strategy_position_ids` map,
  - supports BTCUSDT / ETHUSDT / SOLUSDT strategy positions,
  - preserves per-position coin/side metadata in trade logs,
  - returns aggregate close result for bulk flow (`closed`, `failed`, `closed_ids`, `errors`).
- Regression coverage added in `tests/test_bot_runner_flows.py`:
  - close selected strategy position,
  - close all strategy positions across BTC/ETH/SOL.
- Verification:
  - `pytest tests/test_bot_runner_flows.py` => `12 passed`
  - `pytest` => `22 passed`

## 52) Latest Update (2026-02-25)

- Renamed manual navigation tag across UI from `Manual Trade` to `Position Management`.
  - Updated nav label in:
    - `app/templates/index.html`
    - `app/templates/manual.html`
    - `app/templates/journal.html`
    - `app/templates/eth_chart.html`
    - `app/templates/aster_trading.html`
    - `app/templates/strategy_summary.html`
    - `app/templates/chatlog.html`
- Added dedicated nav style for the Position Management tag:
  - New class: `.nav-position-management`
  - Light yellow background and matching active state in `app/static/app.css`.
- Updated manual page identity text to match new naming:
  - HTML title: `Position Management - zzCatBoktoshiTradingBot`
  - Header title: `Position Management Console`

## 53) Latest Update (2026-02-25)

- Position Management UI refinement on `/manual`:
  - moved `Close All Manual Positions` onto a new line under `Manual Close Position` in the `CLOSE MANUAL POSITION` card.
  - renamed button label from `Close All Manual Pos` to `Close All Manual Positions`.
  - synchronized JS button reset text to the new full label.
- Navigation emphasis update:
  - increased text weight for `.nav-position-management` in `app/static/app.css`.
  - active state is now bolder for clearer visual priority.

## 54) Latest Update (2026-02-25)

- Reordered the top cards on `/manual` (Position Management) per operator UX preference.
  - New order in the first grid row sequence:
    1. `BOT SETTINGS`
    2. `MANUAL TRADE PANEL`
    3. `STRATEGY CONTROL`
- Scope is layout-only reorder in `app/templates/manual.html`; control IDs and API wiring were kept unchanged.

## 55) Latest Update (2026-02-25)

- Per operator request, completed full housekeeping sync before shutdown:
  - updated `AGENTS.md` to reflect current multi-symbol strategy scope and Position Management flows.
  - aligned `AGENTS.md` runtime landmarks to current module location (`BoktoshiBotModule/bot_runner.py`).
  - documented current high-use API set for strategy/manual close operations including selected/all strategy close endpoints.
- Documentation continuity update:
  - appended current request/response trace to `app/templates/chatlog.html`.
  - retained chronological update chain in `PROJECT_LOG.md` for next-session fast resume.

## 56) Latest Update (2026-02-25)

- Added a new migration report page for Freqtrade assessment and integration planning:
  - New template: `app/templates/fredtrade_migration_report.html`
  - New route: `GET /fredtrade-migration-report`
- Report content includes:
  - detailed evaluation of what Freqtrade is,
  - integration feasibility with BOktoshi,
  - Aster compatibility note,
  - recommended architecture (separate service adapter model),
  - full endpoint-by-endpoint API mapping plan for implementation.
- Added direct navigation entry `FredTradeMigration Report` to:
  - `app/templates/index.html`
  - `app/templates/strategy_summary.html`
- Report page style is highlighted with color-coded focus sections (success/warn/info badges and mapping tables) and Vietnamese content with full diacritics.

## 57) Latest Update (2026-02-25)

- Added full pre-implementation assessment for new strategy proposal from `PsudoCode4hSystem.md`:
  - System target: `4H_REGIME_SWITCH_V1` (TREND/RANGE regime switching on `BTCUSDT`, `ETHUSDT`, `SOLUSDT`).
  - Feasibility in current Boktoshi architecture: **high** (estimated 8/10) for `LONG-only` first rollout.
- Integration fit with current codebase was reviewed across:
  - strategy logic layer (`BoktoshiBotModule/strategy.py`),
  - runtime decision loop and state handling (`BoktoshiBotModule/bot_runner.py`),
  - status/strategy APIs and overlay API (`app/main.py`),
  - operator UI pages (`/manual`, `/strategy-summary`, `/aster-chart`),
  - regression test surface (`tests/test_bot_runner_flows.py`, `tests/test_strategy_overlay.py`).
- Critical implementation notes captured before coding:
  - Current execution payload model is `margin + leverage` (not direct `qty`), so risk-based sizing from pseudo-code must be converted to dynamic margin sizing with hard min/max guards.
  - Strategy must be evaluated on **closed 4H candles only** (new-candle gate) to avoid over-triggering from 20s poll loop.
  - Indicator stack required by pseudo-code (`ADX`, `ATR`, `Bollinger`, `Donchian`, ATR slope) is not yet implemented in current strategy module and must be added with deterministic formulas.
  - Daily drawdown guard (`MAX_DAILY_DRAWDOWN`) and cooldown bars need persisted state in KV to survive restarts.
  - Overlay contract currently optimized for MA50/EMA lines; new regime strategy requires extended overlay payload for regime/exits/markers.
- Main risk set documented:
  - indicator implementation mismatch risk (especially ATR/ADX smoothing);
  - API load risk if 600-bar lookback is recomputed too frequently;
  - portfolio concentration risk due to BTC/ETH/SOL correlation;
  - persistence risk if trailing/cooldown/day-state is not restored after restart.
- Recommended rollout path logged for next session:
  - **Phase 1 (recommended):** LONG-only TREND + RANGE with strict risk guards.
  - **Phase 2:** performance and concentration controls.
  - **Phase 3:** optional SHORT support only after paper validation.
- End-of-day operator decision recorded: planning and assessment complete; implementation scheduled for next working session.

## 58) Tích hợp Fredtrade (2026-02-25)

- Đã hoàn tất nghiên cứu toàn diện dự án Freqtrade để phục vụ lộ trình nâng cấp BOktoshi.
- Đã tạo trang báo cáo riêng: `FredTradeMigration Report` với nội dung tiếng Việt đầy đủ:
  - Bản chất dự án Freqtrade và năng lực lõi.
  - Khả năng tích hợp với BOktoshi.
  - Khả năng kết nối Aster.
  - Khuyến nghị kiến trúc (service riêng + adapter).
  - Thiết kế tích hợp chi tiết endpoint-by-endpoint và schema mapping.
- Kết luận kỹ thuật:
  - Khả năng tích hợp: cao nếu đi theo mô hình `BOktoshi API/UI + Freqtrade Engine Service`.
  - Aster: có khả năng kết nối theo hướng CCXT, nhưng cần triển khai theo lộ trình thử nghiệm an toàn trước production.
- Quyết định vận hành:
  - Đây là hạng mục lớn, sâu, cần thêm thời gian nghiên cứu.
  - Tạm dừng triển khai code tích hợp ngay thời điểm hiện tại.
  - Trạng thái: `Deferred / Resume later`.
- Ghi chú cho phiên làm việc kế tiếp:
  - Ưu tiên bắt đầu từ adapter read-only (`status/account/trade-history/logs`), sau đó mới mở các endpoint thao tác lệnh.

## 59) Rate-limit hardening + default paused startup (2026-02-28)

- Mục tiêu vận hành được chốt theo hướng an toàn (profile A): giảm tần suất gọi Boktoshi API để tránh Cloudflare 1015.
- Thay đổi runtime mặc định:
  - thêm biến env `STRATEGY_AUTO_START` (mặc định `false`), strategy khởi động ở trạng thái paused cho tới khi operator bấm Resume.
  - cập nhật `.env.example` để phản ánh cấu hình khởi động an toàn.
- Hardening MTC client (`BoktoshiBotModule/mtc_client.py`):
  - dùng `requests.Session()` + header mặc định ổn định (`Accept`, `User-Agent`).
  - nhận diện Cloudflare 1015 và map thành lỗi chuẩn `CF_1015`.
  - chuẩn hóa lỗi HTTP 429 thành `HTTP_429`.
  - trả lỗi `INVALID_RESPONSE` khi API trả non-JSON.
- Giảm call dư thừa ở bot loop (`BoktoshiBotModule/bot_runner.py`):
  - không fetch `positions` lại sau mỗi symbol trong vòng lặp strategy.
  - tách nhịp fetch theo trạng thái:
    - running: fetch interval >= 20s,
    - paused: fetch interval >= 60s,
    - history fetch interval 120s.
  - khi strategy paused: không chạy strategy open/close evaluation loop.
- Thêm backoff tự động khi gặp rate limit:
  - exponential backoff 30s -> 60s -> 120s -> ... (max 300s) cho các call account/positions/history.
  - có structured log `mtc_backoff_activated` để quan sát.
- Tối ưu polling frontend:
  - Dashboard: refresh từ 3s -> 10s, slow cache từ 15s -> 30s.
  - Manual page: positions/settings/strategies polling giảm còn 10s/30s/60s.
  - Strategy Summary: polling từ 5s -> 30s.
- Kết quả verify tại phiên này:
  - `python -m compileall BoktoshiBotModule app` pass.
  - `pytest -q tests/test_bot_runner_flows.py tests/test_system_metrics.py` pass (13 passed).

## 60) Navigation order + polling clarification (2026-02-28)

- Điều chỉnh thứ tự menu theo yêu cầu operator: `Position Management` được đưa lên trước `Boktoshi Trading Journal` ở toàn bộ trang chính.
- Các template đã cập nhật nav order:
  - `app/templates/index.html`
  - `app/templates/manual.html`
  - `app/templates/journal.html`
  - `app/templates/strategy_summary.html`
  - `app/templates/eth_chart.html`
  - `app/templates/aster_trading.html`
  - `app/templates/fredtrade_migration_report.html`
  - `app/templates/chatlog.html`
- Xác nhận nhịp cập nhật `uPnL History` trên Dashboard:
  - dashboard refresh vòng chính: mỗi `8s`;
  - dữ liệu slow lane (trade history / pnl history / signals / logs): cache TTL `20s`;
  - do đó `uPnL History` mặc định cập nhật tối đa mỗi khoảng `20s` (hoặc sớm hơn khi cache bị invalidate bởi thao tác refresh thủ công).

## 61) Claim open position từ unknown -> manual (2026-02-28)

- Vấn đề vận hành: có vị thế mở trên app Boktoshi nhưng không hiện ở bảng Manual/Strategy do ownership map local không chứa `positionId`.
- Đã xác minh runtime:
  - `items=1`, `manual=0`, `unknown=1` trước khi xử lý.
  - position thực tế: `DOGEUSDT LONG`, `positionId=mtc_430008ebb1d9ec20`.
- Đã xử lý không đổi UI:
  - claim trực tiếp bằng cách thêm `positionId` vào KV `manual_position_ids` trong DB runtime container.
- Kết quả sau claim qua `GET /api/open-positions`:
  - `items=1`, `manual=1`, `unknown=0`.
  - vị thế DOGE đã vào nhóm manual và có thể đóng/manage từ trang Position Management.

## 62) Dashboard manual force refresh button (2026-02-28)

- Đã thêm nút `Refresh Dashboard` đặt ngay trong cụm `Live` ở header dashboard (`app/templates/index.html`).
- UX nút theo yêu cầu:
  - nền cam,
  - chữ đậm (bold),
  - trạng thái disable + đổi text `Refreshing...` khi đang chạy.
- Hành vi khi bấm nút:
  - force refresh toàn bộ dữ liệu dashboard (status/account/open-positions/system metrics + history/pnl/signals/logs), không chờ TTL cache.
  - reset `slowCache.lastFetchedAt` để bắt buộc lấy dữ liệu mới nhất.
  - cố gắng gọi `POST /api/journal/refresh` trước khi refresh để dữ liệu finalized gần thời gian thực hơn.
- Tối ưu hiển thị:
  - `live-bar` cho phép wrap để nút mới không vỡ layout trên viewport nhỏ.

## 63) 4H_REGIME_SWITCH_V1 full rollout (2026-03-01)

- Implemented and integrated new strategy `4H_REGIME_SWITCH_V1` end-to-end as selectable runtime strategy.
- Strategy core (`BoktoshiBotModule/strategy.py`):
  - added deterministic indicator stack for regime logic:
    - `ATR(14)`, `ADX(14)`, `EMA200`, `RSI(14)`, Bollinger(20,2), Donchian(20/10), ATR slope.
  - added regime snapshot + entry/management evaluators:
    - `compute_regime_switch_snapshot(...)`
    - `evaluate_regime_switch_entry_long_4h(...)`
    - `evaluate_regime_switch_manage_long_4h(...)`
  - added overlay helper outputs:
    - Bollinger lines, regime markers, regime long-entry markers.
- Bot runtime integration (`BoktoshiBotModule/bot_runner.py`):
  - new strategy id constant: `4H_REGIME_SWITCH_V1` and strategy registry entry.
  - new persisted runtime state key: `regime_switch_state` (per slot `strategy:symbol`).
  - added 4H closed-candle gate, daily drawdown block, and cooldown bars after exits.
  - added dynamic risk-to-margin sizing conversion for regime entries (exchange payload remains `margin + leverage`).
  - added TREND/RANGE exit handling from strategy state machine via `_manage_regime_strategy_position(...)`.
  - updated `run_all` mode messaging to include all configured strategies.
- API + UI integration:
  - `/api/status` now exposes regime runtime metadata under `strategy.regime_runtime` when active.
  - `/api/strategy/overlay` now supports regime overlays:
    - `EMA200`, Bollinger bands, regime markers, regime snapshot payload.
  - `ASTER Chart` overlay status and markers updated for regime visualization.
  - `Strategy Summary` page updated with dedicated `4H Regime Switch V1` explanation block and runtime chips.
- Validation and regression:
  - added tests:
    - `tests/test_bot_runner_flows.py` (strategy listing/select + regime dry-run entry/state path)
    - `tests/test_strategy_overlay.py` (regime overlay contract)
  - test result: `25 passed`.
  - compile check: `python3 -m compileall app BoktoshiBotModule tests` passed.

## 64) 4H regime deep tuning phases 1-5 complete (2026-03-01)

- Created dedicated execution tracker file for this scope:
  - `Tunning4HRegimeStratery`
  - includes: plan, checklist, dedicated dev log, and phase pass/fail table.
- Phase 1 (Concentration lock) implemented:
  - hard caps for regime strategy:
    - max total strategy longs = `2`
    - max per symbol = `1`
  - same-candle multi-signal allocator now opens deterministic top-ranked candidates only.
- Phase 2 (Performance optimization) implemented:
  - added in-memory 4H regime market cache (`_regime_market_cache`) with short reuse window.
  - management and entry candidate flows now reuse the same cached snapshot path.
- Phase 3 (Concentration scoring) implemented:
  - added deterministic score model (`regime bias + ADX + ATR slope + ATR/close efficiency`).
  - allocator opens candidates by score order until slot cap is filled.
- Phase 4 (Tuning guards) implemented:
  - added volatility-shock skip guard using `atr14` vs `atr14_prev` multiplier.
  - preserved dynamic risk-to-margin sizing and existing cooldown/day-drawdown persistence.
- Phase 5 (Validation) completed:
  - compile check: `python3 -m compileall app BoktoshiBotModule tests` passed.
  - full test run: `pytest -q` passed (`27 passed`).
  - API smoke checks passed:
    - `GET /api/strategies`
    - `POST /api/strategy/select` (`4H_REGIME_SWITCH_V1`)
    - `GET /api/status`
    - `GET /api/strategy/overlay`
- Runtime stack confirmation:
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`
  - container `CatBoktoshiTradingBot-dev` remains running.

## 65) Regime tuning metrics surfaced to Dashboard (2026-03-01)

- Extended runtime observability for `4H_REGIME_SWITCH_V1` in `BoktoshiBotModule/bot_runner.py`:
  - added dedicated counters:
    - `cap_blocked_total`
    - `symbol_cap_blocked_total`
    - `volatility_shock_skipped_total`
    - `candidates_total`
    - `candidates_opened_total`
    - `candidates_rejected_total`
  - added derived metric: `open_rate`.
- Updated `GET /api/system/metrics` in `app/main.py`:
  - new payload section: `metrics.regime_tuning`.
- Updated Dashboard `System Health` panel (`app/templates/index.html`) to display regime-tuning counters and open-rate row.
- Added/updated tests:
  - `tests/test_system_metrics.py` now validates presence/shape of `metrics.regime_tuning`.
  - `tests/test_bot_runner_flows.py` adds checks for candidate open/reject counters and volatility-shock counter updates.
- Verification:
  - `python3 -m compileall app BoktoshiBotModule tests` passed.
  - `pytest -q` passed (`28 passed`).
  - API smoke confirms `/api/system/metrics` includes expected `regime_tuning` keys.

## 66) Dashboard anti-rate toggle + manual-only PnL history fetch (2026-03-01)

- Updated Dashboard controls in `app/templates/index.html`:
  - added new toggle button next to `Refresh Dashboard`:
    - default label: `Toggle Anti Rate Limit Profit`
    - active label: `Toggle To Normal Running Profile`
- Added two refresh profiles on client side:
  - Normal profile:
    - core polling every `8s`
    - slow-lane TTL `20s`
    - slow-lane auto enabled
  - Anti-rate profile:
    - core polling every `30s`
    - slow-lane TTL `120s`
    - slow-lane auto disabled
- Implemented manual-only `PnL History` data fetch:
  - `/api/pnl-history` is no longer auto-fetched by timer.
  - `/api/pnl-history` is fetched only when clicking `Refresh Dashboard`.
  - `Refresh Finalized PnL` and `Clear Stale Pending Queue` no longer trigger `pnl-history` fetch.
- Profile mode is persisted in `localStorage` (`dashboard_profile_mode`) and reapplied on reload.
- Live status text now shows active profile label to avoid operator confusion.

## 67) Roadmap closure: Phase C persisted metadata + API/concurrency tests (2026-03-01)

- Completed remaining roadmap gaps for Phase C and Phase D.

- Phase C (Data Quality) completed with persisted journal metadata:
  - `app/storage.py`
    - added schema migration-on-startup in `init_db(...)`:
      - new `journal_entries` columns:
        - `finalization_state` (`PENDING|ESTIMATED|FINALIZED`)
        - `estimated_source` (`none|snapshot|market_hint|formula`)
      - automatic backfill for existing rows with missing/invalid metadata.
    - updated upsert/replace flows to persist both fields on write.
    - updated read model (`get_journal_entries`) to return both persisted fields.
  - `app/main.py`
    - `_decorate_journal_row(...)` now prefers persisted `finalization_state/estimated_source` and only falls back to runtime inference when missing.
  - added migration utility script:
    - `scripts/migrate_journal_finalization_fields.py`
    - purpose: manual re-run/verification of metadata normalization outside startup path.

- Phase A typed payload schemas finalized:
  - added `app/schemas.py` with typed structures:
    - `CloseRecord`
    - `IntegrityReport`
    - `MetricsPayload`
  - wired type hints in `app/main.py` for close snapshot and metrics/integrity flows.

- Phase D test additions (API-level + concurrency):
  - new file `tests/test_journal_api_sync.py`:
    - verifies `/api/journal/refresh` behavior (sync trigger + pending count result)
    - verifies `/api/system/integrity-report` contract path
    - verifies journal sync trigger/lock concurrency behavior
  - updated `tests/test_journal_storage_dedupe.py` to assert persisted finalization fields.

- Roadmap state updated:
  - `NEXT_ROADMAP.md` marked `COMPLETED (2026-03-01)` with all items checked.
  - `CHECKLIST_CAI_THIEN_HE_THONG.md` execution log updated with roadmap closure note.

- Validation:
  - `python3 -m compileall app tests scripts` passed.
  - `pytest -q` passed (`32 passed`).
  - dev stack restart: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d` (container running).

- Note:
  - running `scripts/migrate_journal_finalization_fields.py` against local mounted db in this session returned `sqlite3.OperationalError: attempt to write a readonly database`; startup auto-migration path remains active in app runtime where DB is writable.

## 68) Hotfix: server startup failure after roadmap typed schemas (2026-03-01)

- Incident:
  - user reported server appears down.
  - container logs showed FastAPI/Pydantic crash on startup route-model build:
    - `PydanticUserError: Please use typing_extensions.TypedDict instead of typing.TypedDict on Python < 3.12`.
- Root cause:
  - `app/schemas.py` imported `TypedDict` from `typing` while runtime image uses Python 3.11.
- Fix:
  - changed import to `from typing_extensions import TypedDict` in `app/schemas.py`.
- Verification:
  - `docker compose ... up -d` keeps service running.
  - `GET /api/status` returns `200`.
  - container logs show successful startup and normal API traffic after reload.

## 69) Chatlog Vietnamese diacritics normalization (2026-03-01)

- User feedback: recent entries in `chatlog` were written in Vietnamese without diacritics.
- Updated `app/templates/chatlog.html` to normalize all newly added no-diacritic sections into proper Vietnamese with diacritics.
- Scope:
  - corrected both user and assistant messages in recent strategy/roadmap/incident blocks.
  - preserved original technical meaning and HTML structure.
- Result:
  - `chatlog` now displays Vietnamese text with proper accents consistently for recent entries.

## 70) Manual position limit increased to 5 (2026-03-02)

- Updated manual runtime guard in `BoktoshiBotModule/bot_runner.py`:
  - `MANUAL_MAX_POSITIONS` changed from `3` to `5`.
  - Manual force-open flow now allows up to 5 concurrent manual-owned positions before returning limit guard.
- Updated local agent project constraints in `AGENTS.md` to match runtime behavior:
  - manual ownership policy now states up to 5 manual-owned positions.
- Added regression test in `tests/test_bot_runner_flows.py`:
  - `test_manual_force_open_rejects_when_reaching_manual_limit_five`
  - verifies manual open is rejected with `limit reached (5)` once five manual IDs are present.

## 71) Manual stacking per symbol + per-order risk overrides (2026-03-02)

- Manual-only behavior update for same pair handling:
  - `BoktoshiBotModule/bot_runner.py`
    - removed manual guard that blocked opening another position on the same symbol/side.
    - kept hedge guard unchanged: opposite side on same symbol is still rejected.
  - Result: manual flow can now open multiple independent positions on the same pair (same side), each tracked by its own `positionId`.

- Per-order manual settings support added (without changing global Bot Settings):
  - `BoktoshiBotModule/bot_runner.py`
    - added `_resolve_manual_open_settings(...)` to parse safe overrides for:
      - `margin_boks`
      - `leverage`
      - `sl_percent` / `sl_capital_pct`
      - `tp_percent` / `tp_capital_pct`
    - `manual_force_open[_long|_short]` now accepts `manual_settings` and applies those values only to that order.
  - `app/main.py`
    - `/api/manual/force-open-long` and `/api/manual/force-open-short` now accept optional payload overrides (`margin_boks`, `leverage`, `sl_percent`, `tp_percent`) and forward them to runner.
  - `app/templates/manual.html`
    - Manual Trade Panel now includes optional per-order inputs for margin/leverage/SL/TP.
    - if left empty, request uses current global Bot Settings.

- Regression/behavior tests updated in `tests/test_bot_runner_flows.py`:
  - `test_manual_force_open_long_rejects_if_manual_short_same_symbol_exists` now asserts hedge-disabled message.
  - added `test_manual_force_open_long_allows_multiple_same_symbol_same_side`.
  - added `test_manual_force_open_uses_per_order_settings_override`.

## 72) AsterTrading split-plan execution + AsterSimpleTrading rollout (2026-03-04)

- Aster module structure expanded for isolated ASTER scope:
  - added `AsterTradingModule/pairs.py` (shared whitelist pairs aligned with Manual symbols).
  - added dedicated ASTER docs/tracker files:
    - `AsterTradingModule/ROADMAP.md`
    - `AsterTradingModule/CHECKLIST.md`
- `AsterTradingModule/service.py` was upgraded for multi-symbol ASTER operations:
  - symbol is now resolved from payload/query (not fixed ETH-only at service level).
  - supports pair dropdown flow with whitelist validation.
  - preview now supports margin-first input (`margin_usdt * leverage`) and auto `1%` stop-loss mode from account equity.
  - added close-all positions capability for fast emergency/manual flatten.
  - open positions/open orders endpoints now support full-list mode (`ALL`) for cross-page sync.
- API layer updates in `app/main.py`:
  - added page route: `GET /aster-simple-trading`.
  - added endpoint: `GET /api/aster-trading/symbols`.
  - added endpoint: `POST /api/aster-trading/close-all-positions`.
  - updated existing ASTER endpoints to accept optional `symbol` query where relevant.
- `AsterTrading` UI (`app/templates/aster_trading.html`) fully refactored toward ASTER-like dark layout:
  - removed `Stop Limit` tab.
  - removed `Time in force` field.
  - pair is now a dropdown from backend symbol list.
  - order mode now switches `Market` vs `Limit` behavior explicitly.
  - added `1% Stoploss` auto toggle + SL reference note.
  - account panel switched to manual refresh only.
  - open positions/open orders kept realtime with 3s refresh.
- New page `AsterSimpleTrading` (`app/templates/aster_simple_trading.html`):
  - `Position Settings` card (rename from bot settings concept for this page scope).
  - quick open LONG/SHORT panel.
  - close controls include both:
    - `Close Selected Symbol`
    - `Close All Positions`
  - account snapshot refresh button (manual fetch only).
  - realtime positions/orders panel (3s), shared data source with AsterTrading page.
- Navigation updates:
  - added `AsterSimpleTrading` nav link to primary templates (`index`, `manual`, `journal`, `strategy_summary`, `eth_chart`, `fredtrade_migration_report`, `chatlog`, and both ASTER pages).
- ASTER service tests added:
  - new file: `tests/test_aster_trading_service.py`
  - covers preview sizing behavior, auto 1% stop-loss path, close-all dry-run, and open-position filtering.
- Verification:
  - `python3 -m compileall app AsterTradingModule tests` passed.
  - `pytest -q` passed (`39 passed`).
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d` executed; container `CatBoktoshiTradingBot-dev` running.
  - smoke check passed:
    - `/aster-trading` -> 200
  - `/aster-simple-trading` -> 200
  - `/api/aster-trading/symbols` -> 200

## 73) AsterTrading test-hardening pass complete (2026-03-04)

- Continued Phase 5 hardening for ASTER scope with additional automated coverage.
- Added API-level regression tests:
  - new file `tests/test_aster_trading_api.py`
  - validates:
    - symbols endpoint payload contract (`/api/aster-trading/symbols`)
    - close-all endpoint behavior path (`/api/aster-trading/close-all-positions`)
    - symbol passthrough for open positions/open orders/history endpoints.
- Added UI contract tests for ASTER pages:
  - new file `tests/test_aster_trading_templates.py`
  - validates:
    - `AsterTrading` template no longer contains `Stop Limit` and `Time In Force` controls.
    - `1% Stoploss` auto control + SL reference section are present.
    - `AsterSimpleTrading` template contains quick close actions and `Position Settings` block.
- Updated ASTER trackers:
  - `AsterTradingModule/CHECKLIST.md` marks API/UI test items completed.
  - `AsterTradingModule/ROADMAP.md` marks Phase 5 API/UI test items completed.
- Verification:
  - `python3 -m compileall app AsterTradingModule tests` passed.
  - `pytest -q` passed (`47 passed`).
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d` run; container stays running.
  - smoke checks:
    - `/aster-trading` -> 200
    - `/aster-simple-trading` -> 200
    - `/api/aster-trading/symbols` -> 200

## 74) Aster operator UX pass: readable response + pair-reactive overview + simple MARKET-only (2026-03-04)

- `AsterTrading` UX refinements in `app/templates/aster_trading.html`:
  - `Latest Response` now has human-readable summary rows (status, pair, side/type, entry/mark, qty/notional, margin/risk, SL/TP, warnings/message).
  - added raw debug toggle button (`Show Raw JSON` / `Hide Raw JSON`) without losing operator-friendly view.
  - fixed reactive behavior on pair/form changes:
    - preview + quick stat boxes auto-refresh with debounce.
    - symbol change immediately refreshes live panel context.
  - live panel now keeps **overview all pairs** and highlights rows for selected pair.
  - added selected-pair counters for both open positions and open orders.
- `AsterSimpleTrading` simplification in `app/templates/aster_simple_trading.html`:
  - removed `Order Type` and `Limit Price` controls.
  - quick open flow is now fixed `MARKET` by design.
  - added inline note clarifying `1% Stoploss Auto` uses 1% of account equity as risk target.
- Test updates:
  - `tests/test_aster_trading_templates.py` extended to verify:
    - structured response controls exist,
    - selected-row highlight support exists,
    - simple page no longer includes `Order Type` and `Limit Price` controls.
- Validation:
  - `python3 -m compileall app AsterTradingModule tests` passed.
  - `pytest -q -rA` passed (all tests green).
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d` run; dev container stays running.
  - smoke checks passed:
    - `/aster-trading` -> 200
    - `/aster-simple-trading` -> 200
    - `/api/aster-trading/open-positions` -> 200
    - `/api/aster-trading/open-orders` -> 200

## 75) Aster auth diagnostics + actionable API error hints (2026-03-04)

- Added auth diagnostics support for ASTER connectivity:
  - `AsterTradingModule/service.py`
    - new method `get_connection_status()` performs signed account check and returns structured status.
    - maps common auth failures (invalid key / missing futures permission / IP whitelist) into operator hints.
  - `app/main.py`
    - new endpoint `GET /api/aster-trading/connection-check`.
- Updated `AsterTrading` UI (`app/templates/aster_trading.html`):
  - added `Check API Auth` button in Account panel.
  - added `connection-box` status area to display success/failure and troubleshooting hints.
  - response summary now adds explicit hint row when API error message includes key/permission issues.
- API smoke in current environment:
  - `/api/aster-trading/connection-check` returned `ok: true`.
  - `/api/aster-trading/account-overview` returned 200.
  - note: if operator sees `Invalid API-key, IP, or permissions for action`, this points to exchange-side credential scope, not UI parser issue.
- Tests/docs updates:
  - `tests/test_aster_trading_api.py` adds coverage for connection-check endpoint.
  - `tests/test_aster_trading_templates.py` validates `Check API Auth` control exists.
  - `README.md` endpoint list includes `/api/aster-trading/connection-check`.
  - ASTER trackers updated (`AsterTradingModule/ROADMAP.md`, `AsterTradingModule/CHECKLIST.md`).
- Validation:
  - `python3 -m compileall app AsterTradingModule tests` passed.
  - `pytest -q` passed (`49 passed`).
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d` container restarted and running.
  - smoke checks:
    - `/aster-trading` -> 200
    - `/aster-simple-trading` -> 200
    - `/api/aster-trading/connection-check` -> 200

## 76) AsterSimpleTrading Action Result parsing (2026-03-04)

- Updated `app/templates/aster_simple_trading.html`:
  - `Action Result` now mirrors operator-friendly format (structured summary rows) instead of raw JSON-only view.
  - added `Show Raw JSON` toggle for debug mode.
  - summary includes key fields: status, pair, side/type, entry/mark, qty/notional, margin/risk, SL/TP, warnings/message.
- Updated UI tests:
  - `tests/test_aster_trading_templates.py` now validates structured response controls on `AsterSimpleTrading`.
- Verification:
  - `python3 -m compileall app AsterTradingModule tests` passed.
  - `pytest -q` passed (`49 passed`).
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d` confirms dev container running.
  - smoke check `/aster-simple-trading` -> 200.

## 77) Final ASTER visual polish + container recreate support (2026-03-04)

- Container/env operation:
  - executed full recreate to reload env values on request:
    - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --force-recreate`
  - service restarted successfully.
- `AsterTrading` visual polish (`app/templates/aster_trading.html`):
  - refined tabs/typography sizing for closer ASTER look.
  - added side chips (`LONG`/`SHORT`) with color-coded style.
  - improved selected pair row highlight with left accent border.
  - response summary grid tuned for desktop readability.
- `AsterSimpleTrading` visual polish (`app/templates/aster_simple_trading.html`):
  - action-result summary now shares structured panel style and raw JSON toggle.
  - added long/short chips and selected-row highlight in realtime tables.
  - pair change now triggers immediate preview + realtime panel refresh.
- Tests updated:
  - `tests/test_aster_trading_templates.py` assertions still pass with structured controls.
- Verification:
  - `python3 -m compileall app AsterTradingModule tests` passed.
  - `pytest -q` passed (`49 passed`).
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d` confirms running container.
  - smoke checks:
    - `/aster-trading` -> 200
    - `/aster-simple-trading` -> 200
    - `/api/aster-trading/connection-check` -> 200

## 78) Global theme `Aster` added (default kept unchanged) (2026-03-04)

- Theme engine update:
  - `app/static/theme.js`
    - added new theme key: `aster`.
    - theme selector now shows: `Default`, `Aster`, `Pinky`, `Light Green`.
  - startup fallback remains `default` (no forced switch).
- Global style tokens update:
  - `app/static/app.css`
    - added `html[data-theme="aster"]` palette for darker ASTER-like look.
    - added theme-specific typography/spacing refinements for headers/cards/nav.
- ASTER pages wiring:
  - `app/templates/aster_trading.html`
  - `app/templates/aster_simple_trading.html`
  - both pages now load `/static/theme.js` and include local `theme-dock` styling so switcher appears and works there too.
  - both pages include local `html[data-theme="aster"]` variable overrides to preserve their custom layout while still following global theme selection.
- Test updates:
  - `tests/test_aster_trading_templates.py`
    - added assertions for `/static/theme.js` usage in both ASTER pages.
    - added assertion that `theme.js` contains `aster` option.
- Verification:
  - `python3 -m compileall app AsterTradingModule tests` passed.
  - `pytest -q` passed (`50 passed`).
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d` running.
  - smoke checks passed:
    - `/` -> 200
    - `/manual` -> 200
    - `/aster-trading` -> 200
    - `/aster-simple-trading` -> 200

## 79) Unknown positions management + Aster auto-auth/account bootstrap (2026-03-04)

- Root issue confirmed from operator feedback:
  - account-level `unknown_positions` were included in Dashboard uPnL/open count,
  - but `Position Management` only exposed Strategy/Manual owned slots, so unknown items were not manageable in UI.
- Backend upgrades:
  - `BoktoshiBotModule/bot_runner.py`
    - added `close_unknown_position(position_id, comment)`.
    - added `close_all_unknown_positions(comment)`.
    - both flows classify unknown positions from latest `/positions` snapshot, then close by `positionId` (with DRY_RUN support, guard checks, and structured trade logs).
  - `app/main.py`
    - added `POST /api/manual/close-unknown-position`.
    - added `POST /api/manual/close-all-unknown-positions`.
- UI upgrades in `app/templates/manual.html`:
  - new card: `CLOSE UNKNOWN POSITION`.
  - new selector: `unknown-close-position` populated from `data.unknown_positions`.
  - new actions:
    - `Close Unknown Position`
    - `Close All Unknown Positions`
  - `Current Open Positions` now has explicit third section for Unknown Position table.
- Aster page bootstrap change:
  - `app/templates/aster_trading.html`
    - on page load, run `checkConnection()` and `refreshAccount()` automatically one time after symbols/preview bootstrap.
    - keeps manual Refresh button behavior for subsequent updates.
- Test additions:
  - `tests/test_bot_runner_flows.py`
    - added unknown close single/all behavior tests.
  - `tests/test_manual_unknown_api.py`
    - added route passthrough tests for new manual unknown endpoints.
  - `tests/test_manual_template_unknown.py`
    - asserts unknown management UI controls are present.
  - `tests/test_aster_trading_templates.py`
    - asserts load-init includes `Promise.allSettled([checkConnection(), refreshAccount()])`.
- Verification:
  - `python3 -m compileall app BoktoshiBotModule tests` passed.
  - `pytest -q` passed (`55 passed`).
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d` running (`CatBoktoshiTradingBot-dev`).
  - smoke checks:
    - `/manual` -> 200
    - `/aster-trading` -> 200
    - `/api/open-positions` -> 200
    - `/api/manual/close-all-unknown-positions` -> 200
  - note: smoke POST to `close-all-unknown-positions` executed against live data and returned closed ids for current unknown positions.
