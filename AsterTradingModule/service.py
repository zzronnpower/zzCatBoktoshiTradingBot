import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from .client import AsterTradeClient, AsterTradeError, floor_to_step, round_to_tick
from .config import AsterTradingConfig
from .pairs import MANUAL_ALLOWED_SYMBOLS


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
        self._symbol_filters_cache: Dict[str, Dict[str, Any]] = {}

    def _normalize_symbol(self, symbol: Any) -> str:
        selected = str(symbol or self.config.default_symbol).upper().strip()
        if selected not in MANUAL_ALLOWED_SYMBOLS:
            raise AsterTradeError(f"Unsupported symbol: {selected}")
        return selected

    def _symbol_filters(self, symbol: str) -> Dict[str, Any]:
        cached = self._symbol_filters_cache.get(symbol)
        if cached is not None:
            return cached

        exchange_info = self.client.get_exchange_info()
        symbols = exchange_info.get("symbols", []) if isinstance(exchange_info, dict) else []
        target = next((s for s in symbols if str(s.get("symbol", "")).upper() == symbol), None)
        if not isinstance(target, dict):
            raise AsterTradeError(f"Symbol {symbol} is not available on ASTER futures.")

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

        self._symbol_filters_cache[symbol] = out
        return out

    def _mark_price(self, symbol: str) -> float:
        premium = self.client.get_premium_index(symbol)
        mark = _to_float(premium.get("markPrice"), 0.0)
        if mark <= 0:
            raise AsterTradeError(f"Cannot resolve ASTER mark price for {symbol}.")
        return mark

    def get_symbols(self) -> Dict[str, Any]:
        return {"items": list(MANUAL_ALLOWED_SYMBOLS), "default": self.config.default_symbol}

    def get_connection_status(self) -> Dict[str, Any]:
        has_key = bool(str(self.config.api_key or "").strip())
        has_secret = bool(str(self.config.api_secret or "").strip())
        if not has_key or not has_secret:
            return {
                "ok": False,
                "configured": False,
                "message": "ASTER API key/secret is missing.",
                "hints": [
                    "Set ASTER_API_KEY and ASTER_API_SECRET in AsterTradingModule/.env.",
                    "Restart container after updating env values.",
                ],
            }

        try:
            account = self.client.get_account()
            balances = self.client.get_balance()
            usdt = next((b for b in balances if str(b.get("asset", "")).upper() == "USDT"), {})
            return {
                "ok": True,
                "configured": True,
                "message": "ASTER API auth is working.",
                "wallet_balance": _to_float(usdt.get("walletBalance"), 0.0),
                "available_balance": _to_float(usdt.get("availableBalance"), 0.0),
                "can_read_account": isinstance(account, dict),
            }
        except AsterTradeError as exc:
            hints = []
            msg_l = str(exc).lower()
            if "invalid api-key" in msg_l or "permissions" in msg_l or exc.code in {-2015, -2014}:
                hints = [
                    "Verify ASTER_API_KEY and ASTER_API_SECRET are correct.",
                    "Enable Futures permission for this API key.",
                    "Whitelist your server IP in ASTER API key settings.",
                ]
            elif exc.status_code == 429:
                hints = ["Rate limit reached. Wait and retry."]
            else:
                hints = ["Check API key status and network connectivity to ASTER."]
            return {
                "ok": False,
                "configured": True,
                "message": str(exc),
                "error_code": int(exc.code or 0),
                "status_code": int(exc.status_code or 0),
                "hints": hints,
            }

    def get_account_overview(self) -> Dict[str, Any]:
        account = self.client.get_account()
        balances = self.client.get_balance()
        positions = self.client.get_positions(None)

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
                "default_symbol": self.config.default_symbol,
                "allowed_symbols": list(MANUAL_ALLOWED_SYMBOLS),
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
        symbol = self._normalize_symbol(payload.get("symbol"))
        leverage = int(_to_float(payload.get("leverage"), self.config.leverage))
        leverage = max(1, min(leverage, 125))
        margin_usdt = max(_to_float(payload.get("margin_usdt"), self.config.margin_per_trade_usdt), 0.0)
        notional_input = _to_float(payload.get("notional_usdt"), 0.0)
        notional = notional_input if notional_input > 0 else margin_usdt * leverage
        stop_loss_pct = max(_to_float(payload.get("stop_loss_pct"), self.config.stop_loss_pct), 0.0001)
        take_profit_pct = max(_to_float(payload.get("take_profit_pct"), self.config.take_profit_pct), 0.0)
        auto_stoploss_1pct = _to_bool(payload.get("auto_stoploss_1pct"), False)

        side = str(payload.get("side", "BUY")).upper()
        if side not in {"BUY", "SELL"}:
            side = "BUY"

        order_type = str(payload.get("order_type", "MARKET")).upper()
        if order_type not in {"MARKET", "LIMIT"}:
            order_type = "MARKET"

        filters = self._symbol_filters(symbol)
        mark_price = self._mark_price(symbol)
        entry_price = _to_float(payload.get("price"), mark_price) if order_type == "LIMIT" else mark_price
        if entry_price <= 0:
            entry_price = mark_price

        raw_qty = notional / max(entry_price, 1e-9)
        quantity = floor_to_step(raw_qty, str(filters.get("step_size", "0.001")))
        min_qty = _to_float(filters.get("min_qty"), 0.0)
        min_notional = _to_float(filters.get("min_notional"), 0.0)
        computed_notional = quantity * entry_price

        if quantity < min_qty:
            quantity = floor_to_step(min_qty, str(filters.get("step_size", "0.001")))
            computed_notional = quantity * entry_price

        if auto_stoploss_1pct:
            overview = self.get_account_overview()
            account_equity = _to_float(overview.get("margin", {}).get("account_equity"), 0.0)
            if account_equity > 0 and computed_notional > 0:
                stop_loss_pct = max((account_equity * 0.01) / computed_notional, 0.0001)

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
            "mark_price": mark_price,
            "leverage": leverage,
            "quantity": quantity,
            "notional_usdt": computed_notional,
            "margin_usdt": margin,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "stop_price": stop_price,
            "take_profit_price": take_profit_price,
            "risk_usdt": risk_usdt,
            "auto_stoploss_1pct": auto_stoploss_1pct,
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

        main_order: Dict[str, Any] = {
            "symbol": preview["symbol"],
            "side": side,
            "type": order_type,
            "quantity": quantity,
            "newOrderRespType": "RESULT",
        }
        if order_type == "LIMIT":
            main_order["timeInForce"] = "GTC"
            main_order["price"] = preview["entry_price"]

        enable_tpsl = _to_bool(payload.get("enable_tpsl"), True)
        sl_order = {
            "symbol": preview["symbol"],
            "side": "SELL" if side == "BUY" else "BUY",
            "type": "STOP_MARKET",
            "stopPrice": preview["stop_price"],
            "closePosition": "true",
            "workingType": "MARK_PRICE",
        }
        tp_order = {
            "symbol": preview["symbol"],
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
                    "set_leverage": {"symbol": preview["symbol"], "leverage": leverage},
                    "main_order": main_order,
                    "stop_loss_order": sl_order if enable_tpsl else None,
                    "take_profit_order": tp_order if enable_tpsl and preview["take_profit_pct"] > 0 else None,
                },
            }

        leverage_result = self.client.set_leverage(preview["symbol"], leverage)
        main_result = self.client.place_order(main_order)
        sl_result: Optional[Dict[str, Any]] = None
        tp_result: Optional[Dict[str, Any]] = None

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
        symbol = self._normalize_symbol(payload.get("symbol"))
        position_side = str(payload.get("position_side", "")).upper().strip()
        dry_run = _to_bool(payload.get("dry_run"), self.config.dry_run)
        positions = self.client.get_positions(symbol)

        target = None
        for pos in positions:
            amt = _to_float(pos.get("positionAmt"), 0.0)
            if abs(amt) <= 1e-12:
                continue
            if position_side == "LONG" and amt <= 0:
                continue
            if position_side == "SHORT" and amt >= 0:
                continue
            target = pos
            break

        if target is None:
            return {"success": False, "message": f"No open {symbol} position to close."}

        amount = _to_float(target.get("positionAmt"), 0.0)
        side = "SELL" if amount > 0 else "BUY"
        quantity = abs(amount)
        order_payload = {
            "symbol": symbol,
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

    def close_all_positions(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        dry_run = _to_bool(payload.get("dry_run"), self.config.dry_run)
        positions = self.client.get_positions(None)
        open_positions = [p for p in positions if abs(_to_float(p.get("positionAmt"), 0.0)) > 1e-12]
        if not open_positions:
            return {"success": False, "message": "No open positions to close.", "closed": 0, "failed": 0, "items": []}

        items: List[Dict[str, Any]] = []
        closed = 0
        failed = 0
        for pos in open_positions:
            symbol = str(pos.get("symbol", "")).upper().strip()
            amount = _to_float(pos.get("positionAmt"), 0.0)
            side = "SELL" if amount > 0 else "BUY"
            order_payload = {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": abs(amount),
                "reduceOnly": "true",
                "newOrderRespType": "RESULT",
            }
            if dry_run:
                closed += 1
                items.append({"symbol": symbol, "success": True, "dry_run": True, "order": order_payload})
                continue
            try:
                result = self.client.place_order(order_payload)
                closed += 1
                items.append({"symbol": symbol, "success": True, "dry_run": False, "result": result})
            except Exception as exc:
                failed += 1
                items.append({"symbol": symbol, "success": False, "error": str(exc)})

        return {
            "success": failed == 0,
            "dry_run": dry_run,
            "closed": closed,
            "failed": failed,
            "items": items,
        }

    def get_open_positions(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        selected_symbol = self._normalize_symbol(symbol) if symbol else "ALL"
        positions = self.client.get_positions(None if selected_symbol == "ALL" else selected_symbol)
        items = []
        for pos in positions:
            amt = _to_float(pos.get("positionAmt"), 0.0)
            if abs(amt) <= 1e-12:
                continue
            symbol_name = str(pos.get("symbol", "")).upper()
            if symbol_name not in MANUAL_ALLOWED_SYMBOLS:
                continue
            items.append(pos)
        return {"symbol": selected_symbol, "items": items}

    def get_open_orders(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        selected_symbol = self._normalize_symbol(symbol) if symbol else "ALL"
        if selected_symbol != "ALL":
            return {"symbol": selected_symbol, "items": self.client.get_open_orders(selected_symbol)}

        items: List[Dict[str, Any]] = []
        try:
            all_open = self.client.get_open_orders(None)
            if isinstance(all_open, list):
                for row in all_open:
                    symbol_name = str(row.get("symbol", "")).upper()
                    if symbol_name in MANUAL_ALLOWED_SYMBOLS:
                        items.append(row)
                return {"symbol": "ALL", "items": items}
        except Exception:
            pass

        for symbol_name in MANUAL_ALLOWED_SYMBOLS:
            try:
                items.extend(self.client.get_open_orders(symbol_name))
            except Exception:
                continue
        return {"symbol": "ALL", "items": items}

    def get_trade_history(self, limit: int = 100, symbol: Optional[str] = None) -> Dict[str, Any]:
        safe_limit = max(1, min(int(limit), 1000))
        selected_symbol = self._normalize_symbol(symbol) if symbol else self.config.default_symbol
        return {"symbol": selected_symbol, "items": self.client.get_user_trades(selected_symbol, safe_limit)}

    def get_income_history(self, limit: int = 100, symbol: Optional[str] = None) -> Dict[str, Any]:
        safe_limit = max(1, min(int(limit), 1000))
        selected_symbol = self._normalize_symbol(symbol) if symbol else self.config.default_symbol
        return {"symbol": selected_symbol, "items": self.client.get_income(selected_symbol, safe_limit)}

    def get_config(self) -> Dict[str, Any]:
        data = asdict(self.config)
        data["allowed_symbols"] = list(MANUAL_ALLOWED_SYMBOLS)
        return data
