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
    assert "ACCOUNT OVERVIEW" in html
    assert "Recent snapshots (last 5)" in html
    assert "1% Stoploss (auto from account risk)" in html
    assert "TP RR 1:3" in html
    assert 'id="cfg-tp-rr-enabled"' in html
    assert "Estimate Side" in html
    assert "LONG (BUY)" in html
    assert "SHORT (SELL)" in html
    assert "Manual SL, Auto the Rest" in html
    assert "Normal Flow Settings" in html
    assert "Manual SL Price" in html
    assert "% Risk on Total Capital" in html
    assert "SL Price % from entry price" in html
    assert "upnl-pos" in html
    assert "upnl-neg" in html
    assert "Trigger/Price" in html
    assert "Qty/Mode" in html
    assert "orderTypeBadge(" in html
    assert "Close-All" in html
    assert 'id="submit-status"' in html
    assert "orderInFlight" in html
    assert "Submitting..." in html
    assert "Order Type" not in html
    assert "Limit Price" not in html
    assert "Structured response view" in html
    assert "Show Raw JSON" in html
    assert '/static/theme.js' in html
    assert "marginBadge(" in html
    assert "setInterval(() => refreshAccount().catch(() => {}), 10000);" in html


def test_theme_js_supports_aster_theme_option():
    js = _read_static("theme.js")
    assert '"aster"' in js
    assert 'option value="aster"' in js
