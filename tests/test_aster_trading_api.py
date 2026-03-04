import app.main as app_main


def test_aster_trading_symbols_endpoint(monkeypatch):
    monkeypatch.setattr(app_main.aster_trading, "get_symbols", lambda: {"items": ["ETHUSDT"], "default": "ETHUSDT"})
    payload = app_main.aster_trading_symbols()
    assert payload["items"] == ["ETHUSDT"]
    assert payload["default"] == "ETHUSDT"


def test_aster_trading_connection_check_endpoint(monkeypatch):
    monkeypatch.setattr(app_main.aster_trading, "get_connection_status", lambda: {"ok": True, "message": "ASTER API auth is working."})
    payload = app_main.aster_trading_connection_check()
    assert payload["ok"] is True
    assert "working" in payload["message"]


def test_aster_trading_close_all_positions_endpoint(monkeypatch):
    monkeypatch.setattr(
        app_main.aster_trading,
        "close_all_positions",
        lambda payload: {"success": True, "dry_run": bool(payload.get("dry_run")), "closed": 2, "failed": 0},
    )
    payload = app_main.aster_trading_close_all_positions({"dry_run": True})
    assert payload["success"] is True
    assert payload["dry_run"] is True
    assert payload["closed"] == 2


def test_aster_trading_open_positions_passes_symbol(monkeypatch):
    calls = {"symbol": None}

    def _fake(symbol=None):
        calls["symbol"] = symbol
        return {"symbol": symbol or "ALL", "items": []}

    monkeypatch.setattr(app_main.aster_trading, "get_open_positions", _fake)
    payload = app_main.aster_trading_open_positions("BTCUSDT")
    assert calls["symbol"] == "BTCUSDT"
    assert payload["symbol"] == "BTCUSDT"


def test_aster_trading_open_orders_defaults_to_all(monkeypatch):
    calls = {"symbol": "unset"}

    def _fake(symbol=None):
        calls["symbol"] = symbol
        return {"symbol": "ALL", "items": []}

    monkeypatch.setattr(app_main.aster_trading, "get_open_orders", _fake)
    payload = app_main.aster_trading_open_orders("")
    assert calls["symbol"] is None
    assert payload["symbol"] == "ALL"


def test_aster_trading_history_endpoints_pass_symbol(monkeypatch):
    seen = {"trade": None, "pnl": None}

    def _trade(limit=100, symbol=None):
        seen["trade"] = (limit, symbol)
        return {"symbol": symbol or "ETHUSDT", "items": []}

    def _pnl(limit=100, symbol=None):
        seen["pnl"] = (limit, symbol)
        return {"symbol": symbol or "ETHUSDT", "items": []}

    monkeypatch.setattr(app_main.aster_trading, "get_trade_history", _trade)
    monkeypatch.setattr(app_main.aster_trading, "get_income_history", _pnl)

    trade = app_main.aster_trading_trade_history(limit=50, symbol="SOLUSDT")
    pnl = app_main.aster_trading_pnl_history(limit=10, symbol="SOLUSDT")

    assert seen["trade"] == (50, "SOLUSDT")
    assert seen["pnl"] == (10, "SOLUSDT")
    assert trade["symbol"] == "SOLUSDT"
    assert pnl["symbol"] == "SOLUSDT"
