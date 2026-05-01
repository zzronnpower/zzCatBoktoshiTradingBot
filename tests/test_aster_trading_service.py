from AsterTradingModule.config import AsterTradingConfig
from AsterTradingModule.service import AsterManualTradingService


class FakeClient:
    def get_exchange_info(self):
        return {
            "symbols": [
                {
                    "symbol": "ETHUSDT",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                    "quoteAsset": "USDT",
                    "filters": [
                        {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                        {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                        {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
                    ],
                }
            ]
        }

    def get_premium_index(self, symbol):
        return {"markPrice": "2000" if symbol == "ETHUSDT" else "1"}

    def get_account(self):
        return {
            "totalWalletBalance": "1000",
            "totalUnrealizedProfit": "0",
            "totalMarginBalance": "1000",
            "totalMaintMargin": "10",
        }

    def get_balance(self):
        return [{"asset": "USDT", "walletBalance": "1000", "availableBalance": "900", "maxWithdrawAmount": "900"}]

    def get_positions(self, symbol=None):
        items = [
            {"symbol": "ETHUSDT", "positionAmt": "0.5", "entryPrice": "1900", "markPrice": "2000", "unRealizedProfit": "50", "leverage": "5"},
            {"symbol": "BTCUSDT", "positionAmt": "0", "entryPrice": "0", "markPrice": "0", "unRealizedProfit": "0", "leverage": "5"},
        ]
        if symbol:
            return [x for x in items if x["symbol"] == symbol]
        return items

    def get_open_orders(self, symbol=None):
        return []

    def set_leverage(self, symbol, leverage):
        return {"symbol": symbol, "leverage": leverage}

    def place_order(self, params):
        return {"ok": True, "params": params}

    def get_user_trades(self, symbol, limit):
        return []

    def get_income(self, symbol, limit):
        return []


def _service():
    service = AsterManualTradingService(AsterTradingConfig())
    service.client = FakeClient()
    return service


def test_preview_uses_margin_and_leverage_for_notional():
    service = _service()
    out = service.preview_order(
        {
            "symbol": "ETHUSDT",
            "order_type": "MARKET",
            "side": "BUY",
            "margin_usdt": 100,
            "leverage": 5,
            "stop_loss_pct": 0.05,
            "take_profit_pct": 0.1,
        }
    )
    assert out["symbol"] == "ETHUSDT"
    assert out["notional_usdt"] > 0
    assert round(out["margin_usdt"], 2) == 100.0
    assert out["order_type"] == "MARKET"


def test_preview_auto_1pct_stoploss_changes_sl_percent():
    service = _service()
    out = service.preview_order(
        {
            "symbol": "ETHUSDT",
            "order_type": "MARKET",
            "side": "BUY",
            "margin_usdt": 100,
            "leverage": 5,
            "stop_loss_pct": 0.05,
            "auto_stoploss_1pct": True,
        }
    )
    assert out["auto_stoploss_1pct"] is True
    assert out["stop_loss_pct"] > 0
    assert out["stop_price"] > 0


def test_preview_take_profit_rr_mode_uses_stop_distance():
    service = _service()
    out = service.preview_order(
        {
            "symbol": "ETHUSDT",
            "order_type": "MARKET",
            "side": "BUY",
            "margin_usdt": 100,
            "leverage": 5,
            "stop_loss_pct": 0.05,
            "tp_mode": "rr",
            "tp_rr": 3,
            "take_profit_pct": 0.01,
        }
    )
    risk_distance = abs(float(out["entry_price"]) - float(out["stop_price"]))
    tp_distance = abs(float(out["take_profit_price"]) - float(out["entry_price"]))
    assert out["tp_mode"] == "rr"
    assert abs(tp_distance - (risk_distance * 3)) < 1e-6


def test_preview_manual_sl_auto_rest_calculates_notional_from_risk_pct():
    service = _service()
    out = service.preview_order(
        {
            "symbol": "ETHUSDT",
            "settings_mode": "manual_sl_auto_rest",
            "order_type": "MARKET",
            "side": "BUY",
            "leverage": 5,
            "manual_sl_price": 1900,
            "risk_pct_total_capital": 1.0,
            "tp_mode": "rr",
            "tp_rr": 3,
        }
    )
    # account_equity from FakeClient is 1000, so risk target is 10 USDT
    expected_sl_pct = (2000 - 1900) / 2000
    expected_notional = 10.0 / expected_sl_pct
    assert out["settings_mode"] == "manual_sl_auto_rest"
    assert abs(float(out["notional_usdt"]) - expected_notional) < 2.0


def test_close_all_positions_dry_run_returns_closed_count():
    service = _service()
    out = service.close_all_positions({"dry_run": True})
    assert out["dry_run"] is True
    assert out["closed"] == 1
    assert out["failed"] == 0


def test_get_open_positions_filters_zero_positions():
    service = _service()
    out = service.get_open_positions()
    assert out["symbol"] == "ALL"
    assert len(out["items"]) == 1
    assert out["items"][0]["symbol"] == "ETHUSDT"


def test_get_open_positions_includes_symbols_outside_static_whitelist():
    service = _service()

    class DynamicClient(FakeClient):
        def get_positions(self, symbol=None):
            items = [
                {"symbol": "BTCUSDT", "positionAmt": "-0.01", "entryPrice": "100000", "markPrice": "100010", "unRealizedProfit": "-0.1", "leverage": "5"},
                {"symbol": "MONUSDT", "positionAmt": "-15099", "entryPrice": "0.0298", "markPrice": "0.0297", "unRealizedProfit": "1.0", "leverage": "5"},
            ]
            if symbol:
                return [x for x in items if x["symbol"] == symbol]
            return items

    service.client = DynamicClient()
    out = service.get_open_positions()
    symbols = sorted([str(x.get("symbol", "")).upper() for x in out["items"]])
    assert symbols == ["BTCUSDT", "MONUSDT"]


def test_get_symbols_filters_to_usdt_perpetual_trading():
    service = _service()

    class DynamicClient(FakeClient):
        def get_exchange_info(self):
            return {
                "symbols": [
                    {"symbol": "ETHUSDT", "contractType": "PERPETUAL", "status": "TRADING", "quoteAsset": "USDT", "filters": []},
                    {"symbol": "BTCUSDT", "contractType": "PERPETUAL", "status": "TRADING", "quoteAsset": "USDT", "filters": []},
                    {"symbol": "ETHUSDC", "contractType": "PERPETUAL", "status": "TRADING", "quoteAsset": "USDC", "filters": []},
                    {"symbol": "XRPUSDT", "contractType": "PERPETUAL", "status": "PENDING_TRADING", "quoteAsset": "USDT", "filters": []},
                    {"symbol": "ABCUSDT", "contractType": "CURRENT_QUARTER", "status": "TRADING", "quoteAsset": "USDT", "filters": []},
                ]
            }

    service.client = DynamicClient()
    out = service.get_symbols()
    assert out["items"] == ["BTCUSDT", "ETHUSDT"]
    assert out["default"] in out["items"]


def test_normalize_symbol_accepts_dynamic_symbol_not_in_static_whitelist():
    service = _service()

    class DynamicClient(FakeClient):
        def get_exchange_info(self):
            return {
                "symbols": [
                    {
                        "symbol": "ADAUSDT",
                        "contractType": "PERPETUAL",
                        "status": "TRADING",
                        "quoteAsset": "USDT",
                        "filters": [
                            {"filterType": "LOT_SIZE", "stepSize": "0.1", "minQty": "0.1"},
                            {"filterType": "PRICE_FILTER", "tickSize": "0.0001"},
                            {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
                        ],
                    }
                ]
            }

        def get_premium_index(self, symbol):
            if symbol == "ADAUSDT":
                return {"markPrice": "1"}
            return super().get_premium_index(symbol)

    service.client = DynamicClient()
    preview = service.preview_order({"symbol": "ADAUSDT", "order_type": "MARKET", "side": "BUY", "margin_usdt": 10, "leverage": 2})
    assert preview["symbol"] == "ADAUSDT"
