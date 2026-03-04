# AsterTrading Checklist

Status date: 2026-03-04

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

## Validation Checklist

- [x] `python3 -m compileall app AsterTradingModule tests`
- [x] `pytest -q`
- [x] `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`
- [x] Smoke check `/aster-trading` and `/aster-simple-trading`
