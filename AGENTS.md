# AGENTS

## Primary Agent Profile

- Name: OpenCode Assistant
- Role: Full-stack coding agent for `zzCatBoktoshiTradingBot`
- Working style: Read current project state first, implement directly, keep bot safe-first for trading actions
- Languages: Python (FastAPI), HTML/CSS/JavaScript, SQL (SQLite)
- Trading scope in this project:
  - Bot execution: Boktoshi MTC API
  - Market/chart data: ASTER-only for ETH chart UI, Hyperliquid for strategy candles (current strategy path)

## Mission in this Repository

- Maintain and improve the multi-symbol long/short trading bot operations (strategy and manual controls).
- Keep UX readable for non-technical operation.
- Preserve safety controls (DRY_RUN, risk checks, max positions, rate limiting).
- Keep docs and logs current so future sessions can continue quickly.

## Non-Negotiable Project Rules

- Strategy scope:
  - Supported strategy symbols are `BTCUSDT`, `ETHUSDT`, `SOLUSDT`.
  - Strategy mode can run single strategy or all enabled strategies simultaneously.
- Position ownership model:
  - Strategy: tracked by strategy slot map (`strategy_position_ids`) and can include multiple strategy-owned positions across supported symbols.
  - Manual: allow up to 3 manual-owned positions from approved symbol whitelist.
- Default execution safety:
  - Use `DRY_RUN=true` until explicitly switched off.
  - Never remove core risk guards without user request.
- Manual controls must remain available even when strategy is paused.
- All major changes should be reflected in:
  - `app/templates/chatlog.html`
  - `PROJECT_LOG.md`
- Auto-maintenance rule:
  - After every coding task, update both `PROJECT_LOG.md` and `app/templates/chatlog.html` automatically.
  - Do not wait for user reminder to update logs/history.
- Auto-run stack rule:
  - After finishing code changes, automatically run the dev stack without asking user confirmation:
    - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`
  - Then report stack status in the reply.

## Current System Capabilities

- Dashboard with account, positions, trades, pnl history, signals, logs.
- Position Management page (`/manual`):
  - Bot Settings editor (margin, leverage, SL, TP)
  - Manual Trade Panel:
    - Force open manual LONG/SHORT for allowed symbols
    - Close single manual-owned position
    - Close all manual-owned positions
  - Strategy Control:
    - Select strategy / run all strategies
    - Pause/Resume strategy engine
  - Strategy close controls:
    - Close selected strategy-owned position
    - Close all strategy-owned positions
- ETH Chart page (ASTER-only):
  - Candlestick + volume
  - Timeframes
  - Stats strip
  - Orderbook + spread

## API and Runtime Landmarks

- App entry: `app/main.py`
- Bot loop and trade logic: `BoktoshiBotModule/bot_runner.py`
- MTC client: `app/mtc_client.py`
- ASTER market data client: `app/aster_client.py`
- DB utilities: `app/storage.py`
- Strategy logic: `app/strategy.py`
- Risk calculations: `app/risk.py`
- UI pages:
  - Dashboard: `app/templates/index.html`
  - Manual: `app/templates/manual.html`
  - ETH chart: `app/templates/eth_chart.html`
  - Chat log: `app/templates/chatlog.html`

## How to Resume Work Quickly

1. Read `PROJECT_LOG.md` first (latest architecture + milestones + pending tasks).
2. Read `app/templates/chatlog.html` for user intent and conversation history.
3. Run service and smoke check:
   - `docker compose up --build -d`
   - Open `/`, `/manual`, `/aster-chart`, `/chatlog`
4. Validate current mode:
   - Check `DRY_RUN` in `.env`
   - Check `/api/status` for `strategy_state`

## Notes for Future Agents

- Keep updates incremental and observable.
- Prefer resilience over fragile "pixel-perfect" copies of external exchanges.
- When adding features, include:
  - Endpoint/API changes
  - UI changes
  - Log/monitoring impact
  - Update to `PROJECT_LOG.md`
- Keep Boktoshi code grouped under `BoktoshiBotModule/`; ASTER futures module stays under `AsterTradingModule/`.

## High-Use Endpoints (Current)

- Strategy control:
  - `POST /api/strategy/select`
  - `POST /api/strategy/run-all`
- Manual position actions:
  - `POST /api/manual/force-open-long`
  - `POST /api/manual/force-open-short`
  - `POST /api/manual/close-position`
  - `POST /api/manual/close-all-positions`
- Strategy position actions:
  - `POST /api/manual/close-strategy-position` (supports optional `position_id`)
  - `POST /api/manual/close-all-strategy-positions`
