import time
import math
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
        self._symbols_cache: List[str] = []
        self._symbols_cache_ts = 0.0
        self._manual_auto_max_positions = 3
        self._manual_auto_min_leverage = 3
        self._manual_auto_max_leverage = 6
        self._manual_auto_balance_buffer_ratio = 0.10

    def _count_open_positions(self) -> int:
        try:
            positions = self.client.get_positions(None)
        except Exception:
            return 0
        return sum(1 for pos in positions if abs(_to_float(pos.get("positionAmt"), 0.0)) > 1e-12)

    def _discover_tradable_symbols(self, force_refresh: bool = False) -> List[str]:
        now = time.time()
        if not force_refresh and self._symbols_cache and (now - self._symbols_cache_ts) < 30:
            return list(self._symbols_cache)

        exchange_info = self.client.get_exchange_info()
        raw_symbols = exchange_info.get("symbols", []) if isinstance(exchange_info, dict) else []

        tradable: List[str] = []
        for item in raw_symbols:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol", "")).upper().strip()
            if not symbol:
                continue
            contract_type = str(item.get("contractType", "")).upper().strip()
            status = str(item.get("status", "")).upper().strip()
            quote = str(item.get("quoteAsset", "")).upper().strip()
            if contract_type != "PERPETUAL" or status != "TRADING" or quote != "USDT":
                continue
            tradable.append(symbol)

        unique_sorted = sorted(set(tradable))
        self._symbols_cache = unique_sorted
        self._symbols_cache_ts = now
        return list(unique_sorted)

    def _normalize_symbol(self, symbol: Any) -> str:
        selected = str(symbol or self.config.default_symbol).upper().strip()
        try:
            tradable = self._discover_tradable_symbols()
        except Exception:
            tradable = list(MANUAL_ALLOWED_SYMBOLS)
        if selected not in tradable:
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
        items: List[str]
        try:
            items = self._discover_tradable_symbols(force_refresh=True)
        except Exception:
            items = list(MANUAL_ALLOWED_SYMBOLS)
        if not items:
            items = list(MANUAL_ALLOWED_SYMBOLS)

        default_symbol = str(self.config.default_symbol).upper().strip()
        if default_symbol not in items:
            default_symbol = items[0]
        return {"items": items, "default": default_symbol}

    def get_connection_status(self) -> Dict[str, Any]:
        has_user = bool(str(self.config.user_address or "").strip())
        has_signer = bool(str(self.config.signer_address or "").strip())
        has_pk = bool(str(self.config.signer_private_key or "").strip())
        if not has_user or not has_signer or not has_pk:
            return {
                "ok": False,
                "configured": False,
                "message": "ASTER Pro API credential is missing.",
                "hints": [
                    "Set ASTER_USER_ADDRESS, ASTER_SIGNER_ADDRESS, ASTER_SIGNER_PRIVATE_KEY in AsterTradingModule/.env.",
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
                "message": "ASTER Pro API auth is working.",
                "wallet_balance": _to_float(usdt.get("walletBalance"), 0.0),
                "available_balance": _to_float(usdt.get("availableBalance"), 0.0),
                "can_read_account": isinstance(account, dict),
            }
        except AsterTradeError as exc:
            hints = []
            msg_l = str(exc).lower()
            if "permissions" in msg_l or exc.code in {-2015, -2014, -4013}:
                hints = [
                    "Verify ASTER_USER_ADDRESS, ASTER_SIGNER_ADDRESS, ASTER_SIGNER_PRIVATE_KEY are correct.",
                    "Check Pro API signer wallet permission in ASTER API wallet settings.",
                    "Ensure server time is synced; nonce drift beyond 10 seconds can fail.",
                ]
            elif "nonce" in msg_l:
                hints = [
                    "Nonce rejected. Check server time sync and ensure unique increasing nonce per request.",
                ]
            elif exc.status_code == 429:
                hints = ["Rate limit reached. Wait and retry."]
            else:
                hints = ["Check Pro API wallet status and network connectivity to ASTER."]
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
        settings_mode = str(payload.get("settings_mode", "normal")).strip().lower()
        leverage = int(_to_float(payload.get("leverage"), self.config.leverage))
        leverage = max(1, min(leverage, 125))
        margin_usdt = max(_to_float(payload.get("margin_usdt"), self.config.margin_per_trade_usdt), 0.0)
        notional_input = _to_float(payload.get("notional_usdt"), 0.0)
        notional = notional_input if notional_input > 0 else margin_usdt * leverage
        stop_loss_pct = max(_to_float(payload.get("stop_loss_pct"), self.config.stop_loss_pct), 0.0001)
        take_profit_pct = max(_to_float(payload.get("take_profit_pct"), self.config.take_profit_pct), 0.0)
        auto_stoploss_1pct = _to_bool(payload.get("auto_stoploss_1pct"), False)
        tp_mode = str(payload.get("tp_mode", "manual")).lower().strip()
        tp_rr = max(_to_float(payload.get("tp_rr"), 3.0), 0.1)

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

        open_positions_count = 0
        remaining_slots = self._manual_auto_max_positions
        margin_budget_per_slot = 0.0
        leverage_needed = float(leverage)
        usable_balance = 0.0

        if settings_mode == "manual_sl_auto_rest":
            manual_sl_price = _to_float(payload.get("manual_sl_price"), 0.0)
            risk_pct_total_capital = max(_to_float(payload.get("risk_pct_total_capital"), 0.0), 0.0)
            if risk_pct_total_capital > 5.0:
                raise AsterTradeError("Risk % on total capital cannot exceed 5%.")
            if manual_sl_price <= 0:
                raise AsterTradeError("Manual SL price is required for Manual SL, Auto the Rest mode.")
            if side == "BUY" and manual_sl_price >= entry_price:
                raise AsterTradeError("For LONG, manual SL price must be below entry price.")
            if side == "SELL" and manual_sl_price <= entry_price:
                raise AsterTradeError("For SHORT, manual SL price must be above entry price.")

            sl_distance_pct = abs(entry_price - manual_sl_price) / max(entry_price, 1e-9)
            if sl_distance_pct <= 0:
                raise AsterTradeError("Manual SL distance is too small.")

            overview = self.get_account_overview()
            account_equity = _to_float(overview.get("margin", {}).get("account_equity"), 0.0)
            available_balance = _to_float(overview.get("margin", {}).get("available_balance"), 0.0)
            if account_equity <= 0:
                raise AsterTradeError("Cannot resolve account equity for risk sizing.")
            if available_balance <= 0:
                raise AsterTradeError("Available balance is not enough for opening new position.")

            open_positions_count = self._count_open_positions()
            remaining_slots = self._manual_auto_max_positions - open_positions_count
            if remaining_slots <= 0:
                raise AsterTradeError("Cannot open more positions: max 3 positions reached.")

            usable_balance = max(available_balance * (1.0 - self._manual_auto_balance_buffer_ratio), 0.0)
            if usable_balance <= 0:
                raise AsterTradeError("Usable balance is too low after reserve buffer.")
            margin_budget_per_slot = usable_balance / max(remaining_slots, 1)
            if margin_budget_per_slot <= 0:
                raise AsterTradeError("Margin budget per slot is zero.")

            risk_usdt_target = account_equity * (risk_pct_total_capital / 100.0)
            notional = risk_usdt_target / sl_distance_pct
            stop_loss_pct = sl_distance_pct

            leverage_needed = notional / margin_budget_per_slot
            leverage = int(max(self._manual_auto_min_leverage, min(self._manual_auto_max_leverage, math.ceil(leverage_needed))))
            if leverage_needed > self._manual_auto_max_leverage + 1e-9:
                raise AsterTradeError("Cannot satisfy risk+SL within leverage limit x6 and remaining slots rule.")

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
        stop_price = round_to_tick(entry_price * sl_mult, str(filters.get("tick_size", "0.01")))
        if tp_mode == "rr":
            risk_distance = abs(entry_price - stop_price)
            if side == "BUY":
                take_profit_price = round_to_tick(entry_price + (tp_rr * risk_distance), str(filters.get("tick_size", "0.01")))
            else:
                take_profit_price = round_to_tick(entry_price - (tp_rr * risk_distance), str(filters.get("tick_size", "0.01")))
            if entry_price > 0:
                take_profit_pct = abs(take_profit_price - entry_price) / entry_price
        else:
            tp_mult = 1 + take_profit_pct if side == "BUY" else 1 - take_profit_pct
            take_profit_price = round_to_tick(entry_price * tp_mult, str(filters.get("tick_size", "0.01")))

        margin = computed_notional / max(leverage, 1)
        risk_usdt = computed_notional * stop_loss_pct
        warnings: List[str] = []
        if computed_notional < min_notional:
            warnings.append(f"Notional {computed_notional:.4f} is below exchange minNotional {min_notional:.4f}.")
        if quantity <= 0:
            warnings.append("Quantity resolved to zero after step-size rounding.")

        return {
            "settings_mode": settings_mode,
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
            "tp_mode": tp_mode,
            "tp_rr": tp_rr,
            "manual_auto_limits": {
                "max_positions": self._manual_auto_max_positions,
                "leverage_min": self._manual_auto_min_leverage,
                "leverage_max": self._manual_auto_max_leverage,
                "balance_buffer_ratio": self._manual_auto_balance_buffer_ratio,
            },
            "manual_auto_runtime": {
                "open_positions_count": open_positions_count,
                "remaining_slots": remaining_slots,
                "usable_balance": usable_balance,
                "margin_budget_per_slot": margin_budget_per_slot,
                "leverage_needed": leverage_needed,
                "leverage_chosen": leverage,
            },
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

    def move_stop_to_breakeven(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        symbol = self._normalize_symbol(payload.get("symbol"))
        position_side = str(payload.get("position_side", "")).upper().strip()
        dry_run = _to_bool(payload.get("dry_run"), self.config.dry_run)

        positions = self.client.get_positions(symbol)
        target = None
        for pos in positions:
            amt = _to_float(pos.get("positionAmt"), 0.0)
            if abs(amt) <= 1e-12:
                continue
            side = "LONG" if amt > 0 else "SHORT"
            if position_side and side != position_side:
                continue
            target = pos
            break

        if target is None:
            return {"success": False, "message": f"No open {symbol} position found."}

        amount = _to_float(target.get("positionAmt"), 0.0)
        side = "LONG" if amount > 0 else "SHORT"
        entry_price = _to_float(target.get("entryPrice"), 0.0)
        mark_price = _to_float(target.get("markPrice"), 0.0)
        unrealized_pnl = _to_float(target.get("unRealizedProfit"), 0.0)
        if entry_price <= 0 or mark_price <= 0:
            return {"success": False, "message": "Cannot resolve entry/mark price for break-even update."}

        in_profit = (mark_price > entry_price) if side == "LONG" else (mark_price < entry_price)
        if unrealized_pnl <= 0 and not in_profit:
            return {"success": False, "message": f"{symbol} {side} is not in profit yet; break-even move is disabled."}

        filters = self._symbol_filters(symbol)
        be_stop_price = round_to_tick(entry_price, str(filters.get("tick_size", "0.01")))

        close_side = "SELL" if side == "LONG" else "BUY"
        open_orders = self.client.get_open_orders(symbol)
        stop_orders_to_cancel: List[Dict[str, Any]] = []
        for order in open_orders:
            order_type = str(order.get("type", "")).upper().strip()
            order_side = str(order.get("side", "")).upper().strip()
            close_position_flag = str(order.get("closePosition", "")).lower().strip()
            if order_type != "STOP_MARKET":
                continue
            if order_side != close_side:
                continue
            if close_position_flag not in {"true", "1"}:
                continue
            stop_orders_to_cancel.append(order)

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "symbol": symbol,
                "position_side": side,
                "entry_price": entry_price,
                "mark_price": mark_price,
                "be_stop_price": be_stop_price,
                "cancel_stop_orders": [
                    {"orderId": item.get("orderId"), "stopPrice": item.get("stopPrice"), "side": item.get("side")} for item in stop_orders_to_cancel
                ],
                "new_stop_order": {
                    "symbol": symbol,
                    "side": close_side,
                    "type": "STOP_MARKET",
                    "stopPrice": be_stop_price,
                    "closePosition": "true",
                    "workingType": "MARK_PRICE",
                },
                "message": "DRY_RUN break-even request prepared.",
            }

        cancelled_items: List[Dict[str, Any]] = []
        for item in stop_orders_to_cancel:
            order_id = int(_to_float(item.get("orderId"), 0.0))
            if order_id <= 0:
                continue
            try:
                result = self.client.cancel_order(symbol, order_id)
                cancelled_items.append({"orderId": order_id, "success": True, "result": result})
            except Exception as exc:
                cancelled_items.append({"orderId": order_id, "success": False, "error": str(exc)})

        stop_payload = {
            "symbol": symbol,
            "side": close_side,
            "type": "STOP_MARKET",
            "stopPrice": be_stop_price,
            "closePosition": "true",
            "workingType": "MARK_PRICE",
            "newOrderRespType": "RESULT",
        }
        placed_stop = self.client.place_order(stop_payload)
        return {
            "success": True,
            "dry_run": False,
            "symbol": symbol,
            "position_side": side,
            "entry_price": entry_price,
            "mark_price": mark_price,
            "be_stop_price": be_stop_price,
            "cancelled_stop_orders": cancelled_items,
            "new_stop_order": placed_stop,
            "message": f"Moved {symbol} {side} stop-loss to break-even.",
        }

    def get_open_positions(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        selected_symbol = self._normalize_symbol(symbol) if symbol else "ALL"
        positions = self.client.get_positions(None if selected_symbol == "ALL" else selected_symbol)
        items = []
        for pos in positions:
            amt = _to_float(pos.get("positionAmt"), 0.0)
            if abs(amt) <= 1e-12:
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
                    if isinstance(row, dict):
                        items.append(row)
                return {"symbol": "ALL", "items": items}
        except Exception:
            pass

        dynamic_symbols: List[str]
        try:
            dynamic_symbols = self._discover_tradable_symbols()
        except Exception:
            dynamic_symbols = list(MANUAL_ALLOWED_SYMBOLS)

        for symbol_name in dynamic_symbols:
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
        selected_symbol = self._normalize_symbol(symbol) if symbol else "ALL"
        return {"symbol": selected_symbol, "items": self.client.get_income(None if selected_symbol == "ALL" else selected_symbol, safe_limit)}

    def get_closed_trades_history(self, limit: int = 200, symbol: Optional[str] = None) -> Dict[str, Any]:
        safe_limit = max(1, min(int(limit), 1000))
        selected_symbol = self._normalize_symbol(symbol) if symbol else "ALL"
        income_items = self.client.get_income(None if selected_symbol == "ALL" else selected_symbol, safe_limit)
        normalized: List[Dict[str, Any]] = []
        for row in income_items:
            if not isinstance(row, dict):
                continue
            symbol_name = str(row.get("symbol", "")).upper().strip() or "-"
            income_type = str(row.get("incomeType", "")).upper().strip() or "UNKNOWN"
            if income_type != "REALIZED_PNL":
                continue
            amount = _to_float(row.get("income"), 0.0)
            ts = int(_to_float(row.get("time"), 0.0))
            normalized.append(
                {
                    "time": ts,
                    "symbol": symbol_name,
                    "incomeType": income_type,
                    "realizedPnl": amount,
                    "asset": str(row.get("asset", "USDT")),
                    "tradeId": row.get("tradeId") or row.get("tranId") or row.get("info") or "-",
                    "raw": row,
                }
            )
        normalized.sort(key=lambda x: int(x.get("time", 0)))

        cum = 0.0
        curve: List[Dict[str, Any]] = []
        wins = 0
        losses = 0
        best = None
        worst = None
        for item in normalized:
            pnl = _to_float(item.get("realizedPnl"), 0.0)
            cum += pnl
            curve.append({"time": int(item.get("time", 0)), "equity": cum})
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1
            best = pnl if best is None else max(best, pnl)
            worst = pnl if worst is None else min(worst, pnl)

        return {
            "symbol": selected_symbol,
            "items": normalized,
            "curve": curve,
            "summary": {
                "total": len(normalized),
                "wins": wins,
                "losses": losses,
                "best": _to_float(best, 0.0),
                "worst": _to_float(worst, 0.0),
                "realized": cum,
            },
        }

    def get_config(self) -> Dict[str, Any]:
        data = asdict(self.config)
        data["allowed_symbols"] = list(MANUAL_ALLOWED_SYMBOLS)
        return data
