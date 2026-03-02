import json
import math
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .aster_client import AsterClient
from .bot_runner import BotRunner
from BoktoshiBotModule.strategy import (
    build_bollinger_series,
    build_ema_series,
    build_ma50_series,
    compute_regime_switch_snapshot,
    detect_ema_rsi_long_markers,
    detect_ma50_crossup_markers,
    detect_regime_markers,
    detect_regime_switch_long_markers,
)
from AsterTradingModule import AsterManualTradingService, AsterTradingConfig
from .schemas import CloseRecord, IntegrityReport, MetricsPayload
from .services.journal_app_service import JournalAppService
from .storage import (
    count_journal_entries,
    get_all_kv,
    get_equity_curve,
    get_journal_entries,
    get_kv,
    get_logs,
    get_signals,
    get_trades,
    init_db,
    replace_journal_entries,
    set_kv,
    trim_runtime_tables,
    update_journal_entry_annotations,
)


_PRICE_HINT_CACHE: Dict[str, Dict[str, float]] = {}
_JOURNAL_SYNC_LOCK = threading.Lock()
_JOURNAL_SYNC_THREAD: Optional[threading.Thread] = None
_PENDING_FINALIZE_STATE_KEY = "journal_pending_finalize_state"
_REMOTE_HISTORY_LAST_SYNC_KEY = "journal_remote_history_last_sync_ts"
_METRICS_LOCK = threading.Lock()
_APP_METRICS: Dict[str, Any] = {
    "requests": {},
    "journal_sync": {
        "runs": 0,
        "success": 0,
        "errors": 0,
        "last_duration_ms": 0.0,
        "last_success_ts": 0,
        "last_error": "",
    },
    "remote_history": {
        "fetch_runs": 0,
        "fetch_errors": 0,
        "last_fetch_count": 0,
        "last_fetch_ts": 0,
    },
}


def _record_request_metric(path: str, duration_ms: float) -> None:
    with _METRICS_LOCK:
        bucket = _APP_METRICS["requests"].setdefault(
            path,
            {"count": 0, "total_ms": 0.0, "avg_ms": 0.0, "max_ms": 0.0, "last_ms": 0.0},
        )
        bucket["count"] += 1
        bucket["total_ms"] += duration_ms
        bucket["avg_ms"] = bucket["total_ms"] / max(1, bucket["count"])
        bucket["max_ms"] = max(float(bucket.get("max_ms", 0.0)), duration_ms)
        bucket["last_ms"] = duration_ms


def _set_journal_sync_metric(success: bool, duration_ms: float, error: str = "") -> None:
    with _METRICS_LOCK:
        js = _APP_METRICS["journal_sync"]
        js["runs"] = int(js.get("runs", 0)) + 1
        js["last_duration_ms"] = float(duration_ms)
        if success:
            js["success"] = int(js.get("success", 0)) + 1
            js["last_success_ts"] = int(time.time())
            js["last_error"] = ""
        else:
            js["errors"] = int(js.get("errors", 0)) + 1
            js["last_error"] = str(error or "unknown")


def _set_remote_history_metric(count: int, had_error: bool) -> None:
    with _METRICS_LOCK:
        rh = _APP_METRICS["remote_history"]
        rh["fetch_runs"] = int(rh.get("fetch_runs", 0)) + 1
        if had_error:
            rh["fetch_errors"] = int(rh.get("fetch_errors", 0)) + 1
        rh["last_fetch_count"] = int(count)
        rh["last_fetch_ts"] = int(time.time())


def _load_env_file_if_exists(path: str) -> None:
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key:
                    continue
                if value and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
                    value = value[1:-1]
                os.environ.setdefault(key, value)
    except Exception:
        return


def _env_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_json(value: str) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_unix_seconds(value: Any, default: int = 0) -> int:
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(raw):
        return default
    if raw > 1e12:
        return int(raw / 1000)
    if raw > 1e10:
        return int(raw / 1000)
    return int(raw)


def _first_present(record: Dict[str, Any], names: List[str]) -> Any:
    for name in names:
        if name in record and record.get(name) not in (None, ""):
            return record.get(name)
    lower_map = {str(k).lower(): v for k, v in record.items()}
    for name in names:
        lowered = name.lower()
        if lowered in lower_map and lower_map.get(lowered) not in (None, ""):
            return lower_map.get(lowered)
    return None


def _first_float_optional(record: Dict[str, Any], names: List[str]) -> Optional[float]:
    value = _first_present(record, names)
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _normalize_symbol(value: Any) -> str:
    text = str(value or "").upper().strip()
    if not text:
        return "-"
    return text


def _normalize_side(value: Any) -> str:
    side = str(value or "").upper().strip()
    if side in {"BUY", "LONG"}:
        return "LONG"
    if side in {"SELL", "SHORT"}:
        return "SHORT"
    return side or "-"


def _normalize_coin(value: Any) -> str:
    text = _normalize_symbol(value)
    if text.endswith("USDT") and len(text) > 4:
        return text[:-4]
    return text


def _extract_mtc_id(text: str) -> str:
    for token in str(text or "").replace('"', " ").replace("'", " ").split():
        cleaned = token.strip().strip(",.:;()[]{}")
        if cleaned.startswith("mtc_"):
            return cleaned
    return ""


def _source_label(source: str, close_mode: str = "") -> str:
    s = str(source or "").strip().lower()
    mode = str(close_mode or "").strip().lower()
    if mode == "strategy_manual":
        return "Stra closed Manually"
    if s == "strategy_manual":
        return "Stra closed Manually"
    if "manual" in s:
        return "Manual"
    if "strategy" in s:
        return "Strategy"
    if s in {"manual", "manual_close"}:
        return "Manual"
    if s in {"strategy", "strategy_auto", "strategy_close"}:
        return "Strategy"
    return "Unknown"


def _infer_source_and_mode(raw_obj: Dict[str, Any], note_text: str = "") -> Dict[str, str]:
    source = str(_first_present(raw_obj, ["source", "owner"]) or "").strip().lower()
    close_mode = str(_first_present(raw_obj, ["close_mode", "closeMode", "mode"]) or "").strip().lower()
    hay = " ".join(
        [
            note_text,
            str(raw_obj.get("comment", "") or ""),
            str(raw_obj.get("message", "") or ""),
            str(raw_obj.get("note", "") or ""),
            str(raw_obj.get("notes", "") or ""),
        ]
    ).lower()

    if not close_mode and "manual close strategy" in hay:
        close_mode = "strategy_manual"
    if not source:
        if close_mode in {"strategy_auto", "strategy_manual"}:
            source = "strategy"
        elif "manual close" in hay or "manual force" in hay:
            source = "manual"
        elif "strategy exit" in hay or "strategy close" in hay:
            source = "strategy"
        elif "mapped manual position id" in hay:
            source = "manual"
    return {"source": source or "unknown", "close_mode": close_mode}


def _compute_size_boks(entry_price: Optional[float], qty: Optional[float], raw_obj: Optional[Dict[str, Any]] = None) -> Optional[float]:
    if entry_price is not None and qty is not None and entry_price > 0 and qty > 0:
        return entry_price * qty
    if isinstance(raw_obj, dict):
        notional = _first_float_optional(raw_obj, ["sizeUsd", "notional", "positionNotional", "size"])
        if notional is not None and notional > 0:
            return notional
        margin = _first_float_optional(raw_obj, ["margin", "usedMargin", "initialMargin"])
        leverage = _first_float_optional(raw_obj, ["leverage", "lev"])
        if margin is not None and leverage is not None and margin > 0 and leverage > 0:
            return margin * leverage
    return None


def _looks_closed_trade(record: Dict[str, Any]) -> bool:
    status_text = str(_first_present(record, ["status", "state", "action", "eventType", "type"]) or "").lower()
    if any(token in status_text for token in ["close", "closed", "realized", "settled", "exit"]):
        return True
    if str(_first_present(record, ["closeTime", "closedAt", "closed_at", "exitTime", "exitAt"]) or ""):
        return True
    if _first_float_optional(record, ["realizedPnl", "realizedPNL", "pnl", "profit", "netPnl", "closePnl", "income"]) is not None:
        return True
    return False


def _normalize_remote_closed_trades(items: List[Dict[str, Any]]) -> List[CloseRecord]:
    out: List[CloseRecord] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        if not _looks_closed_trade(raw):
            continue

        close_ts = _to_unix_seconds(
            _first_present(
                raw,
                ["closeTime", "closedAt", "closed_at", "exitTime", "updatedAt", "updateTime", "time", "ts", "timestamp"],
            ),
            0,
        )
        symbol = _normalize_symbol(_first_present(raw, ["symbol", "coin", "pair", "market"]))
        side = _normalize_side(_first_present(raw, ["side", "positionSide"]))
        qty = _first_float_optional(raw, ["qty", "quantity", "size", "positionSize", "amount", "filledQty", "executedQty"])
        entry_price = _first_float_optional(raw, ["entryPrice", "avgEntryPrice", "openPrice", "priceOpen"])
        exit_price = _first_float_optional(raw, ["closePrice", "exitPrice", "avgExitPrice", "price", "markPrice", "avgPrice"])
        realized = _first_float_optional(raw, ["realizedPnl", "realizedPNL", "realized", "pnl", "profit", "netPnl", "closePnl", "income"])
        commission = _first_float_optional(raw, ["commission", "feeCommission", "brokerFee"]) or 0.0
        fees = _first_float_optional(raw, ["fees", "fee", "fundingFee", "transactionFee"]) or 0.0
        net = _first_float_optional(raw, ["net", "netPnl", "netProfit"])
        leverage = _first_float_optional(raw, ["leverage", "lev"])
        margin = _first_float_optional(raw, ["margin", "usedMargin", "initialMargin", "notional"])
        if qty is None and entry_price and leverage and margin and leverage > 0 and entry_price > 0:
            qty = (margin * leverage) / entry_price
        if net is None and realized is not None:
            net = realized - commission - fees
        if realized is None:
            gross = _first_float_optional(raw, ["grossPnl", "gross", "profitLoss"])
            if gross is not None:
                realized = gross
            elif entry_price is not None and exit_price is not None and qty is not None:
                direction = 1 if side == "LONG" else -1
                realized = (exit_price - entry_price) * qty * direction
        if net is None and realized is not None:
            net = realized - commission - fees
        source_info = _infer_source_and_mode(raw)
        reason = str(_first_present(raw, ["reason", "closeReason", "eventReason", "message"]) or "").strip()
        size_boks = _compute_size_boks(entry_price, qty, raw)
        external_id = str(
            _first_present(raw, ["tradeId", "fillId", "id", "orderId", "positionId", "txId", "uuid"])
            or f"remote:{symbol}:{side}:{close_ts}:{len(out)}"
        )
        dedupe_key = f"{external_id}:{close_ts}:{symbol}:{side}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(
            {
                "external_id": external_id,
                "close_ts": close_ts,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "realized_pnl": realized,
                "commission": commission,
                "fees": fees,
                "net": net,
                "notes": "",
                "tags": "",
                "source": source_info.get("source", "unknown"),
                "close_mode": source_info.get("close_mode", ""),
                "source_label": _source_label(source_info.get("source", "unknown"), source_info.get("close_mode", "")),
                "close_reason": reason,
                "size_boks": size_boks,
                "recovered": 0,
                "raw": json.dumps(raw, ensure_ascii=True),
            }
        )
    out.sort(key=lambda item: (int(item.get("close_ts", 0) or 0), str(item.get("external_id", ""))), reverse=True)
    return out


def _extract_local_open_context() -> Dict[str, List[Dict[str, Any]]]:
    opens = [row for row in get_trades(DB_PATH, limit=2000) if str(row.get("action", "")).upper() == "OPEN"]
    context: Dict[str, List[Dict[str, Any]]] = {}
    for row in sorted(opens, key=lambda r: int(r.get("ts", 0) or 0)):
        coin = _normalize_coin(row.get("coin") or "")
        side = _normalize_side(row.get("side") or "")
        if coin in {"", "-"} or side in {"", "-"}:
            continue
        entry_price: Optional[float] = None
        qty: Optional[float] = None
        order_id = ""
        note_text = str(row.get("notes", "") or "")
        source = "manual"
        close_mode = ""
        try:
            raw = json.loads(note_text or "{}")
            if isinstance(raw, dict):
                entry_price = _first_float_optional(raw, ["estimatedEntry", "entryPrice", "avgEntryPrice", "price"])
                qty = _first_float_optional(raw, ["qty", "quantity", "size", "positionSize", "filledQty"])
                order_id = str(_first_present(raw, ["positionId", "orderId", "tradeId", "id"]) or "")
                position_snapshot: Dict[str, Any] = {}
                if isinstance(raw.get("position"), dict):
                    position_snapshot = dict(raw.get("position") or {})
                if entry_price is None:
                    entry_price = _first_float_optional(position_snapshot, ["entryPrice", "avgEntryPrice", "price"])
                if qty is None:
                    qty = _first_float_optional(position_snapshot, ["qty", "quantity", "positionAmt", "size"])
                source_info = _infer_source_and_mode(raw, note_text)
                source = source_info.get("source", "manual")
                close_mode = source_info.get("close_mode", "")
                if source == "unknown":
                    source = "manual"
        except Exception:
            entry_price = None
            qty = None
        margin = _safe_float(row.get("margin"), 0.0)
        leverage = _safe_float(row.get("leverage"), 0.0)
        if qty is None and entry_price and entry_price > 0 and leverage > 0 and margin > 0:
            qty = (margin * leverage) / entry_price
        size_boks = _compute_size_boks(entry_price, qty, {"margin": margin, "leverage": leverage})
        current_price = None
        mark_price = None
        try:
            raw_open = json.loads(note_text or "{}")
            if isinstance(raw_open, dict):
                close_snapshot = raw_open.get("close_snapshot") if isinstance(raw_open.get("close_snapshot"), dict) else {}
                if isinstance(close_snapshot, dict):
                    current_price = _first_float_optional(close_snapshot, ["currentPrice", "markPrice"])
                    mark_price = _first_float_optional(close_snapshot, ["markPrice", "currentPrice"])
        except Exception:
            current_price = None
            mark_price = None
        key = f"{coin}:{side}"
        context.setdefault(key, []).append(
            {
                "entry_price": entry_price,
                "qty": qty,
                "size_boks": size_boks,
                "ts": int(row.get("ts", 0) or 0),
                "order_id": order_id,
                "coin": row.get("coin"),
                "side": side,
                "source": source,
                "close_mode": close_mode,
                "margin": margin,
                "leverage": leverage,
                "current_price": current_price,
                "mark_price": mark_price,
                "raw_open": note_text,
            }
        )
    return context


def _current_open_position_ids() -> set[str]:
    kv = get_all_kv(DB_PATH)
    positions = _parse_json(kv.get("positions", ""))
    items: List[Dict[str, Any]] = []
    if isinstance(positions, dict):
        maybe = positions.get("positions", [])
        if isinstance(maybe, list):
            items = maybe
    elif isinstance(positions, list):
        items = positions
    out: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("positionId", "") or "").strip()
        if pid:
            out.add(pid)
    return out


def _closed_position_ids_from_local() -> set[str]:
    closed_ids: set[str] = set()
    closes = [row for row in get_trades(DB_PATH, limit=3000) if str(row.get("action", "")).upper() == "CLOSE"]
    for row in closes:
        note_text = str(row.get("notes", "") or "")
        try:
            raw = json.loads(note_text)
        except Exception:
            raw = {}
        if isinstance(raw, dict):
            pid = str(_first_present(raw, ["positionId", "orderId", "tradeId", "id"]) or "").strip()
            if pid:
                closed_ids.add(pid)
        mtc_id = _extract_mtc_id(note_text)
        if mtc_id:
            closed_ids.add(mtc_id)
    return closed_ids


def _pop_open_context_match(
    open_context: Dict[str, List[Dict[str, Any]]],
    key: str,
    close_position_id: str,
) -> Dict[str, Any]:
    if close_position_id:
        for _, rows in open_context.items():
            for i, item in enumerate(rows):
                if str(item.get("order_id", "") or "").strip() == close_position_id:
                    return rows.pop(i)
    rows = open_context.get(key) or []
    if rows:
        return rows.pop(0)
    return {}


def _build_fallback_closed_trades() -> List[CloseRecord]:
    fallback: List[Dict[str, Any]] = []
    open_context = _extract_local_open_context()
    closes = [row for row in get_trades(DB_PATH, limit=2000) if str(row.get("action", "")).upper() == "CLOSE"]
    for row in closes:
        ts = int(row.get("ts", 0) or 0)
        row_id = int(row.get("id", 0) or 0)
        coin = _normalize_coin(row.get("coin") or "ETH")
        side = _normalize_side(row.get("side") or "LONG")
        key = f"{coin}:{side}"
        pre_note = str(row.get("notes", "") or "")
        pre_raw: Dict[str, Any] = {}
        try:
            parsed = json.loads(pre_note or "{}")
            if isinstance(parsed, dict):
                pre_raw = parsed
        except Exception:
            pre_raw = {}
        close_position_id = str(_first_present(pre_raw, ["positionId", "orderId", "tradeId", "id"]) or "").strip()
        if not close_position_id:
            close_position_id = _extract_mtc_id(pre_note)
        matched = _pop_open_context_match(open_context, key, close_position_id)

        realized: Optional[float] = None
        exit_price: Optional[float] = None
        entry_price: Optional[float] = matched.get("entry_price") if isinstance(matched, dict) else None
        qty: Optional[float] = matched.get("qty") if isinstance(matched, dict) else None
        commission = 0.0
        fees = 0.0
        note_text = str(row.get("notes", "") or "")
        source = "unknown"
        close_mode = ""
        reason = ""
        raw_obj: Dict[str, Any] = {}
        try:
            raw = json.loads(note_text or "{}")
            if isinstance(raw, dict):
                raw_obj = raw
                realized = _first_float_optional(raw, ["realizedPnl", "realized", "pnl", "profit", "netPnl", "income"])
                exit_price = _first_float_optional(raw, ["closePrice", "exitPrice", "price", "avgExitPrice", "avgPrice"])
                if entry_price is None:
                    entry_price = _first_float_optional(raw, ["entryPrice", "openPrice", "avgEntryPrice"])
                if qty is None:
                    qty = _first_float_optional(raw, ["qty", "quantity", "size", "positionSize", "filledQty", "executedQty"])
                close_snapshot = raw.get("close_snapshot") if isinstance(raw.get("close_snapshot"), dict) else {}
                if entry_price is None and isinstance(close_snapshot, dict):
                    entry_price = _first_float_optional(close_snapshot, ["entryPrice", "entry", "avgEntryPrice"])
                if exit_price is None and isinstance(close_snapshot, dict):
                    exit_price = _first_float_optional(close_snapshot, ["currentPrice", "markPrice", "closePrice", "exitPrice"])
                if qty is None and isinstance(close_snapshot, dict):
                    qty = _first_float_optional(close_snapshot, ["qty", "quantity", "positionAmt", "size"])
                if realized is None and isinstance(close_snapshot, dict):
                    realized = _first_float_optional(close_snapshot, ["realizedPnl", "unrealizedPnl", "pnl"])
                commission = _first_float_optional(raw, ["commission", "feeCommission"]) or 0.0
                fees = _first_float_optional(raw, ["fees", "fee", "fundingFee"]) or 0.0
                source_info = _infer_source_and_mode(raw, note_text)
                source = source_info.get("source", "unknown")
                close_mode = source_info.get("close_mode", "")
                reason = str(_first_present(raw, ["reason", "closeReason", "eventReason", "message", "note"]) or "")
        except Exception:
            raw_obj = {}

        if source == "unknown":
            source_info = _infer_source_and_mode(raw_obj, note_text)
            source = source_info.get("source", "unknown")
            close_mode = source_info.get("close_mode", close_mode)
        if source == "unknown" and isinstance(matched, dict):
            source = str(matched.get("source", "unknown") or "unknown")
        if not reason:
            reason = note_text

        if realized is None and entry_price is not None and exit_price is not None and qty is not None:
            direction = 1 if side == "LONG" else -1
            realized = (exit_price - entry_price) * qty * direction

        if exit_price is None and isinstance(matched, dict):
            exit_price = _first_float_optional(matched, ["current_price", "mark_price"])
        if entry_price is None and isinstance(matched, dict):
            entry_price = _first_float_optional(matched, ["entry_price"])

        size_boks = _compute_size_boks(entry_price, qty, raw_obj)
        if size_boks is None and isinstance(matched, dict):
            size_boks = matched.get("size_boks")
        if size_boks is None:
            margin = _safe_float(row.get("margin"), 0.0)
            leverage = _safe_float(row.get("leverage"), 0.0)
            if margin > 0 and leverage > 0:
                size_boks = margin * leverage

        close_position_id = str(_first_present(raw_obj, ["positionId", "orderId", "tradeId", "id"]) or "").strip() or close_position_id
        if not close_position_id:
            close_position_id = _extract_mtc_id(note_text)

        symbol = _normalize_symbol(row.get("coin") or "ETH")
        if close_position_id:
            external_id = f"local-close:{close_position_id}"
        elif row_id > 0:
            external_id = f"local-close-row:{row_id}"
        else:
            external_id = f"local-close:{ts}:{symbol}:{side}"
        fallback.append(
            {
                "external_id": external_id,
                "close_ts": ts,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "realized_pnl": realized,
                "commission": commission,
                "fees": fees,
                "net": (realized - commission - fees) if realized is not None else None,
                "notes": note_text,
                "tags": "",
                "source": "strategy_manual" if close_mode == "strategy_manual" else source,
                "close_mode": close_mode,
                "source_label": _source_label(source, close_mode),
                "close_reason": reason,
                "size_boks": size_boks,
                "recovered": 0,
                "raw": json.dumps(row, ensure_ascii=True),
            }
        )

    active_position_ids = _current_open_position_ids()
    closed_ids = _closed_position_ids_from_local()
    for _, open_rows in open_context.items():
        for open_row in open_rows:
            pid = str(open_row.get("order_id", "") or "").strip()
            if not pid:
                continue
            if pid in active_position_ids or pid in closed_ids:
                continue
            source = str(open_row.get("source", "manual") or "manual")
            open_ts = int(open_row.get("ts", 0) or 0)
            recovered_ts = open_ts + 1 if open_ts > 0 else int(time.time())
            coin = _normalize_symbol(open_row.get("coin") or "ETH")
            side = _normalize_side(open_row.get("side") or "LONG")
            fallback.append(
                {
                    "external_id": f"recovered:{pid}",
                    "close_ts": recovered_ts,
                    "symbol": coin,
                    "side": side,
                    "qty": open_row.get("qty"),
                    "entry_price": open_row.get("entry_price"),
                    "exit_price": None,
                    "realized_pnl": None,
                    "commission": 0.0,
                    "fees": 0.0,
                    "net": None,
                    "notes": "Recovered close (missing close callback)",
                    "tags": "recovered",
                    "source": source,
                    "close_mode": "external_recovered",
                    "source_label": _source_label(source, "external_recovered"),
                    "close_reason": "External close detected while app was offline or without callback",
                    "size_boks": open_row.get("size_boks"),
                    "recovered": 1,
                    "raw": json.dumps(
                        {
                            "positionId": pid,
                            "origin": "recovered_from_stale",
                            "open_ts": open_ts,
                            "symbol": coin,
                            "side": side,
                        },
                        ensure_ascii=True,
                    ),
                }
            )
    return fallback


def _build_closed_trade_snapshot(fetch_live_history: bool = True) -> List[CloseRecord]:
    kv = get_all_kv(DB_PATH)
    remote = _parse_json(kv.get("last_history", "[]"))
    remote_items = remote if isinstance(remote, list) else []
    live_items: List[Dict[str, Any]] = []
    fetch_had_error = False
    if fetch_live_history:
        try:
            for offset in (0, 100, 200, 300):
                response = runner.client.get_history(limit=100, offset=offset)
                chunk = response.get("history", response.get("items", response))
                if not isinstance(chunk, list) or not chunk:
                    break
                dict_chunk = [item for item in chunk if isinstance(item, dict)]
                live_items.extend(dict_chunk)
                if len(chunk) < 100:
                    break
        except Exception:
            live_items = []
            fetch_had_error = True
        _set_remote_history_metric(len(live_items), fetch_had_error)

    if live_items:
        remote_items = live_items
        set_kv(DB_PATH, "last_history", json.dumps(live_items))
    normalized = _normalize_remote_closed_trades(remote_items)
    fallback = _build_fallback_closed_trades()
    if not normalized:
        return fallback

    merged: Dict[str, Dict[str, Any]] = {str(item.get("external_id", "")): item for item in normalized if item.get("external_id")}
    for item in fallback:
        key = str(item.get("external_id", ""))
        if key and key not in merged:
            merged[key] = item
    out = list(merged.values())
    out.sort(key=lambda item: (int(item.get("close_ts", 0) or 0), str(item.get("external_id", ""))), reverse=True)
    return out


def _sync_journal_snapshot(force: bool = False) -> None:
    start = time.perf_counter()
    now = int(time.time())
    last_sync = int(get_kv(DB_PATH, "journal_last_sync_ts", "0") or 0)
    if not force and (now - last_sync) < 20:
        _set_journal_sync_metric(True, (time.perf_counter() - start) * 1000)
        return
    try:
        existing_rows = _decorate_journal_rows(get_journal_entries(DB_PATH, limit=2000, offset=0))
        retry_plan = _compute_pending_finalize_plan(existing_rows, now)
        due_ids = retry_plan.get("due_ids", []) if isinstance(retry_plan, dict) else []

        last_remote_sync = int(get_kv(DB_PATH, _REMOTE_HISTORY_LAST_SYNC_KEY, "0") or 0)
        should_fetch_live = bool(force or due_ids or (now - last_remote_sync) >= 120)

        items = _build_closed_trade_snapshot(fetch_live_history=should_fetch_live)
        if not items:
            _set_journal_sync_metric(True, (time.perf_counter() - start) * 1000)
            return
        replace_journal_entries(DB_PATH, items, now)
        set_kv(DB_PATH, "journal_last_sync_ts", str(now))
        if should_fetch_live:
            set_kv(DB_PATH, _REMOTE_HISTORY_LAST_SYNC_KEY, str(now))

        updated_rows = _decorate_journal_rows(get_journal_entries(DB_PATH, limit=2000, offset=0))
        _finalize_pending_retry_after_sync(
            retry_plan.get("state", {}) if isinstance(retry_plan, dict) else {},
            due_ids,
            updated_rows,
            now,
        )
        _set_journal_sync_metric(True, (time.perf_counter() - start) * 1000)
    except Exception as exc:
        _set_journal_sync_metric(False, (time.perf_counter() - start) * 1000, str(exc))
        raise


def _run_journal_sync_task(force: bool = False) -> None:
    with _JOURNAL_SYNC_LOCK:
        _sync_journal_snapshot(force=force)
        if force:
            try:
                _decorate_journal_rows(get_journal_entries(DB_PATH, limit=80, offset=0), allow_network_hints=True)
            except Exception:
                pass


def _trigger_journal_sync(force: bool = False, background: bool = True) -> bool:
    global _JOURNAL_SYNC_THREAD
    if background:
        if _JOURNAL_SYNC_THREAD and _JOURNAL_SYNC_THREAD.is_alive():
            return False
        worker = threading.Thread(target=_run_journal_sync_task, args=(force,), daemon=True)
        _JOURNAL_SYNC_THREAD = worker
        worker.start()
        return True
    _run_journal_sync_task(force=force)
    return True


def _symbol_to_usdt(symbol: str) -> str:
    s = str(symbol or "").upper().strip()
    if not s:
        return ""
    return s if s.endswith("USDT") else f"{s}USDT"


def _position_id_from_row(row: Dict[str, Any]) -> str:
    ext = str(row.get("external_id", "") or "")
    if ext.startswith("local-close:"):
        pid = ext.split(":", 1)[1].strip()
        if pid and not pid.startswith("row:"):
            return pid
    if ext.startswith("recovered:"):
        pid = ext.split(":", 1)[1].strip()
        if pid:
            return pid
    raw_obj: Dict[str, Any] = {}
    try:
        parsed = json.loads(str(row.get("raw", "") or "{}"))
        if isinstance(parsed, dict):
            raw_obj = parsed
    except Exception:
        raw_obj = {}
    note_text = str(row.get("notes", "") or "")
    if "notes" in raw_obj:
        note_text = str(raw_obj.get("notes", "") or note_text)
    pid = str(_first_present(raw_obj, ["positionId", "orderId", "tradeId", "id"]) or "").strip()
    if pid:
        return pid
    return _extract_mtc_id(note_text)


def _load_pending_finalize_state() -> Dict[str, Dict[str, Any]]:
    raw = get_kv(DB_PATH, _PENDING_FINALIZE_STATE_KEY, "{}")
    obj = _parse_json(raw)
    return obj if isinstance(obj, dict) else {}


def _save_pending_finalize_state(state: Dict[str, Dict[str, Any]]) -> None:
    set_kv(DB_PATH, _PENDING_FINALIZE_STATE_KEY, json.dumps(state, ensure_ascii=True))


def _clear_stale_pending_finalize_state(max_age_sec: int = 86400) -> Dict[str, Any]:
    now = int(time.time())
    state = _load_pending_finalize_state()
    before = len(state)
    next_state: Dict[str, Dict[str, Any]] = {}
    for pid, item in state.items():
        if not isinstance(item, dict):
            continue
        first_seen = int(item.get("first_seen", now) or now)
        if now - first_seen > max(60, int(max_age_sec)):
            continue
        next_state[pid] = item
    _save_pending_finalize_state(next_state)
    return {"before": before, "after": len(next_state), "removed": max(0, before - len(next_state))}


def _compute_pending_finalize_plan(existing_rows: List[Dict[str, Any]], now: int) -> Dict[str, Any]:
    state = _load_pending_finalize_state()
    pending_ids: List[str] = []
    for row in existing_rows:
        if int(row.get("pending", 0) or 0) != 1:
            continue
        pid = _position_id_from_row(row)
        if pid:
            pending_ids.append(pid)

    pending_set = set(pending_ids)
    for pid in list(state.keys()):
        if pid not in pending_set:
            state.pop(pid, None)

    due_ids: List[str] = []
    for pid in pending_set:
        item = state.get(pid, {}) if isinstance(state.get(pid), dict) else {}
        first_seen = int(item.get("first_seen", now) or now)
        attempts = int(item.get("attempts", 0) or 0)
        next_ts = int(item.get("next_ts", now) or now)
        if now - first_seen > 86400:
            state.pop(pid, None)
            continue
        if now >= next_ts:
            due_ids.append(pid)
        state[pid] = {
            "first_seen": first_seen,
            "attempts": attempts,
            "next_ts": next_ts,
            "last_seen": now,
        }

    _save_pending_finalize_state(state)
    return {"state": state, "due_ids": due_ids, "pending_ids": list(pending_set)}


def _finalize_pending_retry_after_sync(
    prior_state: Dict[str, Dict[str, Any]],
    due_ids: List[str],
    updated_rows: List[Dict[str, Any]],
    now: int,
) -> None:
    unresolved: set[str] = set()
    for row in updated_rows:
        if int(row.get("pending", 0) or 0) != 1:
            continue
        pid = _position_id_from_row(row)
        if pid:
            unresolved.add(pid)

    next_state: Dict[str, Dict[str, Any]] = {}
    due_set = set(due_ids)
    for pid in unresolved:
        prev = prior_state.get(pid, {}) if isinstance(prior_state.get(pid), dict) else {}
        attempts = int(prev.get("attempts", 0) or 0)
        first_seen = int(prev.get("first_seen", now) or now)
        if pid in due_set:
            attempts += 1
            delay = min(900, int(15 * (2 ** min(attempts, 6))))
            next_ts = now + delay
        else:
            next_ts = int(prev.get("next_ts", now + 30) or (now + 30))
        if now - first_seen > 86400:
            continue
        next_state[pid] = {
            "first_seen": first_seen,
            "attempts": attempts,
            "next_ts": next_ts,
            "last_seen": now,
        }
    _save_pending_finalize_state(next_state)


def _recent_market_price_hints(rows: List[Dict[str, Any]], allow_network: bool = False) -> Dict[str, float]:
    now = int(time.time())
    symbols: List[str] = []
    for row in sorted(rows, key=lambda item: int(item.get("close_ts", 0) or 0), reverse=True)[:40]:
        if row.get("realized_pnl") not in (None, ""):
            continue
        if row.get("display_exit_price") not in (None, ""):
            continue
        symbol = _symbol_to_usdt(str(row.get("symbol", "") or ""))
        if symbol and symbol not in symbols:
            symbols.append(symbol)
        if len(symbols) >= 2:
            break

    hints: Dict[str, float] = {}
    for symbol in symbols:
        cache = _PRICE_HINT_CACHE.get(symbol)
        if cache and (now - int(cache.get("ts", 0))) <= 300:
            hints[symbol] = float(cache.get("price", 0) or 0)
            continue
        if cache:
            stale_price = float(cache.get("price", 0) or 0)
            if stale_price > 0:
                hints[symbol] = stale_price
                continue
        if not allow_network:
            continue
        try:
            overview = aster.get_overview(symbol=symbol)
            price = _safe_float(overview.get("markPrice") or overview.get("lastPrice"), 0.0)
            if price > 0:
                hints[symbol] = price
                _PRICE_HINT_CACHE[symbol] = {"ts": float(now), "price": float(price)}
        except Exception:
            continue
    return hints


def _decorate_journal_row(row: Dict[str, Any], price_hints: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    out = dict(row)
    raw_obj: Dict[str, Any] = {}
    try:
        parsed = json.loads(str(row.get("raw", "") or "{}"))
        if isinstance(parsed, dict):
            raw_obj = parsed
    except Exception:
        raw_obj = {}

    source = str(row.get("source", "") or "").strip().lower()
    close_mode = str(row.get("close_mode", "") or "").strip().lower()
    source_info = _infer_source_and_mode(raw_obj, str(row.get("notes", "") or ""))
    inferred_source = source_info.get("source", "")
    inferred_mode = source_info.get("close_mode", "")
    if (not source or source == "unknown") and inferred_source:
        source = inferred_source
    if (not close_mode) and inferred_mode:
        close_mode = inferred_mode
    if source == "strategy_manual" and not close_mode:
        close_mode = "strategy_manual"
    if source == "unknown" and str(raw_obj.get("origin", "")).lower().startswith("recovered"):
        source = "manual"

    out["source"] = source
    out["close_mode"] = close_mode
    out["source_label"] = _source_label(source, close_mode)

    entry_price = _first_float_optional(out, ["entry_price"])
    qty = _first_float_optional(out, ["qty"])
    size_boks = _first_float_optional(out, ["size_boks"])
    if size_boks is None:
        size_boks = _compute_size_boks(entry_price, qty, raw_obj)
    out["size_boks"] = size_boks

    if out.get("close_reason") in (None, ""):
        out["close_reason"] = str(_first_present(raw_obj, ["reason", "closeReason", "eventReason", "message"]) or "")
    if out.get("recovered") in (None, ""):
        out["recovered"] = 1 if str(raw_obj.get("origin", "")).lower().startswith("recovered") else 0
    if out.get("recovered") and not out.get("close_reason"):
        out["close_reason"] = "External close detected while app was offline or without callback"

    exit_price = _first_float_optional(out, ["exit_price"])
    realized = _first_float_optional(out, ["realized_pnl"])
    estimated_exit: Optional[float] = None
    estimated_realized: Optional[float] = None

    close_snapshot = raw_obj.get("close_snapshot") if isinstance(raw_obj.get("close_snapshot"), dict) else {}
    if exit_price is None and isinstance(close_snapshot, dict):
        estimated_exit = _first_float_optional(close_snapshot, ["currentPrice", "markPrice", "closePrice", "exitPrice"])

    if exit_price is None and estimated_exit is None and price_hints:
        hinted = price_hints.get(_symbol_to_usdt(str(out.get("symbol", "") or "")), 0.0)
        if hinted > 0:
            estimated_exit = hinted

    if realized is None and isinstance(close_snapshot, dict):
        estimated_realized = _first_float_optional(close_snapshot, ["realizedPnl", "unrealizedPnl", "pnl"])

    if realized is None and estimated_realized is None:
        px_for_est = exit_price if exit_price is not None else estimated_exit
        if entry_price is not None and px_for_est is not None and px_for_est > 0:
            qty_for_est = qty
            if qty_for_est is None and size_boks is not None and entry_price > 0:
                qty_for_est = size_boks / entry_price
            if qty_for_est is not None:
                direction = 1 if str(out.get("side", "")).upper() == "LONG" else -1
                estimated_realized = (px_for_est - entry_price) * qty_for_est * direction

    out["estimated_exit_price"] = estimated_exit
    out["estimated_realized_pnl"] = estimated_realized
    out["exit_estimated"] = 1 if (exit_price is None and estimated_exit is not None) else 0
    out["realized_estimated"] = 1 if (realized is None and estimated_realized is not None) else 0
    out["display_exit_price"] = exit_price if exit_price is not None else estimated_exit
    out["display_realized_pnl"] = realized if realized is not None else estimated_realized
    out["pending"] = 1 if (out.get("recovered") != 1 and out.get("realized_pnl") in (None, "")) else 0
    persisted_state = str(out.get("finalization_state", "") or "").upper().strip()
    persisted_source = str(out.get("estimated_source", "") or "").lower().strip()
    if persisted_state in {"PENDING", "ESTIMATED", "FINALIZED"}:
        out["finalization_state"] = persisted_state
        out["estimated_source"] = persisted_source if persisted_source else "none"
    else:
        if realized is not None:
            out["finalization_state"] = "FINALIZED"
            out["estimated_source"] = "none"
        elif estimated_realized is not None:
            out["finalization_state"] = "ESTIMATED"
            if isinstance(close_snapshot, dict) and _first_float_optional(close_snapshot, ["realizedPnl", "unrealizedPnl", "pnl"]) is not None:
                out["estimated_source"] = "snapshot"
            elif estimated_exit is not None and estimated_exit == _first_float_optional(out, ["display_exit_price"]):
                out["estimated_source"] = "market_hint"
            else:
                out["estimated_source"] = "formula"
        else:
            out["finalization_state"] = "PENDING"
            out["estimated_source"] = "none"
    return out


def _decorate_journal_rows(rows: List[Dict[str, Any]], allow_network_hints: bool = False) -> List[Dict[str, Any]]:
    hints = _recent_market_price_hints(rows, allow_network=allow_network_hints)
    return [_decorate_journal_row(row, hints) for row in rows]


def _summarize_journal_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    fills = len(rows)
    total_size = 0.0
    total_commission = 0.0
    total_fees = 0.0
    pnl_values: List[float] = []

    for row in rows:
        total_size += _safe_float(row.get("size_boks"), 0.0)
        total_commission += _safe_float(row.get("commission"), 0.0)
        total_fees += _safe_float(row.get("fees"), 0.0)
        display_pnl = _first_float_optional(row, ["display_realized_pnl", "realized_pnl", "estimated_realized_pnl"])
        if display_pnl is not None:
            pnl_values.append(display_pnl)

    gross = float(sum(pnl_values)) if pnl_values else 0.0
    best = float(max(pnl_values)) if pnl_values else 0.0
    worst = float(min(pnl_values)) if pnl_values else 0.0
    wins = sum(1 for v in pnl_values if v > 0)
    losses = sum(1 for v in pnl_values if v < 0)

    return {
        "fills": int(fills),
        "qty": float(total_size),
        "size_boks": float(total_size),
        "gross": float(gross),
        "commission": float(total_commission),
        "fees": float(total_fees),
        "net": float(gross),
        "best": float(best),
        "worst": float(worst),
        "wins": int(wins),
        "losses": int(losses),
    }


def _journal_integrity_report(rows: List[Dict[str, Any]], now: Optional[int] = None) -> IntegrityReport:
    ts_now = int(now or time.time())
    by_external: Dict[str, int] = {}
    stale_pending: List[Dict[str, Any]] = []
    missing_core: List[Dict[str, Any]] = []

    for row in rows:
        ext = str(row.get("external_id", "") or "")
        if ext:
            by_external[ext] = by_external.get(ext, 0) + 1

        close_ts = int(row.get("close_ts", 0) or 0)
        is_pending = int(row.get("pending", 0) or 0) == 1
        if is_pending and close_ts > 0 and (ts_now - close_ts) > 3600:
            stale_pending.append(
                {
                    "external_id": ext,
                    "symbol": row.get("symbol"),
                    "age_sec": ts_now - close_ts,
                    "source_label": row.get("source_label"),
                }
            )

        entry_missing = row.get("entry_price") in (None, "")
        size_missing = row.get("size_boks") in (None, "")
        source_missing = str(row.get("source_label", "") or "").strip() in {"", "Unknown"}
        if entry_missing or size_missing or source_missing:
            missing_core.append(
                {
                    "external_id": ext,
                    "symbol": row.get("symbol"),
                    "entry_missing": bool(entry_missing),
                    "size_missing": bool(size_missing),
                    "source_missing": bool(source_missing),
                }
            )

    duplicate_external_ids = [k for k, v in by_external.items() if v > 1]
    return {
        "checked_at": ts_now,
        "total_rows": len(rows),
        "duplicate_external_id_count": len(duplicate_external_ids),
        "duplicate_external_ids": duplicate_external_ids[:50],
        "stale_pending_count": len(stale_pending),
        "stale_pending_examples": stale_pending[:50],
        "missing_core_fields_count": len(missing_core),
        "missing_core_examples": missing_core[:50],
    }


_load_env_file_if_exists("BoktoshiBotModule/.env")
_load_env_file_if_exists("AsterTradingModule/.env")


DB_PATH = os.getenv("DB_PATH", "/app/data/bot.db")
MTC_API_KEY = os.getenv("MTC_API_KEY", "")
MTC_BASE_URL = os.getenv("MTC_BASE_URL", "https://boktoshi.com/api/v1")
BOT_NAME = os.getenv("BOT_NAME", "zzCatBoktoshiTradingBot")
BOT_DESC = os.getenv("BOT_DESC", "ETHUSDT MA50(4H) long-only bot")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "20"))
DRY_RUN = _env_bool(os.getenv("DRY_RUN", "true"), True)
STRATEGY_AUTO_START = _env_bool(os.getenv("STRATEGY_AUTO_START", "false"), False)

TRADE_COIN = "ETHUSDT"
MARGIN_BOKS = float(os.getenv("MARGIN_BOKS", "100"))
LEVERAGE = float(os.getenv("LEVERAGE", "5"))
SL_CAPITAL_PCT = float(os.getenv("SL_CAPITAL_PCT", "0.01"))
TP_CAPITAL_PCT = float(os.getenv("TP_CAPITAL_PCT", "0.03"))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "5"))
ASTER_BASE_URL = os.getenv("ASTER_BASE_URL", "https://www.asterdex.com")
PINNED_ASTER_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "TAOUSDT", "XRPUSDT", "HYPEUSDT", "PUMPUSDT", "DOGEUSDT"]
OVERLAY_TOP_SYMBOL_LIMIT = 10

@asynccontextmanager
async def app_lifespan(_app) -> AsyncIterator[None]:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    init_db(DB_PATH)
    trim_runtime_tables(DB_PATH)
    runner.load_runtime_settings_from_db()
    runner.start()
    _trigger_journal_sync(force=True, background=True)
    try:
        yield
    finally:
        runner.stop()


app = FastAPI(title="zzCatBoktoshiTradingBot", lifespan=app_lifespan)
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
aster = AsterClient(base_url=ASTER_BASE_URL)
aster_trading = AsterManualTradingService(AsterTradingConfig())


@app.middleware("http")
async def request_timing_middleware(request: Request, call_next):  # type: ignore[override]
    t0 = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - t0) * 1000
    path = str(request.url.path)
    if path.startswith("/api/"):
        _record_request_metric(path, duration_ms)
    return response

runner = BotRunner(
    db_path=DB_PATH,
    base_url=MTC_BASE_URL,
    api_key=MTC_API_KEY,
    poll_seconds=POLL_SECONDS,
    dry_run=DRY_RUN,
    bot_name=BOT_NAME,
    bot_desc=BOT_DESC,
    trade_coin=TRADE_COIN,
    margin_boks=MARGIN_BOKS,
    leverage=LEVERAGE,
    sl_capital_pct=SL_CAPITAL_PCT,
    tp_capital_pct=TP_CAPITAL_PCT,
    max_positions=MAX_POSITIONS,
    strategy_auto_start=STRATEGY_AUTO_START,
)

journal_service = JournalAppService(
    get_all_kv=lambda: get_all_kv(DB_PATH),
    parse_json=lambda v: _parse_json(v),
    trigger_sync=lambda force, background: _trigger_journal_sync(force=force, background=background),
    get_trades=lambda limit: get_trades(DB_PATH, limit=limit),
    get_journal_entries=lambda limit, offset, search: get_journal_entries(DB_PATH, limit=limit, offset=offset, search=search),
    count_journal_entries=lambda search: count_journal_entries(DB_PATH, search=search),
    decorate_rows=lambda rows: _decorate_journal_rows(rows),
    summarize_rows=lambda rows: _summarize_journal_rows(rows),
    integrity_report=lambda rows: _journal_integrity_report(rows),
    load_pending_state=lambda: _load_pending_finalize_state(),
    clear_stale_state=lambda max_age_sec: _clear_stale_pending_finalize_state(max_age_sec=max_age_sec),
)


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/manual", response_class=HTMLResponse)
def manual_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("manual.html", {"request": request})


@app.get("/journal", response_class=HTMLResponse)
def journal_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("journal.html", {"request": request})


@app.get("/strategy-summary", response_class=HTMLResponse)
def strategy_summary_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("strategy_summary.html", {"request": request})


@app.get("/fredtrade-migration-report", response_class=HTMLResponse)
def fredtrade_migration_report_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("fredtrade_migration_report.html", {"request": request})


@app.get("/chatlog", response_class=HTMLResponse)
def chatlog_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("chatlog.html", {"request": request})


@app.get("/aster-trading", response_class=HTMLResponse)
def aster_trading_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("aster_trading.html", {"request": request})


@app.get("/eth-chart", response_class=HTMLResponse)
def eth_chart_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("eth_chart.html", {"request": request})


@app.get("/aster-chart", response_class=HTMLResponse)
def aster_chart_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("eth_chart.html", {"request": request})


@app.get("/api/status")
def status() -> Dict[str, Any]:
    kv = get_all_kv(DB_PATH)
    runtime_settings = runner.get_runtime_settings()
    active_strategy = runner.get_active_strategy()
    enabled_strategies = runner.get_enabled_strategies()
    strategy_map = {item["id"]: item for item in runner.list_strategies()}
    strategy_info = strategy_map.get(active_strategy, strategy_map.get(runner.STRATEGY_MA50, {}))
    is_ema = active_strategy == runner.STRATEGY_EMA_RSI
    is_regime = active_strategy == runner.STRATEGY_REGIME_SWITCH
    ema_runtime_raw = _parse_json(kv.get(runner.EMA_STATE_KEY, ""))
    ema_runtime = None
    if isinstance(ema_runtime_raw, dict):
        if "position_id" in ema_runtime_raw:
            ema_runtime = ema_runtime_raw
        else:
            slot = f"{active_strategy}:{TRADE_COIN}"
            slot_value = ema_runtime_raw.get(slot)
            if isinstance(slot_value, dict):
                ema_runtime = slot_value
    return {
        "bot_status": kv.get("bot_status", "unknown"),
        "strategy_state": "paused" if runner.is_strategy_paused() else "running",
        "last_tick": kv.get("last_tick", ""),
        "account_ok": kv.get("account_ok", ""),
        "dry_run": DRY_RUN,
        "trade_pair": TRADE_COIN,
        "trade_coin": runner.trade_coin,
        "strategy": {
            "id": active_strategy,
            "name": strategy_info.get("label", active_strategy),
            "mode": runner.get_strategy_mode(),
            "enabled_ids": enabled_strategies,
            "symbols": runner.STRATEGY_TARGET_SYMBOLS,
            "entry": strategy_info.get("entry", ""),
            "short_enabled": False,
            "margin_boks": runtime_settings["margin_boks"],
            "leverage": runtime_settings["leverage"],
            "sl_capital_pct": runtime_settings["sl_capital_pct"],
            "tp_capital_pct": runtime_settings["tp_capital_pct"],
            "risk_mode": "REGIME_SWITCH_RISK" if is_regime else ("R_MULTIPLE_TRAILING" if is_ema else "CAPITAL_PCT_FIXED"),
            "tp_r_multiple": 2 if is_ema else None,
            "trailing_activation_r": 1 if is_ema else None,
            "ema_runtime": ema_runtime if is_ema else None,
            "regime_runtime": runner.get_regime_runtime() if is_regime else None,
        },
        "last_signal": _parse_json(kv.get("last_signal", "")),
    }


@app.get("/api/account")
def account() -> Dict[str, Any]:
    kv = get_all_kv(DB_PATH)
    return {"account": _parse_json(kv.get("account", "")), "notices": _parse_json(kv.get("notices", "[]"))}


@app.get("/api/open-positions")
def open_positions() -> Dict[str, Any]:
    kv = get_all_kv(DB_PATH)
    positions = _parse_json(kv.get("positions", ""))
    if isinstance(positions, dict):
        items = positions.get("positions", [])
    elif isinstance(positions, list):
        items = positions
    else:
        items = []
    grouped = runner.classify_open_positions(items)
    return {
        "items": items,
        "strategy_position": grouped.get("strategy_position"),
        "strategy_positions": grouped.get("strategy_positions", []),
        "manual_position": grouped.get("manual_position"),
        "manual_positions": grouped.get("manual_positions", []),
        "unknown_positions": grouped.get("unknown_positions", []),
    }


@app.get("/api/trade-history")
def trade_history() -> Dict[str, Any]:
    return journal_service.get_trade_history_payload()


@app.get("/api/pnl-history")
def pnl_history() -> Dict[str, Any]:
    curve = get_equity_curve(DB_PATH, limit=1000)
    return {"items": curve}


@app.get("/api/journal")
def journal_entries(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    search: str = Query(default=""),
    source: str = Query(default=""),
    state: str = Query(default=""),
    recovered: str = Query(default=""),
) -> Dict[str, Any]:
    return journal_service.get_journal_page(page, page_size, search, source, state, recovered)


@app.get("/api/journal/summary")
def journal_summary(
    search: str = Query(default=""),
    source: str = Query(default=""),
    state: str = Query(default=""),
    recovered: str = Query(default=""),
) -> Dict[str, Any]:
    return journal_service.get_journal_summary(search, source, state, recovered)


@app.post("/api/journal/refresh")
def journal_refresh() -> Dict[str, Any]:
    _trigger_journal_sync(force=True, background=False)
    rows = _decorate_journal_rows(get_journal_entries(DB_PATH, limit=3000, offset=0), allow_network_hints=True)
    pending = sum(1 for r in rows if int(r.get("pending", 0) or 0) == 1)
    return {"success": True, "refreshed": len(rows), "pending": pending}


@app.post("/api/journal/clear-stale-pending")
def journal_clear_stale_pending(max_age_sec: int = Query(default=86400, ge=300, le=604800)) -> Dict[str, Any]:
    return journal_service.clear_stale_pending(max_age_sec)


@app.patch("/api/journal/{entry_id}")
def journal_update_annotations(entry_id: int, payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:  # type: ignore[valid-type]
    notes = str(payload.get("notes", "") or "").strip()
    tags = str(payload.get("tags", "") or "").strip()
    updated = update_journal_entry_annotations(DB_PATH, entry_id, notes, tags)
    if not updated:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return {"success": True, "id": entry_id, "notes": notes, "tags": tags}


@app.get("/api/system/integrity-report")
def system_integrity_report() -> Dict[str, Any]:
    return journal_service.get_integrity_report()


@app.get("/api/system/metrics")
def system_metrics() -> Dict[str, MetricsPayload]:
    with _METRICS_LOCK:
        requests_metrics = dict(_APP_METRICS.get("requests", {}))
        journal_sync = dict(_APP_METRICS.get("journal_sync", {}))
        remote_history = dict(_APP_METRICS.get("remote_history", {}))
    queue = _load_pending_finalize_state()
    return {
        "metrics": {
            "requests": requests_metrics,
            "journal_sync": journal_sync,
            "remote_history": remote_history,
            "pending_finalize_count": len(queue),
            "regime_tuning": runner.get_regime_tuning_metrics(),
        }
    }


@app.get("/api/signals")
def signals() -> Dict[str, Any]:
    return {"items": get_signals(DB_PATH, limit=200)}


@app.get("/api/logs")
def logs() -> Dict[str, Any]:
    return {"items": get_logs(DB_PATH, limit=300)}


@app.get("/api/bot/settings")
def bot_settings() -> Dict[str, Any]:
    values = runner.get_runtime_settings()
    return {
        "margin_boks": values["margin_boks"],
        "leverage": values["leverage"],
        "sl_capital_pct": values["sl_capital_pct"],
        "tp_capital_pct": values["tp_capital_pct"],
        "sl_percent": values["sl_capital_pct"] * 100,
        "tp_percent": values["tp_capital_pct"] * 100,
    }


@app.post("/api/bot/settings")
def update_bot_settings(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:  # type: ignore[valid-type]
    parsed = {
        "margin_boks": payload.get("margin_boks"),
        "leverage": payload.get("leverage"),
        "sl_capital_pct": payload.get("sl_capital_pct"),
        "tp_capital_pct": payload.get("tp_capital_pct"),
    }

    sl_percent = payload.get("sl_percent")
    tp_percent = payload.get("tp_percent")
    if sl_percent is not None:
        try:
            parsed["sl_capital_pct"] = float(sl_percent) / 100
        except Exception:
            pass
    if tp_percent is not None:
        try:
            parsed["tp_capital_pct"] = float(tp_percent) / 100
        except Exception:
            pass

    updated = runner.apply_runtime_settings(parsed)
    return {
        "success": True,
        "settings": {
            "margin_boks": updated["margin_boks"],
            "leverage": updated["leverage"],
            "sl_capital_pct": updated["sl_capital_pct"],
            "tp_capital_pct": updated["tp_capital_pct"],
            "sl_percent": updated["sl_capital_pct"] * 100,
            "tp_percent": updated["tp_capital_pct"] * 100,
        },
    }


@app.get("/api/strategies")
def list_strategies() -> Dict[str, Any]:
    return {
        "active": runner.get_active_strategy(),
        "enabled": runner.get_enabled_strategies(),
        "mode": runner.get_strategy_mode(),
        "items": runner.list_strategies(),
    }


@app.post("/api/strategy/select")
def select_strategy(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:  # type: ignore[valid-type]
    strategy_id = str(payload.get("strategy_id", "") or "")
    result = runner.set_active_strategy(strategy_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=str(result.get("message", "Invalid strategy")))
    return {
        "success": True,
        "active": runner.get_active_strategy(),
        "enabled": runner.get_enabled_strategies(),
        "mode": runner.get_strategy_mode(),
        "items": runner.list_strategies(),
    }


@app.post("/api/strategy/run-all")
def run_all_strategies() -> Dict[str, Any]:
    result = runner.run_all_strategies()
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=str(result.get("message", "Invalid strategy mode")))
    return {
        "success": True,
        "active": runner.get_active_strategy(),
        "enabled": runner.get_enabled_strategies(),
        "mode": runner.get_strategy_mode(),
        "items": runner.list_strategies(),
    }


@app.post("/api/manual/force-open-long")
def manual_force_open_long(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:  # type: ignore[valid-type]
    symbol = str(payload.get("symbol", "ETHUSDT") or "ETHUSDT").upper()
    manual_settings = {
        "margin_boks": payload.get("margin_boks"),
        "leverage": payload.get("leverage"),
        "sl_percent": payload.get("sl_percent"),
        "tp_percent": payload.get("tp_percent"),
    }
    return runner.manual_force_open_long(
        symbol=symbol,
        comment=f"zzCatzz from the Matrix is opening a LONG position on {symbol}.",
        manual_settings=manual_settings,
    )


@app.post("/api/manual/force-open-short")
def manual_force_open_short(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:  # type: ignore[valid-type]
    symbol = str(payload.get("symbol", "ETHUSDT") or "ETHUSDT").upper()
    manual_settings = {
        "margin_boks": payload.get("margin_boks"),
        "leverage": payload.get("leverage"),
        "sl_percent": payload.get("sl_percent"),
        "tp_percent": payload.get("tp_percent"),
    }
    return runner.manual_force_open_short(
        symbol=symbol,
        comment=f"zzCatzz from the Matrix is opening a SHORT position on {symbol}.",
        manual_settings=manual_settings,
    )


@app.post("/api/manual/close-position")
def manual_close_position(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:  # type: ignore[valid-type]
    position_id = str(payload.get("position_id", "") or "")
    return runner.manual_close_eth_positions(
        position_id=position_id,
        comment="The SuperBOT of zzCatzz has exited the ﾏﾄﾘｯｸｽ ﾏﾄﾘｯｸｽ ﾏﾄﾘｯｸｽ!",
    )


@app.post("/api/manual/close-all-positions")
def manual_close_all_positions() -> Dict[str, Any]:
    return runner.manual_close_all_positions(comment="The SuperBOT of zzCatzz has exited the ﾏﾄﾘｯｸｽ ﾏﾄﾘｯｸｽ ﾏﾄﾘｯｸｽ!")


@app.post("/api/manual/close-strategy-position")
def close_strategy_position(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:  # type: ignore[valid-type]
    position_id = str(payload.get("position_id", "") or "")
    return runner.close_strategy_position(
        position_id=position_id,
        comment="The SuperBOT of zzCatzz has exited the ﾏﾄﾘｯｸｽ ﾏﾄﾘｯｸｽ ﾏﾄﾘｯｸｽ!",
    )


@app.post("/api/manual/close-all-strategy-positions")
def close_all_strategy_positions() -> Dict[str, Any]:
    return runner.close_all_strategy_positions(comment="The SuperBOT of zzCatzz has exited the ﾏﾄﾘｯｸｽ ﾏﾄﾘｯｸｽ ﾏﾄﾘｯｸｽ!")


@app.post("/api/bot/pause")
def pause_bot_strategy() -> Dict[str, Any]:
    return runner.pause_strategy()


@app.post("/api/bot/resume")
def resume_bot_strategy() -> Dict[str, Any]:
    return runner.resume_strategy()


@app.get("/api/aster/overview")
def aster_overview(symbol: str = "ETHUSDT") -> Dict[str, Any]:
    try:
        return aster.get_overview(symbol=symbol)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/aster/klines")
def aster_klines(symbol: str = "ETHUSDT", interval: str = "5m", limit: int = 400) -> Dict[str, Any]:
    try:
        return {
            "symbol": symbol,
            "interval": interval,
            "items": aster.get_klines(symbol=symbol, interval=interval, limit=limit),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/aster/depth")
def aster_depth(symbol: str = "ETHUSDT", limit: int = 20) -> Dict[str, Any]:
    try:
        return aster.get_depth(symbol=symbol, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/aster/symbols")
def aster_symbols() -> Dict[str, Any]:
    try:
        items = aster.get_usdt_symbols_ranked(pinned_symbols=PINNED_ASTER_SYMBOLS)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/strategy/overlay")
def strategy_overlay(symbol: str = "ETHUSDT", interval: str = "4h", limit: int = 280) -> Dict[str, Any]:
    selected_symbol = str(symbol or "ETHUSDT").upper().strip()
    active_strategy = runner.get_active_strategy()
    required_interval = "15m" if active_strategy == runner.STRATEGY_EMA_RSI else "4h"

    try:
        ranked_symbols = aster.get_usdt_symbols_ranked(pinned_symbols=PINNED_ASTER_SYMBOLS)
    except Exception:
        ranked_symbols = []
    overlay_symbols: List[str] = [str(s).upper() for s in ranked_symbols[:OVERLAY_TOP_SYMBOL_LIMIT]]
    if selected_symbol not in overlay_symbols:
        return {
            "enabled": False,
            "source": "hyperliquid",
            "symbol": selected_symbol,
            "strategy": active_strategy,
            "required_interval": required_interval,
            "message": f"Overlay is available for top {OVERLAY_TOP_SYMBOL_LIMIT} symbols in the list.",
            "ma50": [],
            "ema_fast": [],
            "ema_slow": [],
            "entry_markers": [],
            "position": None,
        }

    requested_interval = str(interval or required_interval).lower().strip()
    if requested_interval != required_interval:
        return {
            "enabled": False,
            "source": "hyperliquid",
            "symbol": selected_symbol,
            "interval": requested_interval,
            "strategy": active_strategy,
            "required_interval": required_interval,
            "message": f"Overlay for {active_strategy} is available on {required_interval} timeframe only.",
            "ma50": [],
            "ema_fast": [],
            "ema_slow": [],
            "entry_markers": [],
            "position": None,
        }

    bars = max(80, min(int(limit), 1000))
    try:
        candles = runner.hyperliquid.get_candles(runner._normalize_coin(selected_symbol), interval=required_interval, bars=bars)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch Hyperliquid candles: {exc}") from exc

    ma50 = []
    ema_fast = []
    ema_slow = []
    bb_upper = []
    bb_mid = []
    bb_lower = []
    entry_markers = []
    regime_markers = []
    regime_snapshot: Dict[str, Any] = {}
    message = ""
    if active_strategy == runner.STRATEGY_EMA_RSI:
        ema_fast = build_ema_series(candles, 20)
        ema_slow = build_ema_series(candles, 50)
        entry_markers = detect_ema_rsi_long_markers(candles)
        message = "EMA20/EMA50 and EMA-RSI entry markers are computed from Hyperliquid candles."
    elif active_strategy == runner.STRATEGY_REGIME_SWITCH:
        ema_fast = build_ema_series(candles, 200)
        bb = build_bollinger_series(candles, period=20, std_mult=2.0)
        bb_upper = bb.get("upper", []) if isinstance(bb, dict) else []
        bb_mid = bb.get("mid", []) if isinstance(bb, dict) else []
        bb_lower = bb.get("lower", []) if isinstance(bb, dict) else []
        entry_markers = detect_regime_switch_long_markers(candles)
        regime_markers = detect_regime_markers(candles)
        regime_snapshot = compute_regime_switch_snapshot(candles)
        message = "EMA200 + Bollinger bands + regime/entry markers are computed from closed 4H Hyperliquid candles."
    else:
        ma50 = build_ma50_series(candles)
        entry_markers = detect_ma50_crossup_markers(candles)
        message = "MA50 and entry markers are computed from Hyperliquid candles."

    kv = get_all_kv(DB_PATH)
    raw_positions = _parse_json(kv.get("positions", ""))
    if isinstance(raw_positions, dict):
        positions = raw_positions.get("positions", [])
    elif isinstance(raw_positions, list):
        positions = raw_positions
    else:
        positions = []
    grouped = runner.classify_open_positions(positions if isinstance(positions, list) else [])
    strategy_position = grouped.get("strategy_position") if isinstance(grouped, dict) else None

    position_overlay = None
    if isinstance(strategy_position, dict) and str(strategy_position.get("coin", "")).upper() == runner._normalize_coin(selected_symbol):
        entry_price = _safe_float(strategy_position.get("entryPrice"), 0.0)
        stop_loss = _safe_float(strategy_position.get("stopLoss"), 0.0)
        take_profit = _safe_float(strategy_position.get("takeProfit"), 0.0)
        opened_at_raw = _safe_float(strategy_position.get("openedAt"), 0.0)
        opened_at_sec = int(opened_at_raw / 1000) if opened_at_raw > 1e12 else int(opened_at_raw)
        position_overlay = {
            "position_id": str(strategy_position.get("positionId", "")),
            "coin": str(strategy_position.get("coin", "")),
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "opened_at": opened_at_sec,
            "unrealized_pnl": _safe_float(strategy_position.get("unrealizedPnl"), 0.0),
        }

    return {
        "enabled": True,
        "source": "hyperliquid",
        "symbol": selected_symbol,
        "interval": required_interval,
        "strategy": active_strategy,
        "required_interval": required_interval,
        "message": message,
        "ma50": ma50,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "bb_upper": bb_upper,
        "bb_mid": bb_mid,
        "bb_lower": bb_lower,
        "entry_markers": entry_markers,
        "regime_markers": regime_markers,
        "regime_snapshot": regime_snapshot if isinstance(regime_snapshot, dict) else {},
        "position": position_overlay,
    }


@app.get("/api/aster-trading/account-overview")
def aster_trading_account_overview() -> Dict[str, Any]:
    try:
        return aster_trading.get_account_overview()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/aster-trading/order-preview")
def aster_trading_order_preview(payload: Dict[str, Any] = Body(default={})):  # type: ignore[valid-type]
    try:
        return aster_trading.preview_order(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/aster-trading/place-order")
def aster_trading_place_order(payload: Dict[str, Any] = Body(default={})):  # type: ignore[valid-type]
    try:
        return aster_trading.place_manual_order(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/aster-trading/close-position")
def aster_trading_close_position(payload: Dict[str, Any] = Body(default={})):  # type: ignore[valid-type]
    try:
        return aster_trading.close_position_market(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/aster-trading/open-positions")
def aster_trading_open_positions() -> Dict[str, Any]:
    try:
        return aster_trading.get_open_positions()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/aster-trading/open-orders")
def aster_trading_open_orders() -> Dict[str, Any]:
    try:
        return aster_trading.get_open_orders()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/aster-trading/trade-history")
def aster_trading_trade_history(limit: int = 100) -> Dict[str, Any]:
    try:
        return aster_trading.get_trade_history(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/aster-trading/pnl-history")
def aster_trading_pnl_history(limit: int = 100) -> Dict[str, Any]:
    try:
        return aster_trading.get_income_history(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
