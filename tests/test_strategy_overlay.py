import app.main as app_main


def _mock_candles(count: int = 120):
    out = []
    base = 1900.0
    for i in range(count):
        close = base + (i * 0.8)
        out.append(
            {
                "open_time": i * 900000,
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "volume": 100 + i,
            }
        )
    return out


def _mock_top_symbols():
    return [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "HYPEUSDT",
        "PUMPUSDT",
        "DOGEUSDT",
        "BNBUSDT",
        "ADAUSDT",
        "LTCUSDT",
    ]


def test_overlay_rejects_wrong_interval_for_ema(monkeypatch):
    monkeypatch.setattr(app_main.runner, "get_active_strategy", lambda: app_main.runner.STRATEGY_EMA_RSI)
    monkeypatch.setattr(app_main.aster, "get_usdt_symbols_ranked", lambda pinned_symbols=None: _mock_top_symbols())

    result = app_main.strategy_overlay(symbol="ETHUSDT", interval="4h", limit=120)

    assert result["enabled"] is False
    assert result["required_interval"] == "15m"
    assert "15m" in result["message"]


def test_overlay_returns_ema_lines_for_ema_strategy(monkeypatch):
    monkeypatch.setattr(app_main.runner, "get_active_strategy", lambda: app_main.runner.STRATEGY_EMA_RSI)
    monkeypatch.setattr(app_main.aster, "get_usdt_symbols_ranked", lambda pinned_symbols=None: _mock_top_symbols())
    monkeypatch.setattr(app_main.runner.hyperliquid, "get_candles", lambda coin, interval, bars: _mock_candles(150))
    monkeypatch.setattr(app_main, "get_all_kv", lambda db_path: {})
    monkeypatch.setattr(app_main.runner, "classify_open_positions", lambda positions: {"strategy_position": None})

    result = app_main.strategy_overlay(symbol="ETHUSDT", interval="15m", limit=150)

    assert result["enabled"] is True
    assert result["strategy"] == app_main.runner.STRATEGY_EMA_RSI
    assert result["required_interval"] == "15m"
    assert len(result["ema_fast"]) > 0
    assert len(result["ema_slow"]) > 0
    assert result["ma50"] == []


def test_overlay_returns_ma50_line_for_ma_strategy(monkeypatch):
    monkeypatch.setattr(app_main.runner, "get_active_strategy", lambda: app_main.runner.STRATEGY_MA50)
    monkeypatch.setattr(app_main.aster, "get_usdt_symbols_ranked", lambda pinned_symbols=None: _mock_top_symbols())
    monkeypatch.setattr(app_main.runner.hyperliquid, "get_candles", lambda coin, interval, bars: _mock_candles(200))
    monkeypatch.setattr(app_main, "get_all_kv", lambda db_path: {})
    monkeypatch.setattr(app_main.runner, "classify_open_positions", lambda positions: {"strategy_position": None})

    result = app_main.strategy_overlay(symbol="ETHUSDT", interval="4h", limit=200)

    assert result["enabled"] is True
    assert result["strategy"] == app_main.runner.STRATEGY_MA50
    assert result["required_interval"] == "4h"
    assert len(result["ma50"]) > 0
    assert result["ema_fast"] == []
    assert result["ema_slow"] == []


def test_overlay_rejects_symbol_outside_top10(monkeypatch):
    monkeypatch.setattr(app_main.runner, "get_active_strategy", lambda: app_main.runner.STRATEGY_MA50)
    monkeypatch.setattr(app_main.aster, "get_usdt_symbols_ranked", lambda pinned_symbols=None: _mock_top_symbols())

    result = app_main.strategy_overlay(symbol="AVAXUSDT", interval="4h", limit=100)

    assert result["enabled"] is False
    assert "top 10" in result["message"].lower()


def test_overlay_returns_regime_data_for_regime_strategy(monkeypatch):
    monkeypatch.setattr(app_main.runner, "get_active_strategy", lambda: app_main.runner.STRATEGY_REGIME_SWITCH)
    monkeypatch.setattr(app_main.aster, "get_usdt_symbols_ranked", lambda pinned_symbols=None: _mock_top_symbols())
    monkeypatch.setattr(app_main.runner.hyperliquid, "get_candles", lambda coin, interval, bars: _mock_candles(260))
    monkeypatch.setattr(app_main, "get_all_kv", lambda db_path: {})
    monkeypatch.setattr(app_main.runner, "classify_open_positions", lambda positions: {"strategy_position": None})

    result = app_main.strategy_overlay(symbol="ETHUSDT", interval="4h", limit=260)

    assert result["enabled"] is True
    assert result["strategy"] == app_main.runner.STRATEGY_REGIME_SWITCH
    assert result["required_interval"] == "4h"
    assert len(result["ema_fast"]) > 0
    assert "regime_snapshot" in result
