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

- Maintain and improve the ETHUSDT long-only trading bot.
- Keep UX readable for non-technical operation.
- Preserve safety controls (DRY_RUN, risk checks, max positions, rate limiting).
- Keep docs and logs current so future sessions can continue quickly.

## Non-Negotiable Project Rules

- Trading pair for strategy: ETHUSDT only.
- Position ownership model:
  - Allow up to 2 concurrent ETHUSDT LONG positions total
  - 1 strategy-owned + 1 manual-owned
- Default execution safety:
  - Use `DRY_RUN=true` until explicitly switched off.
  - Never remove core risk guards without user request.
- Manual controls must remain available even when strategy is paused.
- All major changes should be reflected in:
  - `app/templates/chatlog.html`
  - `PROJECT_LOG.md`

## Current System Capabilities

- Dashboard with account, positions, trades, pnl history, signals, logs.
- Manual trade page:
  - Force open LONG ETHUSDT
  - Close manual-owned ETHUSDT position
  - Close strategy-owned ETHUSDT position
  - Pause/Resume strategy engine
- ETH Chart page (ASTER-only):
  - Candlestick + volume
  - Timeframes
  - Stats strip
  - Orderbook + spread

## API and Runtime Landmarks

- App entry: `app/main.py`
- Bot loop and trade logic: `app/bot_runner.py`
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
   - Open `/`, `/manual`, `/eth-chart`, `/chatlog`
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
