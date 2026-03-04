from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_template(name: str) -> str:
    path = ROOT / "app" / "templates" / name
    return path.read_text(encoding="utf-8")


def _read_static(name: str) -> str:
    path = ROOT / "app" / "static" / name
    return path.read_text(encoding="utf-8")


def test_aster_trading_template_removes_stop_limit_and_tif():
    html = _read_template("aster_trading.html")
    assert "Stop Limit" not in html
    assert "Time In Force" not in html
    assert "id=\"tab-market\"" in html
    assert "id=\"tab-limit\"" in html


def test_aster_trading_template_has_auto_1pct_stoploss_control():
    html = _read_template("aster_trading.html")
    assert "1% Stoploss" in html
    assert "id=\"f-auto-1pct\"" in html
    assert "SL reference" in html


def test_aster_trading_template_has_human_response_view_controls():
    html = _read_template("aster_trading.html")
    assert "Structured response view" in html
    assert "Show Raw JSON" in html
    assert "id=\"response-summary\"" in html
    assert "selected-row" in html
    assert "Check API Auth" in html
    assert '/static/theme.js' in html
    assert "Promise.allSettled([checkConnection(), refreshAccount()])" in html


def test_aster_simple_trading_template_has_quick_close_buttons():
    html = _read_template("aster_simple_trading.html")
    assert "AsterSimpleTrading" in html
    assert "Close Selected Symbol" in html
    assert "Close All Positions" in html
    assert "POSITION SETTINGS" in html
    assert "Order Type" not in html
    assert "Limit Price" not in html
    assert "Structured response view" in html
    assert "Show Raw JSON" in html
    assert '/static/theme.js' in html


def test_theme_js_supports_aster_theme_option():
    js = _read_static("theme.js")
    assert '"aster"' in js
    assert 'option value="aster"' in js
