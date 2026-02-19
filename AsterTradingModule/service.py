import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from .client import AsterTradeClient, AsterTradeError, floor_to_step, round_to_tick
from .config import AsterTradingConfig


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class AsterManualTradingService:
    def __init__(self, config: Optional[AsterTradingConfig] = None) -> None:
        self.config = config or AsterTradingConfig()
        self.client = AsterTradeClient(self.config)
        self._symbol_filters_cache: Optional[Dict[str, Any]] = None

    def _symbol_filters(self) -> Dict[str, Any]:
        if self._symbol_filters_cache is not None:
            return self._symbol_filters_cache
        exchange_info = self.client.get_exchange_info()
        symbols = exchange_info.get("symbols", []) if isinstance(exchange_info, dict) else []
        target = next((s for s in symbols if str(s.get("symbol", "")).upper() == self.config.symbol), None)
        if not isinstance(target, dict):
            raise AsterTradeError(f"Symbol {self.config.symbol} is not available on ASTER futures.")

        raw_filters = target.get("filters", [])
        out = {
            "step_size": "0.001",
            "tick_size": "0.01",
            "min_qty": 0.0,
            "min_notional": 0.0,
        }
        for item in raw_filters:
            if not isinstance(item, dict):
                continue
            filter_type = item.get("filterType")
            if filter_type in {"LOT_SIZE", "MARKET_LOT_SIZE"}:
                out["step_size"] = item.get("stepSize", out["step_size"])
                out["min_qty"] = max(out["min_qty"], _to_float(item.get("minQty"), 0.0))
            elif filter_type == "PRICE_FILTER":
                out["tick_size"] = item.get("tickSize", out["tick_size"])
            elif filter_type in {"MIN_NOTIONAL", "NOTIONAL"}:
                out["min_notional"] = max(out["min_notional"], _to_float(item.get("notional"), 0.0))
                out["min_notional"] = max(out["min_notional"], _to_float(item.get("minNotional"), 0.0))

        self._symbol_filters_cache = out
        return out

    def _mark_price(self) -> float:
        premium = self.client.get_premium_index(self.config.symbol)
        mark = _to_float(premium.get("markPrice"), 0.0)
        if mark <= 0:
            raise AsterTradeError("Cannot resolve ASTER mark price for ETHUSDT.")
        return mark

    def get_account_overview(self) -> Dict[str, Any]:
        account = self.client.get_account()
        balances = self.client.get_balance()
        positions = self.client.get_positions(self.config.symbol)

        usdt_balance = next((b for b in balances if str(b.get("asset", "")).upper() == "USDT"), {})
        total_wallet = _to_float(account.get("totalWalletBalance"), _to_float(usdt_balance.get("walletBalance"), 0.0))
        total_upnl = _to_float(account.get("totalUnrealizedProfit"), 0.0)
        total_margin_balance = _to_float(account.get("totalMarginBalance"), total_wallet + total_upnl)
        total_maint_margin = _to_float(account.get("totalMaintMargin"), 0.0)
        margin_ratio = (total_maint_margin / total_margin_balance) if total_margin_balance > 0 else 0.0

        active_positions: List[Dict[str, Any]] = []
        for pos in positions:
            amt = _to_float(pos.get("positionAmt"), 0.0)
            if abs(amt) <= 1e-12:
                continue
            active_positions.append(pos)

        return {
            "config": {
                "symbol": self.config.symbol,
                "defaults": {
                    "leverage": self.config.leverage,
                    "position_notional_usdt": self.config.position_notional_usdt,
                    "margin_per_trade_usdt": self.config.margin_per_trade_usdt,
                    "stop_loss_pct": self.config.stop_loss_pct,
                    "risk_usdt": self.config.risk_usdt,
                    "dry_run": self.config.dry_run,
                },
            },
            "account_equity": {
                "spot_total_value": 0.0,
                "perp_total_value": total_margin_balance,
                "perp_unrealized_pnl": total_upnl,
                "shield_unrealized_pnl": 0.0,
            },
            "margin": {
                "account_margin_ratio": margin_ratio,
                "account_margin_ratio_pct": margin_ratio * 100,
                "account_maintenance_margin": total_maint_margin,
                "account_equity": total_margin_balance,
                "wallet_balance": _to_float(usdt_balance.get("walletBalance"), total_wallet),
                "available_balance": _to_float(usdt_balance.get("availableBalance"), 0.0),
                "max_withdraw_amount": _to_float(usdt_balance.get("maxWithdrawAmount"), 0.0),
            },
            "positions": active_positions,
            "server_time": int(time.time() * 1000),
        }

    def preview_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        symbol = self.config.symbol
        leverage = int(_to_float(payload.get("leverage"), self.config.leverage))
        leverage = max(1, min(leverage, 125))
        notional = max(_to_float(payload.get("notional_usdt"), self.config.position_notional_usdt), 0.0)
        stop_loss_pct = max(_to_float(payload.get("stop_loss_pct"), self.config.stop_loss_pct), 0.0001)
        take_profit_pct = max(_to_float(payload.get("take_profit_pct"), self.config.take_profit_pct), 0.0)
        side = str(payload.get("side", "BUY")).upper()
        if side not in {"BUY", "SELL"}:
            side = "BUY"

        order_type = str(payload.get("order_type", "MARKET")).upper()
        if order_type not in {"MARKET", "LIMIT", "STOP", "STOP_MARKET", "TAKE_PROFIT", "TAKE_PROFIT_MARKET"}:
            order_type = "MARKET"

        filters = self._symbol_filters()
        mark_price = self._mark_price()
        entry_price = _to_float(payload.get("price"), mark_price) if order_type != "MARKET" else mark_price
        if entry_price <= 0:
            entry_price = mark_price

        raw_qty = notional / max(entry_price, 1e-9)
        quantity = floor_to_step(raw_qty, str(filters.get("step_size", "0.001")))
        min_qty = _to_float(filters.get("min_qty"), 0.0)
        min_notional = _to_float(filters.get("min_notional"), 0.0)
        computed_notional = quantity * entry_price

        if quantity < min_qty:
            quantity = min_qty
            quantity = floor_to_step(quantity, str(filters.get("step_size", "0.001")))
            computed_notional = quantity * entry_price

        sl_mult = 1 - stop_loss_pct if side == "BUY" else 1 + stop_loss_pct
        tp_mult = 1 + take_profit_pct if side == "BUY" else 1 - take_profit_pct
        stop_price = round_to_tick(entry_price * sl_mult, str(filters.get("tick_size", "0.01")))
        take_profit_price = round_to_tick(entry_price * tp_mult, str(filters.get("tick_size", "0.01")))

        margin = computed_notional / max(leverage, 1)
        risk_usdt = computed_notional * stop_loss_pct
        warnings: List[str] = []
        if computed_notional < min_notional:
            warnings.append(f"Notional {computed_notional:.4f} is below exchange minNotional {min_notional:.4f}.")
        if quantity <= 0:
            warnings.append("Quantity resolved to zero after step-size rounding.")

        return {
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "entry_price": entry_price,
            "leverage": leverage,
            "quantity": quantity,
            "notional_usdt": computed_notional,
            "margin_usdt": margin,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "stop_price": stop_price,
            "take_profit_price": take_profit_price,
            "risk_usdt": risk_usdt,
            "filters": filters,
            "warnings": warnings,
        }

    def place_manual_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        preview = self.preview_order(payload)
        if preview["quantity"] <= 0:
            return {"success": False, "message": "Quantity is invalid after symbol filter rounding.", "preview": preview}
        if preview["warnings"]:
            return {"success": False, "message": "Order preview has validation warnings.", "preview": preview}

        dry_run = _to_bool(payload.get("dry_run"), self.config.dry_run)
        leverage = int(preview["leverage"])
        side = preview["side"]
        quantity = preview["quantity"]
        order_type = preview["order_type"]
        tif = str(payload.get("time_in_force", "GTC")).upper()
        if tif not in {"GTC", "IOC", "FOK", "GTX"}:
            tif = "GTC"

        main_order: Dict[str, Any] = {
            "symbol": self.config.symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity,
            "newOrderRespType": "RESULT",
        }
        if order_type in {"LIMIT", "STOP", "TAKE_PROFIT"}:
            main_order["timeInForce"] = tif
            main_order["price"] = preview["entry_price"]
        if order_type in {"STOP", "STOP_MARKET", "TAKE_PROFIT", "TAKE_PROFIT_MARKET"}:
            stop_price = _to_float(payload.get("trigger_price"), 0.0)
            if stop_price <= 0:
                stop_price = preview["stop_price"]
            main_order["stopPrice"] = round_to_tick(stop_price, str(preview["filters"]["tick_size"]))
        reduce_only = _to_bool(payload.get("reduce_only"), False)
        if reduce_only:
            main_order["reduceOnly"] = "true"

        enable_tpsl = _to_bool(payload.get("enable_tpsl"), True)
        sl_order = {
            "symbol": self.config.symbol,
            "side": "SELL" if side == "BUY" else "BUY",
            "type": "STOP_MARKET",
            "stopPrice": preview["stop_price"],
            "closePosition": "true",
            "workingType": "MARK_PRICE",
        }
        tp_order = {
            "symbol": self.config.symbol,
            "side": "SELL" if side == "BUY" else "BUY",
            "type": "TAKE_PROFIT_MARKET",
            "stopPrice": preview["take_profit_price"],
            "closePosition": "true",
            "workingType": "MARK_PRICE",
        }

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "message": "DRY_RUN enabled. No live ASTER order submitted.",
                "preview": preview,
                "orders": {
                    "set_leverage": {"symbol": self.config.symbol, "leverage": leverage},
                    "main_order": main_order,
                    "stop_loss_order": sl_order if enable_tpsl else None,
                    "take_profit_order": tp_order if enable_tpsl and preview["take_profit_pct"] > 0 else None,
                },
            }

        leverage_result = self.client.set_leverage(self.config.symbol, leverage)
        main_result = self.client.place_order(main_order)
        sl_result: Dict[str, Any] | None = None
        tp_result: Dict[str, Any] | None = None

        if enable_tpsl:
            sl_result = self.client.place_order(sl_order)
            if preview["take_profit_pct"] > 0:
                tp_result = self.client.place_order(tp_order)

        return {
            "success": True,
            "dry_run": False,
            "preview": preview,
            "results": {
                "set_leverage": leverage_result,
                "main_order": main_result,
                "stop_loss_order": sl_result,
                "take_profit_order": tp_result,
            },
        }

    def close_position_market(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        dry_run = _to_bool(payload.get("dry_run"), self.config.dry_run)
        positions = self.client.get_positions(self.config.symbol)
        target = None
        for pos in positions:
            amt = _to_float(pos.get("positionAmt"), 0.0)
            if abs(amt) > 1e-12:
                target = pos
                break
        if target is None:
            return {"success": False, "message": "No open ETHUSDT position to close."}

        amount = _to_float(target.get("positionAmt"), 0.0)
        side = "SELL" if amount > 0 else "BUY"
        quantity = abs(amount)
        order_payload = {
            "symbol": self.config.symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
            "reduceOnly": "true",
            "newOrderRespType": "RESULT",
        }

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "message": "DRY_RUN close request prepared.",
                "order": order_payload,
            }

        result = self.client.place_order(order_payload)
        return {"success": True, "dry_run": False, "result": result}

    def get_open_positions(self) -> Dict[str, Any]:
        positions = self.client.get_positions(self.config.symbol)
        items = []
        for pos in positions:
            amt = _to_float(pos.get("positionAmt"), 0.0)
            if abs(amt) <= 1e-12:
                continue
            items.append(pos)
        return {"symbol": self.config.symbol, "items": items}

    def get_open_orders(self) -> Dict[str, Any]:
        return {"symbol": self.config.symbol, "items": self.client.get_open_orders(self.config.symbol)}

    def get_trade_history(self, limit: int = 100) -> Dict[str, Any]:
        safe_limit = max(1, min(int(limit), 1000))
        return {"symbol": self.config.symbol, "items": self.client.get_user_trades(self.config.symbol, safe_limit)}

    def get_income_history(self, limit: int = 100) -> Dict[str, Any]:
        safe_limit = max(1, min(int(limit), 1000))
        return {"symbol": self.config.symbol, "items": self.client.get_income(self.config.symbol, safe_limit)}

    def get_config(self) -> Dict[str, Any]:
        return asdict(self.config)
