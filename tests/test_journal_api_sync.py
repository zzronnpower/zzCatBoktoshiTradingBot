import threading
import time

import app.main as app_main


def test_api_journal_refresh_triggers_sync_and_counts_pending(monkeypatch):
    called = {"force": None, "background": None}

    def fake_trigger(force=False, background=True):
        called["force"] = force
        called["background"] = background
        return True

    monkeypatch.setattr(app_main, "_trigger_journal_sync", fake_trigger)
    monkeypatch.setattr(app_main, "get_journal_entries", lambda db_path, limit, offset: [{"id": 1}, {"id": 2}, {"id": 3}])
    monkeypatch.setattr(
        app_main,
        "_decorate_journal_rows",
        lambda rows, allow_network_hints=False: [
            {"id": 1, "pending": 1},
            {"id": 2, "pending": 0},
            {"id": 3, "pending": 1},
        ],
    )

    payload = app_main.journal_refresh()

    assert payload["success"] is True
    assert payload["refreshed"] == 3
    assert payload["pending"] == 2
    assert called == {"force": True, "background": False}


def test_api_integrity_report_uses_journal_service(monkeypatch):
    expected = {"report": {"total_rows": 10, "duplicate_external_id_count": 0}}
    monkeypatch.setattr(app_main.journal_service, "get_integrity_report", lambda: expected)

    payload = app_main.system_integrity_report()

    assert payload == expected


def test_trigger_journal_sync_background_returns_false_when_worker_alive(monkeypatch):
    class _AliveWorker:
        def is_alive(self):
            return True

    monkeypatch.setattr(app_main, "_JOURNAL_SYNC_THREAD", _AliveWorker())
    started = app_main._trigger_journal_sync(force=False, background=True)
    assert started is False


def test_run_journal_sync_task_uses_lock_to_serialize(monkeypatch):
    active = {"count": 0, "max": 0, "calls": 0}
    guard = threading.Lock()

    def fake_sync(force=False):
        with guard:
            active["count"] += 1
            active["calls"] += 1
            active["max"] = max(active["max"], active["count"])
        time.sleep(0.05)
        with guard:
            active["count"] -= 1

    monkeypatch.setattr(app_main, "_sync_journal_snapshot", fake_sync)

    t1 = threading.Thread(target=app_main._run_journal_sync_task, kwargs={"force": False})
    t2 = threading.Thread(target=app_main._run_journal_sync_task, kwargs={"force": False})
    t1.start()
    t2.start()
    t1.join(timeout=1)
    t2.join(timeout=1)

    assert active["calls"] == 2
    assert active["max"] == 1
