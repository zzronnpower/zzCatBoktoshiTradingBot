# Checklist cai thien he thong (Boktoshi)

## Muc tieu
- Tang do on dinh khi chay dai han
- Giam do tre Dashboard/Journal
- Giam loi du lieu thieu/trung o Trade History/Journal
- Thiet lap quy trinh test/release an toan

## Quy uoc trang thai
- [ ] Chua lam
- [~] Dang lam
- [x] Hoan thanh
- [-] Bo qua / khong ap dung

---

## Phase 1 - Quick Wins (uu tien cao)

### 1. Tach sync nang khoi request UI
- [x] Tach logic fetch history nang ra background sync (khong chay truc tiep trong `/api/trade-history`)
- [x] Giu endpoint dashboard chi doc DB local + cache
- [x] Them throttle ro rang cho sync task (TTL + lock chong chay chong)

### 2. Giam lag frontend do refresh day
- [x] Chia refresh theo nhom:
  - realtime (status/open positions): 3-5s
  - history/journal/logs/signals: 15-30s hoac manual refresh
- [x] Chi rerender bang khi hash du lieu doi
- [x] Giu trang thai UI (page, scroll, filter) on dinh khi refresh

### 3. On dinh luong close trade
- [x] Chuan hoa trang thai close: pending -> estimated -> finalized
- [x] Retry finalize theo positionId (backoff + timeout window)
- [x] Hien thi ro Estimated / Pending settlement / Finalized

### 4. Don du lieu runtime co kiem soat
- [x] Cap logs/signals/equity_curve = 100 dong
- [x] Kiem tra them index cho truy van dashboard nong

---

## Phase 2 - Data Integrity & Performance

### 5. Cung hoa SQLite cho tai thuc te
- [x] Bat PRAGMA journal_mode=WAL
- [x] Bat PRAGMA synchronous=NORMAL
- [x] Bat PRAGMA busy_timeout
- [x] Danh gia lai lock contention khi bot loop + API cung ghi

### 6. Bo sung index DB
- [x] journal_entries(external_id) unique + verify
- [x] journal_entries(close_ts) index
- [x] trades(ts, action) index
- [x] logs(ts) index
- [x] signals(ts) index

### 7. Chong duplicate/barn du lieu
- [x] Script integrity check dinh ky:
  - duplicate external_id
  - pending qua lau
  - record thieu key field
- [x] Co che auto-heal hoac canh bao tren dashboard admin

---

## Phase 3 - Testability & Release Safety

### 8. Sua ha tang test
- [x] Fix import path pytest (app, BoktoshiBotModule)
- [x] Them pytest.ini chuan
- [x] Dam bao test collect/pass on dinh local + docker

### 9. Bo sung test cho luong quan trong
- [x] Test close flow: manual/strategy/recovered
- [x] Test estimator fallback
- [x] Test dedupe journal
- [x] Test summary cong ca estimated pnl

### 10. Quan sat he thong (observability)
- [x] Metric latency endpoint
- [x] Metric sync duration + error rate external API
- [x] Metric pending close count
- [x] Log structured theo positionId/external_id

---

## Deliverables sau moi hang muc
- [x] Co ghi chu thay doi (file nao, logic nao)
- [x] Co ket qua verify (API, DB count, UI check)
- [x] Cap nhat lai checklist trang thai

---

## Nhat ky thuc thi

- 2026-02-25: Khoi tao checklist va bat dau Phase 1.1 (tach sync nang khoi request path).
- 2026-02-25: Hoan thanh Phase 1.1:
  - them background sync worker + lock cho journal snapshot.
  - `/api/trade-history`, `/api/journal`, `/api/journal/summary` chi trigger sync nen khong block response.
  - them warmup sync luc startup va giu refresh endpoint force-sync dong bo.
- 2026-02-25: Tiep tuc Phase 1.2 va tinh nang Estimate:
  - bo gioi han 2h cua market-price estimate, giu duoc `display_exit_price` va `display_realized_pnl` cho cac lenh pending.
  - tach polling Dashboard theo fast/slow lanes (slow cache 15s cho history/pnl/signals/logs).
  - nut `Refresh Finalized PnL` co reset slow cache de cap nhat ngay.
- 2026-02-25: Hoan thanh them cac hang muc hieu nang/DB:
  - them hash-based rerender cho Trade History, PnL History, Signals, Logs de tranh redraw thua.
  - harden SQLite: WAL + synchronous NORMAL + busy_timeout.
  - bo sung index truy van nong: logs(ts), signals(ts), trades(ts,action), equity_curve(ts), journal_entries(close_ts,source).
- 2026-02-25: Bo sung retry finalize va integrity checks:
  - them pending finalize queue theo `positionId` voi backoff (15s -> toi da 900s) va timeout window 24h.
  - them API canh bao he thong: `GET /api/system/integrity-report`.
  - them script offline check: `scripts/integrity_check.py`.
- 2026-02-25: Hoan thanh ha tang test (Phase 3.8) va bo sung test helper:
  - them `tests/conftest.py` de fix import path khi chay pytest.
  - them `pytest.ini` chuan hoa test collection.
  - them test moi cho summary/estimator/integrity script.
  - ket qua: `18 passed`.
- 2026-02-25: Tiep tuc phase tiep theo:
  - them test dedupe storage cho `replace_journal_entries`.
  - them endpoint observability `GET /api/system/metrics` (request latency, journal sync, remote history, pending finalize count).
  - them lock contention benchmark script `scripts/lock_contention_check.py` va chay stress 8 workers x 250 loops (0 write errors).
  - cap nhat test result: `19 passed`.
- 2026-02-25: Hoan thanh observability logging:
  - bo sung structured logs cho cac event open/close quan trong voi `position_id` va `external_id`.
  - structured logs bo sung cho stale-clear, rate-limit skip, submitted/failed flows.
  - bo sung test endpoint metrics (`tests/test_system_metrics.py`).
  - cap nhat test result: `20 passed`.
- 2026-02-25: Dong checklist phase hien tai:
  - danh dau hoan tat 3 deliverables chung (ghi chu thay doi / verify / cap nhat checklist).
- 2026-02-25: Trien khai tiep toan bo 5 phase roadmap:
  - Phase A: tao service layer `app/services/journal_app_service.py` va wire endpoint read-model qua service.
  - Phase B: them panel `System Health`, action `Clear Stale Pending Queue`, bo loc nhanh Journal (source/state/recovered).
  - Phase C: bo sung truong suy dien `finalization_state` va `estimated_source` tren journal rows.
  - Phase D: bo sung CI workflow `pytest` tren GitHub Actions.
  - Phase E: bo sung script benchmark/target check `scripts/perf_targets_check.py` va verify dat target hien tai.
