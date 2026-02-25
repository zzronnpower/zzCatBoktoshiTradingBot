# Next Roadmap (Post-Checklist)

## Goal
After finishing the core stabilization checklist, this roadmap defines the next quality and scalability cycle.

## Phase A - Architecture Cleanup
- Extract Journal sync/finalize logic from `app/main.py` into a dedicated service module.
- Separate read models (`dashboard`, `journal`, `metrics`) from write/sync pipelines.
- Introduce typed payload schemas for close records and integrity reports.

## Phase B - UX and Operations
- Add a small System Health panel on Dashboard:
  - API latency (avg/max)
  - pending finalize count
  - last journal sync duration
  - remote history fetch error count
- Add a manual action to clear stale pending-finalize queue entries.
- Add quick filters for Journal (source/pending/recovered).

## Phase C - Data Quality
- Add explicit `finalization_state` field (`PENDING`, `ESTIMATED`, `FINALIZED`).
- Add persisted marker for `estimated_source` (`snapshot`, `market_hint`, `formula`).
- Add data migration script to normalize old rows with missing source metadata.

## Phase D - Test and CI
- Add API-level tests for:
  - `/api/system/metrics`
  - `/api/system/integrity-report`
  - `/api/journal/refresh`
- Add concurrency tests for sync trigger and lock behavior.
- Add CI workflow to run pytest and fail on regression.

## Phase E - Performance Targets
- Keep `GET /api/trade-history` p95 < 40 ms (warm path).
- Keep `GET /api/journal` p95 < 25 ms (page_size 20).
- Keep force refresh under 5s for normal network conditions.

## Suggested Order
1) Phase A
2) Phase B
3) Phase C
4) Phase D
5) Phase E tuning pass
