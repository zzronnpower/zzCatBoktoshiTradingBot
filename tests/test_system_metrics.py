import app.main as app_main
from app.storage import init_db


def test_system_metrics_contains_expected_sections(tmp_path, monkeypatch):
    db_path = str(tmp_path / "bot.db")
    init_db(db_path)
    monkeypatch.setattr(app_main, "DB_PATH", db_path)

    # seed request metric
    app_main._record_request_metric('/api/test-metric', 12.0)

    payload = app_main.system_metrics()
    metrics = payload.get('metrics', {})

    assert 'requests' in metrics
    assert 'journal_sync' in metrics
    assert 'remote_history' in metrics
    assert 'pending_finalize_count' in metrics
    assert 'regime_tuning' in metrics
    assert '/api/test-metric' in metrics['requests']
    regime = metrics['regime_tuning']
    assert 'cap_blocked_total' in regime
    assert 'candidates_total' in regime
    assert 'open_rate' in regime
