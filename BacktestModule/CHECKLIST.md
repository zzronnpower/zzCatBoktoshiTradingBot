# Backtest Module Checklist

## Phase 1 - SOL Binance Futures MVP

- [x] Create module roadmap/checklist docs.
- [x] Add backtest service to parse Freqtrade result and build UI payload.
- [x] Add backend route `GET /backtest`.
- [x] Add API `GET /api/backtest/latest`.
- [x] Build `app/templates/backtest.html` with KPI + equity + drawdown + trades.
- [x] Add Backtest nav link to major templates.
- [x] Generate real SOL Binance Futures backtest result from Freqtrade.
- [x] Export normalized artifact to `BacktestModule/artifacts/latest.json`.
- [x] Smoke verify `/backtest` and `/api/backtest/latest`.

## Next (after MVP acceptance)

- [x] Add compare mode: baseline vs candidate.
- [x] Add run history list and side-by-side KPI delta.
- [x] Add timerange/timeframe controls on UI.
- [x] Add strategy selector (MA50/EMA/REGIME).
- [x] Add pair selector and quick timerange presets (3M/6M/12M/YTD).
- [x] Add `Run New Backtest` action from `/backtest` UI (API-triggered).
