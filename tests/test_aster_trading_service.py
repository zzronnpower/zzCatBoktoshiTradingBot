from AsterTradingModule.config import AsterTradingConfig
from AsterTradingModule.service import AsterManualTradingService


class FakeClient:
    def get_exchange_info(self):
        return {
            "symbols": [
                {
                    "symbol": "ETHUSDT",
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
