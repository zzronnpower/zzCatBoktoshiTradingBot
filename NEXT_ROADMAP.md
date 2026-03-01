# Next Roadmap (Post-Checklist)

Status: COMPLETED (2026-03-01)

## Goal
After finishing the core stabilization checklist, this roadmap defines the next quality and scalability cycle.

## Phase A - Architecture Cleanup
- [x] Extract Journal sync/finalize logic from `app/main.py` into a dedicated service module.
- [x] Separate read models (`dashboard`, `journal`, `metrics`) from write/sync pipelines.
- [x] Introduce typed payload schemas for close records and integrity reports.

## Phase B - UX and Operations
- [x] Add a small System Health panel on Dashboard:
  - API latency (avg/max)
  - pending finalize count
  - last journal sync duration
  - remote history fetch error count
- [x] Add a manual action to clear stale pending-finalize queue entries.
- [x] Add quick filters for Journal (source/pending/recovered).

## Phase C - Data Quality
- [x] Add explicit `finalization_state` field (`PENDING`, `ESTIMATED`, `FINALIZED`).
- [x] Add persisted marker for `estimated_source` (`snapshot`, `market_hint`, `formula`).
- [x] Add data migration script to normalize old rows with missing source metadata.

## Phase D - Test and CI
- [x] Add API-level tests for:
  - `/api/system/metrics`
  - `/api/system/integrity-report`
  - `/api/journal/refresh`
- [x] Add concurrency tests for sync trigger and lock behavior.
- [x] Add CI workflow to run pytest and fail on regression.

## Phase E - Performance Targets
- [x] Keep `GET /api/trade-history` p95 < 40 ms (warm path).
- [x] Keep `GET /api/journal` p95 < 25 ms (page_size 20).
- [x] Keep force refresh under 5s for normal network conditions.

## Suggested Order
1) Phase A
2) Phase B
3) Phase C
4) Phase D
5) Phase E tuning pass
