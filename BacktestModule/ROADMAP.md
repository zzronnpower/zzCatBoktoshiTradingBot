# Backtest Module Roadmap

## Scope

- Pair: `SOL/USDT:USDT`
- Exchange: `Binance Futures`
- Strategy (phase 1): `MA50_4H_CROSSUP_3C_LONG_ONLY`

## Delivery Phases

1. Data pipeline and first backtest run
2. Backtest artifact normalization for UI/API
3. Backtest page (`/backtest`) with KPI + charts + trade table
4. API integration and nav rollout across existing pages
5. Compare mode (baseline vs candidate)
6. Timerange/timeframe controls
7. Additional strategy slots (EMA / Regime)

## Progress Log

- 2026-03-08: Initialized module roadmap and checklist.
- 2026-03-08: Added backtest service and `/api/backtest/latest` endpoint.
- 2026-03-08: Added `/backtest` page and nav links across UI templates.
- 2026-03-08: Started SOL Binance Futures backtest artifact pipeline.
- 2026-03-08: Completed first SOL backtest run (`88 trades`, `-7.63 USDT`, `PF 0.93`) and published `BacktestModule/artifacts/latest.json`.
- 2026-03-08: Added standalone artifact build script for repeat runs (`scripts/build_backtest_artifact.py`).
- 2026-03-08: Added compare API + UI (`/api/backtest/runs`, `/api/backtest/compare`) with baseline vs candidate KPI delta and dual-line equity/drawdown charts.
- 2026-03-08: Added run snapshot storage in `BacktestModule/artifacts/runs/` and generated first two runs:
  - baseline (`BoktoshiMa50SolStrategy`)
  - candidate (`BoktoshiMa50SolCandidateStrategy`)
- 2026-03-08: Added timerange/timeframe/strategy/text filters to runs list and wired filter controls in `/backtest` UI.
- 2026-03-08: Added strategy selector module on Backtest page (preset families MA50/EMA/REGIME + dynamic strategy names from artifacts via `/api/backtest/strategies`).
- 2026-03-08: Added pair selector and timerange quick presets (3M/6M/12M/YTD/Clear) with dynamic pair list endpoint (`/api/backtest/pairs`).
- 2026-03-08: Added API-triggered run workflow from Backtest page (`POST /api/backtest/run`) with Freqtrade pipeline execution and automatic artifact publish.
