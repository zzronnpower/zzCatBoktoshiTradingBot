# AsterTrading Checklist

Status date: 2026-05-01

## Current Batch

- [x] Add multi-symbol support for ASTER trading service.
- [x] Add `/aster-simple-trading` page route.
- [x] Add `/api/aster-trading/symbols` endpoint.
- [x] Add `/api/aster-trading/close-all-positions` endpoint.
- [x] Update existing ASTER endpoints to accept optional `symbol` query/payload.
- [x] Redesign `app/templates/aster_trading.html` to ASTER-like dark theme.
- [x] Remove Stop Limit tab and Time in Force from AsterTrading UI.
- [x] Add pair dropdown and Market/Limit conditional UI behavior.
- [x] Add `1% Stoploss` auto mode and SL reference output.
- [x] Add AsterSimpleTrading page with Position Settings + quick open/close actions.
- [x] Keep account panel manual-refresh only.
- [x] Keep open positions/open orders in realtime polling mode (3s).
- [x] Add nav link for AsterSimpleTrading in key templates.
- [x] Add API tests for `/api/aster-trading/*` routes.
- [x] Add browser-level UI tests for Aster pages.
- [x] Parse latest response into human-readable operator summary view.
- [x] Add raw JSON toggle in response panel.
- [x] Auto refresh preview when pair/form inputs change.
- [x] Keep overview tables for all pairs but highlight selected pair rows.
- [x] Remove `Order Type` and `Limit Price` from `AsterSimpleTrading` (MARKET-only flow).
- [x] Parse `AsterSimpleTrading` Action Result into structured readable summary.
- [x] Add raw JSON toggle for `AsterSimpleTrading` Action Result.
- [x] Add ASTER auth diagnostics endpoint and UI check button.
- [x] Show operator hints when API key/permission/IP errors are detected.
- [x] Final visual polish against latest operator screenshots.
- [x] Add global `Aster` theme option in `theme.js` while keeping `Default` as startup theme.
- [x] Add `aster` design tokens and typography/spacing adjustments in `app/static/app.css`.
- [x] Enable theme switcher on `AsterTrading` and `AsterSimpleTrading` pages.
- [x] Add tests validating `aster` option presence and theme script wiring.
- [x] Migrate ASTER auth/execution to Pro API V3 (`user/signer/nonce/EIP-712`) and remove legacy API key signing flow.
- [x] Switch AsterTrading symbol source to dynamic USDT PERPETUAL list from exchangeInfo.
- [x] Add dedicated account overview card on AsterSimpleTrading with auto refresh.
- [x] Add account panel risk UX: PnL color, margin ratio badge, 5-snapshot mini-history.
- [x] Add stoploss auto 1% toggle and TP RR mode controls for AsterSimpleTrading.
- [x] Sync estimate line with backend preview values (SL/TP prices) and fallback note handling.
- [x] Emphasize estimate metrics (`Est. SL Risk`, `Est. TP`) with color+bold.
- [x] Gate TP RR mode by explicit checkbox before `Take Profit Mode`.
- [x] Split active tab accents: AsterTrading (yellow), AsterSimpleTrading (orange).
- [x] Add `SL Price % from entry price` info line under estimate summary.
- [x] Highlight `Preview ... Entry | Qty | Margin | SL` line in yellow + bold for quick readability.
- [x] Show `Estimated Entry Price` alongside `SL Price % from entry price` in AsterSimpleTrading.
- [x] Split `Estimated Entry Price` and `SL Price % from entry price` into two lines; highlight entry price in dark-gold bold.
- [x] Add `Estimate Side` selector so estimate preview can switch LONG/SHORT direction.
- [x] Fix estimate sync to respect selected estimate side (remove hardcoded BUY).
- [x] Ensure `OPEN LONG` always sends BUY regardless of estimate side selector.
- [x] Keep MANUAL TRADE PANEL `Preview ... | SL ...` line synced with estimate preview updates.
- [x] Remove static whitelist filtering from open positions/open orders list APIs.
- [x] Add order submit in-flight guard and `Submitting...` button lock for OPEN LONG/SHORT.
- [x] Add explicit order submit status feedback (idle/submitting/success/failed).
- [x] Include symbol+side context (and orderId when available) in submit status text.
- [x] Add settings-mode dropdown in AsterSimpleTrading (`Normal Flow Settings` / `Manual SL, Auto the Rest`).
- [x] Add Manual-SL mode inputs: manual SL price + risk% on total capital (max 5%).
- [x] Wire payload `settings_mode` and manual-SL fields to backend preview/place-order flow.
- [x] Add backend preview branch for `manual_sl_auto_rest` risk-based sizing.
- [x] In Manual-SL mode, auto-compute leverage in x3..x6 using remaining-slot budget.
- [x] Remove manual leverage input from Manual-SL UI mode and show computed leverage summary.
- [x] Color-code open positions `uPnL` in AsterSimpleTrading (green profit / red loss).
- [x] Fix open-orders table semantics for SL/TP closePosition orders (trigger price + qty mode rendering).
- [x] Close dropdown now sourced from realtime open positions only, with pair+ID labels.
- [x] Close dropdown label updated to `PAIR | SIDE | QTY | uPnL` format.
- [x] Add new AsterTradingHistory tab/page for closed trades.
- [x] Add `/api/aster-trading/history` endpoint (income-based closed trades).
- [x] Add cumulative realized PnL curve visualization.

## Validation Checklist

- [x] `python3 -m compileall app AsterTradingModule tests`
- [ ] `pytest -q` (tooling missing in runtime image during this batch)
- [x] `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`
- [x] Smoke check `/aster-trading` and `/aster-simple-trading`
