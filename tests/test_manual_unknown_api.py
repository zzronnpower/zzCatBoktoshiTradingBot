import app.main as app_main


def test_close_unknown_position_endpoint_passes_payload(monkeypatch):
    seen = {"position_id": None}

    def _fake(position_id="", comment=""):
        seen["position_id"] = position_id
        return {"success": True, "closed": 1, "position_id": position_id}

    monkeypatch.setattr(app_main.runner, "close_unknown_position", _fake)
    payload = app_main.close_unknown_position({"position_id": "u-test"})
    assert seen["position_id"] == "u-test"
    assert payload["success"] is True
    assert payload["position_id"] == "u-test"


def test_close_all_unknown_positions_endpoint_calls_runner(monkeypatch):
    called = {"value": False}

    def _fake(comment=""):
        called["value"] = True
        return {"success": True, "closed": 2, "failed": 0}

    monkeypatch.setattr(app_main.runner, "close_all_unknown_positions", _fake)
    payload = app_main.close_all_unknown_positions()
    assert called["value"] is True
    assert payload["success"] is True
    assert payload["closed"] == 2
