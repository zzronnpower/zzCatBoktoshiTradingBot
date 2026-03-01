import json
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from .hyperliquid_client import HyperliquidClient
from .mtc_client import MTCClient, MTCClientError
from .risk import build_long_sl_tp_prices, build_short_sl_tp_prices, parse_total_capital
from .storage import add_equity_snapshot, add_log, add_signal, add_trade, get_kv, set_kv
from .strategy import (
    compute_regime_switch_snapshot,
    evaluate_exit_ema_cross_down_15m,
    evaluate_long_ema_rsi_15m,
    evaluate_long_ma50_cross_3_candles,
    evaluate_regime_switch_entry_long_4h,
    evaluate_regime_switch_manage_long_4h,
)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class BotRunner:
    MANUAL_ALLOWED_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "TAOUSDT", "XRPUSDT", "HYPEUSDT", "PUMPUSDT", "DOGEUSDT"]
    MANUAL_MAX_POSITIONS = 3
    STRATEGY_MA50 = "MA50_4H_CROSSUP_3C_LONG_ONLY"
    STRATEGY_EMA_RSI = "EMA_RSI_15M_ETH_ONLY"
    STRATEGY_REGIME_SWITCH = "4H_REGIME_SWITCH_V1"
    STRATEGY_TARGET_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    EMA_STATE_KEY = "ema_strategy_state"
    REGIME_STATE_KEY = "regime_switch_state"
    STRATEGY_POSITION_IDS_KEY = "strategy_position_ids"
    ENABLED_STRATEGIES_KEY = "enabled_strategies"
    ACTIVE_STRATEGY_KEY = "active_strategy"

    REGIME_RISK_PER_TRADE = 0.01
    REGIME_MAX_OPEN_LONGS_TOTAL = 2
    REGIME_MAX_OPEN_LONGS_PER_SYMBOL = 1
    REGIME_MAX_DAILY_DRAWDOWN = 0.03
    REGIME_COOLDOWN_BARS_AFTER_EXIT = 3
    REGIME_TREND_STOP_ATR_MULT = 1.5
    REGIME_TREND_TRAIL_ATR_MULT = 2.0
    REGIME_MOVE_STOP_TO_BE_ATR = 1.0
    REGIME_RANGE_STOP_ATR_MULT = 1.2
    REGIME_RANGE_MOVE_SL_TO_BE_R = 1.0
    REGIME_VOLATILITY_SHOCK_MULT = 1.8

    def __init__(
        self,
        db_path: str,
        base_url: str,
        api_key: Optional[str],
        poll_seconds: int,
        dry_run: bool,
        bot_name: str,
        bot_desc: str,
        trade_coin: str,
        margin_boks: float,
        leverage: float,
        sl_capital_pct: float,
        tp_capital_pct: float,
        max_positions: int,
        strategy_auto_start: bool = False,
    ) -> None:
        self.db_path = db_path
        self.client = MTCClient(base_url, api_key)
        self.hyperliquid = HyperliquidClient()
        self.poll_seconds = poll_seconds
        self.dry_run = dry_run
        self.bot_name = bot_name
        self.bot_desc = bot_desc
        self.trade_pair = trade_coin.upper()
        self.trade_coin = self._normalize_coin(self.trade_pair)
        self.default_trade_pair = self.trade_pair
        self.default_trade_coin = self.trade_coin
        self.margin_boks = margin_boks
        self.leverage = leverage
        self.sl_capital_pct = sl_capital_pct
        self.tp_capital_pct = tp_capital_pct
        self.max_positions = max_positions

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._warned_no_key = False
        self._trade_timestamps: Deque[int] = deque()
        self._trade_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._strategy_paused = not bool(strategy_auto_start)
        self.active_strategy = self.STRATEGY_MA50
        self.enabled_strategies: List[str] = [self.STRATEGY_MA50]
        self.running_fetch_seconds = max(int(self.poll_seconds), 20)
        self.paused_fetch_seconds = max(int(self.poll_seconds) * 3, 60)
        self.history_fetch_seconds = 120
        self._last_remote_fetch_ts = 0
        self._last_history_fetch_ts = 0
        self._api_backoff_until_ts = 0
        self._api_backoff_step = 0
        self._last_backoff_log_ts = 0
        self._regime_market_cache: Dict[str, Dict[str, Any]] = {}
        self._regime_tuning_metrics: Dict[str, int] = {
            "cap_blocked_total": 0,
            "symbol_cap_blocked_total": 0,
            "volatility_shock_skipped_total": 0,
            "candidates_total": 0,
            "candidates_opened_total": 0,
            "candidates_rejected_total": 0,
        }

    def _is_rate_limited_error(self, exc: MTCClientError) -> bool:
        code = str(getattr(exc, "code", "") or "").upper()
        text = str(exc or "").lower()
        return code in {"CF_1015", "HTTP_429"} or "1015" in text or "rate limit" in text

    def _register_rate_limit_backoff(self, now: int, exc: MTCClientError, source: str) -> None:
        if not self._is_rate_limited_error(exc):
            return
        self._api_backoff_step = min(self._api_backoff_step + 1, 5)
        delay = min(300, 30 * (2 ** (self._api_backoff_step - 1)))
        self._api_backoff_until_ts = max(self._api_backoff_until_ts, now + delay)
        if now - self._last_backoff_log_ts >= 10:
            self._log_structured(
                now,
                "WARN",
                "mtc_backoff_activated",
                source=source,
                error_code=exc.code,
                backoff_seconds=delay,
                backoff_until=self._api_backoff_until_ts,
            )
            self._last_backoff_log_ts = now

    def _clear_rate_limit_backoff(self) -> None:
        self._api_backoff_step = 0
        self._api_backoff_until_ts = 0

    def get_runtime_settings(self) -> Dict[str, float]:
        with self._state_lock:
            return {
                "margin_boks": float(self.margin_boks),
                "leverage": float(self.leverage),
                "sl_capital_pct": float(self.sl_capital_pct),
                "tp_capital_pct": float(self.tp_capital_pct),
            }

    def _inc_regime_metric(self, key: str, delta: int = 1) -> None:
        if key not in self._regime_tuning_metrics:
            return
        self._regime_tuning_metrics[key] = max(self._regime_tuning_metrics[key] + int(delta), 0)

    def get_regime_tuning_metrics(self) -> Dict[str, Any]:
        metrics: Dict[str, Any] = dict(self._regime_tuning_metrics)
        total = max(_to_int(metrics.get("candidates_total", 0), 0), 0)
        opened = max(_to_int(metrics.get("candidates_opened_total", 0), 0), 0)
        metrics["open_rate"] = (opened / total) if total > 0 else 0.0
        return metrics

    def get_active_strategy(self) -> str:
        return self.active_strategy

    def get_enabled_strategies(self) -> List[str]:
        return list(self.enabled_strategies)

    def get_strategy_mode(self) -> str:
        return "all" if len(self.enabled_strategies) > 1 else "single"

    def get_regime_runtime(self, strategy_id: Optional[str] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
        slot = self._strategy_slot_key(strategy_id or self.active_strategy, symbol or self.trade_pair)
        state = self._get_regime_state(slot)
        if not state:
            return {}
        return {
            "slot": slot,
            "last_regime": str(state.get("last_regime", "")),
            "cooldown_remaining_bars": _to_int(state.get("cooldown_remaining_bars", 0), 0),
            "trading_blocked_today": bool(state.get("trading_blocked_today", False)),
            "day_drawdown_pct": _to_float(state.get("day_drawdown_pct", 0.0), 0.0),
            "last_processed_candle": _to_int(state.get("last_processed_candle", 0), 0),
            "regime_at_entry": str(state.get("regime_at_entry", "")),
        }

    def list_strategies(self) -> List[Dict[str, str]]:
        return [
            {
                "id": self.STRATEGY_MA50,
                "label": "MA50 4H CrossUp 3 Candles (BTC/ETH/SOL)",
                "entry": "Price crosses above MA50 then closes above MA50 for 3 consecutive 4H candles on BTCUSDT/ETHUSDT/SOLUSDT.",
            },
            {
                "id": self.STRATEGY_EMA_RSI,
                "label": "EMA20/50 + RSI filter 15m (BTC/ETH/SOL)",
                "entry": "EMA20 cross above EMA50 with RSI in 50-70 band on closed 15m candle for BTCUSDT/ETHUSDT/SOLUSDT.",
            },
            {
                "id": self.STRATEGY_REGIME_SWITCH,
                "label": "4H Regime Switch V1 (BTC/ETH/SOL)",
                "entry": "Closed 4H candle regime detector (TREND/RANGE) with Donchian breakout or BB/RSI mean reversion, long-only.",
            },
        ]

    def _valid_strategy_ids(self) -> List[str]:
        return [item["id"] for item in self.list_strategies()]

    def _set_enabled_strategies(self, strategy_ids: List[str], now: Optional[int] = None, message: str = "") -> Dict[str, Any]:
        valid_ids = set(self._valid_strategy_ids())
        cleaned = [sid for sid in [str(x or "").strip().upper() for x in strategy_ids] if sid in valid_ids]
        deduped = list(dict.fromkeys(cleaned))
        if not deduped:
            return {"success": False, "message": "No valid strategies selected."}
        self.enabled_strategies = deduped
        self.active_strategy = deduped[0]
        set_kv(self.db_path, self.ACTIVE_STRATEGY_KEY, self.active_strategy)
        set_kv(self.db_path, self.ENABLED_STRATEGIES_KEY, json.dumps(self.enabled_strategies))
        if now is None:
            now = int(time.time())
        if message:
            add_log(self.db_path, now, "INFO", message)
        return {
            "success": True,
            "active": self.active_strategy,
            "enabled": list(self.enabled_strategies),
            "mode": self.get_strategy_mode(),
        }

    def set_active_strategy(self, strategy_id: str) -> Dict[str, Any]:
        selected = str(strategy_id or "").strip().upper()
        valid_ids = set(self._valid_strategy_ids())
        if selected not in valid_ids:
            return {"success": False, "message": f"Unsupported strategy: {strategy_id}"}
        return self._set_enabled_strategies(
            [selected],
            now=int(time.time()),
            message=f"Strategy mode switched to SINGLE. Active strategy set to {selected}.",
        )

    def run_all_strategies(self) -> Dict[str, Any]:
        return self._set_enabled_strategies(
            self._valid_strategy_ids(),
            now=int(time.time()),
            message="Strategy mode switched to ALL. All configured strategies are enabled.",
        )

    def apply_runtime_settings(self, payload: Dict[str, Any]) -> Dict[str, float]:
        margin_boks = max(_to_float(payload.get("margin_boks"), self.margin_boks), 1.0)
        leverage = max(_to_float(payload.get("leverage"), self.leverage), 1.0)
        sl_capital_pct = max(_to_float(payload.get("sl_capital_pct"), self.sl_capital_pct), 0.0001)
        tp_capital_pct = max(_to_float(payload.get("tp_capital_pct"), self.tp_capital_pct), 0.0)

        with self._state_lock:
            self.margin_boks = margin_boks
            self.leverage = leverage
            self.sl_capital_pct = sl_capital_pct
            self.tp_capital_pct = tp_capital_pct

        set_kv(self.db_path, "cfg_margin_boks", str(margin_boks))
        set_kv(self.db_path, "cfg_leverage", str(leverage))
        set_kv(self.db_path, "cfg_sl_capital_pct", str(sl_capital_pct))
        set_kv(self.db_path, "cfg_tp_capital_pct", str(tp_capital_pct))
        add_log(
            self.db_path,
            int(time.time()),
            "INFO",
            "Updated runtime settings: "
            f"margin={margin_boks}, leverage={leverage}, sl_capital_pct={sl_capital_pct}, tp_capital_pct={tp_capital_pct}",
        )
        return self.get_runtime_settings()

    def load_runtime_settings_from_db(self) -> Dict[str, float]:
        margin_boks = _to_float(get_kv(self.db_path, "cfg_margin_boks", str(self.margin_boks)), self.margin_boks)
        leverage = _to_float(get_kv(self.db_path, "cfg_leverage", str(self.leverage)), self.leverage)
        sl_capital_pct = _to_float(get_kv(self.db_path, "cfg_sl_capital_pct", str(self.sl_capital_pct)), self.sl_capital_pct)
        tp_capital_pct = _to_float(get_kv(self.db_path, "cfg_tp_capital_pct", str(self.tp_capital_pct)), self.tp_capital_pct)
        with self._state_lock:
            self.margin_boks = max(margin_boks, 1.0)
            self.leverage = max(leverage, 1.0)
            self.sl_capital_pct = max(sl_capital_pct, 0.0001)
            self.tp_capital_pct = max(tp_capital_pct, 0.0)
        valid_ids = set(self._valid_strategy_ids())
        selected = get_kv(self.db_path, self.ACTIVE_STRATEGY_KEY, self.STRATEGY_MA50).upper().strip()
        enabled_raw = get_kv(self.db_path, self.ENABLED_STRATEGIES_KEY, "")
        enabled: List[str] = []
        if enabled_raw:
            try:
                parsed = json.loads(enabled_raw)
                if isinstance(parsed, list):
                    enabled = [str(x or "").strip().upper() for x in parsed]
            except Exception:
                enabled = []
        enabled = [sid for sid in enabled if sid in valid_ids]
        if not enabled and selected in valid_ids:
            enabled = [selected]
        if not enabled:
            enabled = [self.STRATEGY_MA50]
        self.enabled_strategies = list(dict.fromkeys(enabled))
        self.active_strategy = self.enabled_strategies[0]
        set_kv(self.db_path, self.ACTIVE_STRATEGY_KEY, self.active_strategy)
        set_kv(self.db_path, self.ENABLED_STRATEGIES_KEY, json.dumps(self.enabled_strategies))
        return self.get_runtime_settings()

    @staticmethod
    def _normalize_coin(symbol: str) -> str:
        value = symbol.upper().strip()
        if value.endswith("USDT"):
            return value[:-4]
        return value

    def _log_structured(self, ts: int, level: str, event: str, **fields: Any) -> None:
        payload: Dict[str, Any] = {
            "event": event,
            "ts": int(ts),
            "level": str(level).upper(),
        }
        for key, value in fields.items():
            if value in (None, ""):
                continue
            payload[key] = value
        add_log(self.db_path, ts, level, json.dumps(payload, ensure_ascii=True, sort_keys=True))

    @staticmethod
    def _close_external_id(position_id: str) -> str:
        pid = str(position_id or "").strip()
        if not pid:
            return ""
        return f"local-close:{pid}"

    def _strategy_slot_key(self, strategy_id: Optional[str] = None, symbol: Optional[str] = None) -> str:
        sid = str(strategy_id or self.active_strategy or "").upper().strip()
        pair = str(symbol or self.trade_pair or "").upper().strip()
        return f"{sid}:{pair}"

    def _get_strategy_position_map(self) -> Dict[str, str]:
        raw = get_kv(self.db_path, self.STRATEGY_POSITION_IDS_KEY, "")
        out: Dict[str, str] = {}
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    out = {str(k): str(v) for k, v in parsed.items() if str(v)}
            except Exception:
                out = {}
        legacy = get_kv(self.db_path, "strategy_position_id", "")
        if legacy:
            legacy_key = self._strategy_slot_key(self.STRATEGY_MA50, self.default_trade_pair)
            if legacy_key not in out:
                out[legacy_key] = legacy
            current_key = self._strategy_slot_key(self.active_strategy, self.trade_pair)
            if current_key not in out:
                out[current_key] = legacy
        return out

    def _set_strategy_position_map(self, value: Dict[str, str]) -> None:
        clean = {str(k): str(v) for k, v in value.items() if str(k) and str(v)}
        set_kv(self.db_path, self.STRATEGY_POSITION_IDS_KEY, json.dumps(clean))
        legacy_key = self._strategy_slot_key(self.STRATEGY_MA50, self.default_trade_pair)
        set_kv(self.db_path, "strategy_position_id", clean.get(legacy_key, ""))

    def _owner_key(self, owner: str) -> str:
        if owner == "manual":
            return "manual_position_ids"
        if owner == "strategy":
            return self.STRATEGY_POSITION_IDS_KEY
        return f"{owner}_position_id"

    def _get_owner_position_id(self, owner: str) -> str:
        if owner == "manual":
            ids = self._get_manual_position_ids()
            return ids[0] if ids else ""
        if owner == "strategy":
            value = self._get_strategy_position_map()
            return value.get(self._strategy_slot_key(), "")
        return get_kv(self.db_path, self._owner_key(owner), "")

    def _set_owner_position_id(self, owner: str, position_id: str) -> None:
        if owner == "manual":
            if position_id:
                self._set_manual_position_ids([position_id])
            else:
                self._set_manual_position_ids([])
            return
        if owner == "strategy":
            value = self._get_strategy_position_map()
            slot = self._strategy_slot_key()
            if position_id:
                value[slot] = str(position_id)
            else:
                value.pop(slot, None)
            self._set_strategy_position_map(value)
            return
        set_kv(self.db_path, self._owner_key(owner), position_id)

    def _get_manual_position_ids(self) -> List[str]:
        raw = get_kv(self.db_path, self._owner_key("manual"), "")
        ids: List[str] = []
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    ids = [str(x) for x in parsed if str(x)]
            except Exception:
                ids = [x.strip() for x in raw.split(",") if x.strip()]

        legacy = get_kv(self.db_path, "manual_position_id", "")
        if legacy and legacy not in ids:
            ids.insert(0, legacy)
        deduped = list(dict.fromkeys(ids))
        if deduped != ids:
            self._set_manual_position_ids(deduped)
        return deduped

    def _set_manual_position_ids(self, position_ids: List[str]) -> None:
        clean = list(dict.fromkeys([str(x) for x in position_ids if str(x)]))
        set_kv(self.db_path, self._owner_key("manual"), json.dumps(clean))
        set_kv(self.db_path, "manual_position_id", clean[0] if clean else "")

    def _add_manual_position_id(self, position_id: str) -> None:
        if not position_id:
            return
        ids = self._get_manual_position_ids()
        if position_id not in ids:
            ids.append(position_id)
        self._set_manual_position_ids(ids)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            now = int(time.time())
            paused = self.is_strategy_paused()
            set_kv(self.db_path, "bot_status", "paused" if paused else "running")
            set_kv(self.db_path, "strategy_state", "paused" if paused else "running")
            set_kv(self.db_path, "last_tick", str(now))
            if not self.client.api_key:
                if not self._warned_no_key:
                    add_log(self.db_path, now, "WARN", "MTC_API_KEY missing; bot idle mode.")
                    self._warned_no_key = True
                time.sleep(self.poll_seconds)
                continue

            if self._api_backoff_until_ts > now:
                time.sleep(self.poll_seconds)
                continue

            fetch_interval = self.paused_fetch_seconds if paused else self.running_fetch_seconds
            if self._last_remote_fetch_ts and (now - self._last_remote_fetch_ts) < fetch_interval:
                time.sleep(self.poll_seconds)
                continue

            try:
                self._tick(now)
                self._last_remote_fetch_ts = now
            except Exception as exc:
                add_log(self.db_path, now, "ERROR", f"Tick failure: {exc}")

            time.sleep(self.poll_seconds)

    def _tick(self, now: int) -> None:
        paused = self.is_strategy_paused()
        account = self._fetch_account(now)
        positions = self._fetch_positions(now)
        self._sync_owned_position_ids(now, positions)
        history: List[Dict[str, Any]] = []
        need_history_fetch = (not self._last_history_fetch_ts) or (now - self._last_history_fetch_ts >= self.history_fetch_seconds)
        if need_history_fetch:
            history = self._fetch_history(now)
            self._last_history_fetch_ts = now
        else:
            cached_history = get_kv(self.db_path, "last_history", "[]")
            try:
                parsed_history = json.loads(cached_history)
            except Exception:
                parsed_history = []
            history = parsed_history if isinstance(parsed_history, list) else []
        self._record_equity(now, account, positions)
        if not paused:
            self._run_all_strategy_contexts(now, account, positions)
        if (not paused) and now % 3600 < self.poll_seconds:
            self._maybe_daily_claim(now)
        set_kv(self.db_path, "last_history", json.dumps(history))

    def _run_all_strategy_contexts(self, now: int, account: Dict[str, Any], positions: List[Dict[str, Any]]) -> None:
        paused = self.is_strategy_paused()
        selected_strategy = self.enabled_strategies[0] if self.enabled_strategies else self.STRATEGY_MA50
        selected_pair = self.default_trade_pair
        for strategy_id in self.enabled_strategies:
            if strategy_id == self.STRATEGY_REGIME_SWITCH:
                for symbol in self.STRATEGY_TARGET_SYMBOLS:
                    self._set_strategy_context(strategy_id, symbol)
                    self._manage_open_positions(now, account, positions)

                if not paused:
                    available_slots = self._available_regime_slots(positions)
                    if available_slots > 0:
                        candidates = self._collect_regime_candidates(now, account, positions)
                        ranked = sorted(candidates, key=lambda x: _to_float(x.get("_score", 0.0), 0.0), reverse=True)
                        opened = 0
                        for candidate in ranked:
                            if opened >= available_slots:
                                break
                            symbol = str(candidate.get("_symbol", "") or "")
                            if not symbol:
                                continue
                            if self._count_regime_open_longs_for_coin(self._normalize_coin(symbol), positions) >= self.REGIME_MAX_OPEN_LONGS_PER_SYMBOL:
                                continue
                            try:
                                if self._open_regime_candidate(now, candidate, account, positions):
                                    opened += 1
                                    self._inc_regime_metric("candidates_opened_total", 1)
                                else:
                                    self._inc_regime_metric("candidates_rejected_total", 1)
                            except MTCClientError as exc:
                                self._inc_regime_metric("candidates_rejected_total", 1)
                                self._log_structured(
                                    now,
                                    "ERROR",
                                    "regime_open_failed",
                                    symbol=symbol,
                                    error=str(exc),
                                    error_code=exc.code,
                                )
                        skipped_by_slots = max(len(ranked) - min(len(ranked), available_slots), 0)
                        if skipped_by_slots > 0:
                            self._inc_regime_metric("candidates_rejected_total", skipped_by_slots)
                    else:
                        self._inc_regime_metric("cap_blocked_total", 1)
                    continue

            for symbol in self.STRATEGY_TARGET_SYMBOLS:
                self._set_strategy_context(strategy_id, symbol)
                self._manage_open_positions(now, account, positions)
                if not paused:
                    self._maybe_open_long(now, account, positions)
        self._set_strategy_context(selected_strategy, selected_pair)

    def _set_strategy_context(self, strategy_id: str, symbol: str) -> None:
        self.active_strategy = str(strategy_id or self.STRATEGY_MA50).upper().strip()
        self.trade_pair = str(symbol or self.default_trade_pair).upper().strip()
        self.trade_coin = self._normalize_coin(self.trade_pair)

    def is_strategy_paused(self) -> bool:
        with self._state_lock:
            return self._strategy_paused

    def pause_strategy(self) -> Dict[str, Any]:
        now = int(time.time())
        with self._state_lock:
            if self._strategy_paused:
                set_kv(self.db_path, "bot_status", "paused")
                set_kv(self.db_path, "strategy_state", "paused")
                return {"success": True, "paused": True, "message": "Strategy is already paused."}
            self._strategy_paused = True
        set_kv(self.db_path, "bot_status", "paused")
        set_kv(self.db_path, "strategy_state", "paused")
        add_log(self.db_path, now, "INFO", "Strategy paused by user action. Manual trading remains available.")
        return {"success": True, "paused": True, "message": "Strategy paused."}

    def resume_strategy(self) -> Dict[str, Any]:
        now = int(time.time())
        with self._state_lock:
            if not self._strategy_paused:
                set_kv(self.db_path, "bot_status", "running")
                set_kv(self.db_path, "strategy_state", "running")
                return {"success": True, "paused": False, "message": "Strategy is already running."}
            self._strategy_paused = False
        set_kv(self.db_path, "bot_status", "running")
        set_kv(self.db_path, "strategy_state", "running")
        add_log(self.db_path, now, "INFO", "Strategy resumed by user action.")
        return {"success": True, "paused": False, "message": "Strategy resumed."}

    def _fetch_account(self, now: int) -> Dict[str, Any]:
        try:
            account = self.client.get_account()
            set_kv(self.db_path, "account", json.dumps(account))
            set_kv(self.db_path, "account_ok", "true")
            notices = account.get("notices", []) if isinstance(account, dict) else []
            if notices:
                set_kv(self.db_path, "notices", json.dumps(notices))
            self._clear_rate_limit_backoff()
            return account if isinstance(account, dict) else {}
        except MTCClientError as exc:
            set_kv(self.db_path, "account_ok", "false")
            self._register_rate_limit_backoff(now, exc, "account")
            add_log(self.db_path, now, "ERROR", f"Account fetch failed: {exc} ({exc.code})")
            return {}

    def _fetch_positions(self, now: int) -> List[Dict[str, Any]]:
        try:
            response = self.client.get_positions()
            set_kv(self.db_path, "positions", json.dumps(response))
            positions = response.get("positions", response if isinstance(response, list) else [])
            self._clear_rate_limit_backoff()
            return positions if isinstance(positions, list) else []
        except MTCClientError as exc:
            self._register_rate_limit_backoff(now, exc, "positions")
            add_log(self.db_path, now, "ERROR", f"Positions fetch failed: {exc} ({exc.code})")
            return []

    def _fetch_history(self, now: int) -> List[Dict[str, Any]]:
        try:
            response = self.client.get_history(limit=100)
            history = response.get("history", response.get("items", response))
            self._clear_rate_limit_backoff()
            if isinstance(history, list):
                return history
            return []
        except MTCClientError as exc:
            self._register_rate_limit_backoff(now, exc, "history")
            add_log(self.db_path, now, "ERROR", f"History fetch failed: {exc} ({exc.code})")
            return []

    def _record_equity(self, now: int, account: Dict[str, Any], positions: List[Dict[str, Any]]) -> None:
        boks = account.get("boks", {}) if isinstance(account, dict) else {}
        balance = float(boks.get("balance", 0) or 0)
        available = float(boks.get("availableBalance", 0) or 0)
        locked = float(boks.get("lockedMargin", 0) or 0)
        unrealized = sum(float(p.get("unrealizedPnl", 0) or 0) for p in positions)
        total_equity = balance + locked + unrealized
        add_equity_snapshot(
            self.db_path,
            ts=now,
            balance=balance,
            available=available,
            locked=locked,
            unrealized=unrealized,
            total_equity=total_equity,
        )

    def _eth_long_positions(self, positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for pos in positions:
            coin = str(pos.get("coin", "")).upper()
            side = str(pos.get("side", "")).upper()
            position_id = str(pos.get("positionId", ""))
            if coin == self.trade_coin and side == "LONG" and position_id:
                out.append(pos)
        return out

    def _find_position_by_id(self, positions: List[Dict[str, Any]], position_id: str) -> Optional[Dict[str, Any]]:
        if not position_id:
            return None
        for pos in positions:
            if str(pos.get("positionId", "")) == position_id:
                return pos
        return None

    def _compact_position_snapshot(self, position: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(position, dict):
            return {}
        return {
            "positionId": str(position.get("positionId", "") or ""),
            "coin": str(position.get("coin", "") or "").upper(),
            "side": str(position.get("side", "") or "").upper(),
            "entryPrice": _to_float(position.get("entryPrice", 0), 0.0),
            "currentPrice": _to_float(position.get("currentPrice", 0), 0.0),
            "markPrice": _to_float(position.get("markPrice", 0), 0.0),
            "positionAmt": _to_float(position.get("positionAmt", 0), 0.0),
            "sizeUsd": _to_float(position.get("size", position.get("positionSize", 0)), 0.0),
            "margin": _to_float(position.get("margin", position.get("usedMargin", 0)), 0.0),
            "leverage": _to_float(position.get("leverage", 0), 0.0),
            "unrealizedPnl": _to_float(position.get("unrealizedPnl", 0), 0.0),
            "stopLoss": _to_float(position.get("stopLoss", 0), 0.0),
            "takeProfit": _to_float(position.get("takeProfit", 0), 0.0),
        }

    def _sync_owned_position_ids(self, now: int, positions: List[Dict[str, Any]]) -> None:
        strategy_map = self._get_strategy_position_map()
        manual_ids = self._get_manual_position_ids()

        stale_strategy_ids: List[str] = []
        next_strategy_map: Dict[str, str] = {}
        for slot, strategy_id in strategy_map.items():
            if strategy_id and self._find_position_by_id(positions, strategy_id):
                next_strategy_map[slot] = strategy_id
            elif strategy_id:
                stale_strategy_ids.append(strategy_id)
        if next_strategy_map != strategy_map:
            self._set_strategy_position_map(next_strategy_map)
        if stale_strategy_ids:
            self._log_structured(now, "INFO", "stale_strategy_position_cleared", position_ids=stale_strategy_ids)

        valid_manual_ids = [pid for pid in manual_ids if self._find_position_by_id(positions, pid)]
        cleared_ids = [pid for pid in manual_ids if pid not in valid_manual_ids]
        if cleared_ids:
            self._set_manual_position_ids(valid_manual_ids)
            self._log_structured(now, "INFO", "stale_manual_positions_cleared", position_ids=cleared_ids)

    def _owner_has_open_position(self, owner: str, positions: List[Dict[str, Any]]) -> bool:
        if owner == "manual":
            manual_ids = self._get_manual_position_ids()
            return any(self._find_position_by_id(positions, pid) is not None for pid in manual_ids)
        owner_id = self._get_owner_position_id(owner)
        return self._find_position_by_id(positions, owner_id) is not None

    def _manual_has_open_symbol(self, positions: List[Dict[str, Any]], symbol: str) -> bool:
        coin = self._normalize_coin(symbol)
        for pid in self._get_manual_position_ids():
            pos = self._find_position_by_id(positions, pid)
            if not pos:
                continue
            if str(pos.get("coin", "")).upper() == coin:
                return True
        return False

    def _has_open_side_on_coin(self, positions: List[Dict[str, Any]], coin: str, side: str) -> bool:
        target_coin = self._normalize_coin(coin)
        target_side = str(side or "").upper().strip()
        for pos in positions:
            if str(pos.get("coin", "")).upper() != target_coin:
                continue
            if str(pos.get("side", "")).upper() == target_side:
                return True
        return False

    def _has_any_open_long_on_coin(self, positions: List[Dict[str, Any]], coin: str) -> bool:
        target_coin = self._normalize_coin(coin)
        for pos in positions:
            if str(pos.get("side", "")).upper() != "LONG":
                continue
            if str(pos.get("coin", "")).upper() == target_coin:
                return True
        return False

    def _get_ema_state(self) -> Dict[str, Any]:
        raw = get_kv(self.db_path, self.EMA_STATE_KEY, "")
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        if not isinstance(parsed, dict):
            return {}
        slot = self._strategy_slot_key()
        nested = parsed.get(slot)
        if isinstance(nested, dict):
            return nested
        if "position_id" in parsed:
            return parsed
        return {}

    def _set_ema_state(self, state: Dict[str, Any]) -> None:
        raw = get_kv(self.db_path, self.EMA_STATE_KEY, "")
        value: Dict[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    value = parsed
            except Exception:
                value = {}
        value[self._strategy_slot_key()] = state
        set_kv(self.db_path, self.EMA_STATE_KEY, json.dumps(value))

    def _clear_ema_state(self) -> None:
        raw = get_kv(self.db_path, self.EMA_STATE_KEY, "")
        if not raw:
            return
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                set_kv(self.db_path, self.EMA_STATE_KEY, "")
                return
        except Exception:
            set_kv(self.db_path, self.EMA_STATE_KEY, "")
            return
        parsed.pop(self._strategy_slot_key(), None)
        set_kv(self.db_path, self.EMA_STATE_KEY, json.dumps(parsed))

    def _get_regime_state_map(self) -> Dict[str, Dict[str, Any]]:
        raw = get_kv(self.db_path, self.REGIME_STATE_KEY, "")
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        if not isinstance(parsed, dict):
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for k, v in parsed.items():
            if isinstance(v, dict):
                out[str(k)] = v
        return out

    def _get_regime_state(self, slot: Optional[str] = None) -> Dict[str, Any]:
        selected_slot = slot or self._strategy_slot_key()
        return self._get_regime_state_map().get(selected_slot, {})

    def _set_regime_state(self, state: Dict[str, Any], slot: Optional[str] = None) -> None:
        selected_slot = slot or self._strategy_slot_key()
        value = self._get_regime_state_map()
        value[selected_slot] = state
        set_kv(self.db_path, self.REGIME_STATE_KEY, json.dumps(value))

    def _patch_regime_state(self, patch: Dict[str, Any], slot: Optional[str] = None) -> Dict[str, Any]:
        selected_slot = slot or self._strategy_slot_key()
        state = self._get_regime_state(selected_slot)
        state.update(patch)
        self._set_regime_state(state, selected_slot)
        return state

    def _clear_regime_state(self, slot: Optional[str] = None) -> None:
        selected_slot = slot or self._strategy_slot_key()
        value = self._get_regime_state_map()
        value.pop(selected_slot, None)
        set_kv(self.db_path, self.REGIME_STATE_KEY, json.dumps(value))

    @staticmethod
    def _current_day_key(now: int) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(now))

    @staticmethod
    def _account_total_equity(account: Dict[str, Any], positions: List[Dict[str, Any]]) -> float:
        boks = account.get("boks", {}) if isinstance(account, dict) else {}
        balance = _to_float(boks.get("balance", 0), 0.0)
        locked = _to_float(boks.get("lockedMargin", 0), 0.0)
        unrealized = sum(_to_float(p.get("unrealizedPnl", 0), 0.0) for p in positions)
        return max(balance + locked + unrealized, 0.0)

    def _regime_entry_key(self) -> str:
        return f"last_entry_candle_regime:{self._strategy_slot_key()}"

    def _strategy_owned_positions_for(self, strategy_id: str, positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        strategy_map = self._get_strategy_position_map()
        prefix = f"{str(strategy_id or '').upper().strip()}:"
        owned: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for slot, pid in strategy_map.items():
            if not str(slot).upper().startswith(prefix):
                continue
            sid = str(pid or "").strip()
            if not sid or sid in seen:
                continue
            pos = self._find_position_by_id(positions, sid)
            if pos is None:
                continue
            side = str(pos.get("side", "")).upper()
            if side != "LONG":
                continue
            owned.append(pos)
            seen.add(sid)
        return owned

    def _count_strategy_open_positions(self, positions: List[Dict[str, Any]]) -> int:
        return len(self._strategy_owned_positions_for(self.active_strategy, positions))

    def _count_regime_open_longs_total(self, positions: List[Dict[str, Any]]) -> int:
        return len(self._strategy_owned_positions_for(self.STRATEGY_REGIME_SWITCH, positions))

    def _count_regime_open_longs_for_coin(self, coin: str, positions: List[Dict[str, Any]]) -> int:
        target = self._normalize_coin(coin)
        return sum(1 for pos in self._strategy_owned_positions_for(self.STRATEGY_REGIME_SWITCH, positions) if str(pos.get("coin", "")).upper() == target)

    def _available_regime_slots(self, positions: List[Dict[str, Any]]) -> int:
        return max(self.REGIME_MAX_OPEN_LONGS_TOTAL - self._count_regime_open_longs_total(positions), 0)

    @staticmethod
    def _score_regime_candidate(signal: Dict[str, Any]) -> float:
        regime = str(signal.get("regime", "NO_TRADE"))
        adx_val = _to_float(signal.get("adx14", 0.0), 0.0)
        atr_slope = _to_float(signal.get("atr_slope", 0.0), 0.0)
        close = max(_to_float(signal.get("close", 0.0), 0.0), 1e-9)
        atr = max(_to_float(signal.get("atr14", 0.0), 0.0), 1e-9)
        breakout_strength = atr / close
        regime_bias = 1.0 if regime == "TREND" else 0.4
        return (regime_bias * 100.0) + adx_val + (atr_slope * 10.0) + (breakout_strength * 10000.0)

    def _build_regime_margin(self, entry_price: float, stop_price: float, equity: float, positions: List[Dict[str, Any]]) -> float:
        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            return max(1.0, float(self.margin_boks))
        concentration_discount = 0.5 if self._count_strategy_open_positions(positions) >= 1 else 1.0
        risk_budget = max(equity * self.REGIME_RISK_PER_TRADE * concentration_discount, 0.0)
        if risk_budget <= 0:
            return max(1.0, float(self.margin_boks))
        notional = (risk_budget * entry_price) / stop_distance
        raw_margin = notional / max(self.leverage, 1e-9)
        capped_margin = min(raw_margin, float(self.margin_boks))
        return max(1.0, capped_margin)

    def _ensure_ema_state(self, now: int, position: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, Any]:
        position_id = str(position.get("positionId", ""))
        pnl = float(position.get("unrealizedPnl", 0) or 0)
        state = self._get_ema_state()
        if str(state.get("position_id", "")) == position_id and position_id:
            return state

        capital = parse_total_capital(account)
        risk_r = max(abs(capital * self.sl_capital_pct), 1e-9)
        created = {
            "position_id": position_id,
            "risk_r": risk_r,
            "trailing_active": pnl >= risk_r,
            "peak_pnl": pnl,
        }
        self._set_ema_state(created)
        add_log(self.db_path, now, "INFO", f"Initialized EMA strategy state for {position_id}: R={risk_r:.6f}")
        return created

    def _get_closed_ema_candles(self) -> List[Dict[str, Any]]:
        candles = self.hyperliquid.get_candles(self.trade_coin, interval="15m", bars=300)
        if len(candles) >= 2:
            maybe_open = _to_float(candles[-1].get("close_time", 0), 0.0)
            if maybe_open > int(time.time() * 1000):
                candles = candles[:-1]
        return candles

    def _manage_ema_strategy_position(
        self,
        now: int,
        account: Dict[str, Any],
        position: Dict[str, Any],
    ) -> None:
        position_id = str(position.get("positionId", ""))
        if not position_id:
            return

        state = self._ensure_ema_state(now, position, account)
        risk_r = max(_to_float(state.get("risk_r"), 0.0), 1e-9)
        pnl = float(position.get("unrealizedPnl", 0) or 0)
        peak_pnl = max(_to_float(state.get("peak_pnl"), pnl), pnl)
        trailing_active = bool(state.get("trailing_active", False))

        if peak_pnl != _to_float(state.get("peak_pnl"), pnl):
            state["peak_pnl"] = peak_pnl
            self._set_ema_state(state)

        if not trailing_active and pnl >= risk_r:
            trailing_active = True
            state["trailing_active"] = True
            state["peak_pnl"] = peak_pnl
            self._set_ema_state(state)
            add_log(self.db_path, now, "INFO", f"EMA trailing activated for {position_id} at >= 1R.")

        try:
            exit_signal = evaluate_exit_ema_cross_down_15m(self._get_closed_ema_candles())
            if exit_signal.get("signal"):
                self._close_position(
                    now,
                    position_id,
                    "EMA20 crossed below EMA50 on closed 15m candle",
                    comment="EMA strategy exit: cross down on closed 15m candle.",
                    owner="strategy",
                )
                self._clear_ema_state()
                return
        except Exception as exc:
            add_log(self.db_path, now, "ERROR", f"EMA exit signal evaluation failed: {exc}")

        if pnl <= -risk_r:
            self._close_position(
                now,
                position_id,
                f"EMA strategy SL 1R hit ({pnl:.4f} BOKS)",
                comment="EMA strategy exit: stop loss 1R.",
                owner="strategy",
            )
            self._clear_ema_state()
            return

        if pnl >= (2 * risk_r):
            self._close_position(
                now,
                position_id,
                f"EMA strategy TP 2R hit ({pnl:.4f} BOKS)",
                comment="EMA strategy exit: take profit 2R.",
                owner="strategy",
            )
            self._clear_ema_state()
            return

        if trailing_active and (peak_pnl - pnl) >= risk_r:
            self._close_position(
                now,
                position_id,
                f"EMA trailing stop hit: drawdown {peak_pnl - pnl:.4f} >= 1R from peak",
                comment="EMA strategy exit: trailing stop after 1R activation.",
                owner="strategy",
            )
            self._clear_ema_state()
            return

    def _get_closed_4h_candles(self, bars: int = 620) -> List[Dict[str, Any]]:
        candles = self.hyperliquid.get_candles(self.trade_coin, interval="4h", bars=bars)
        if len(candles) >= 2:
            maybe_open = _to_float(candles[-1].get("close_time", 0), 0.0)
            if maybe_open > int(time.time() * 1000):
                candles = candles[:-1]
        return candles

    def _get_regime_market_snapshot(self, now: int, symbol: str, bars: int = 620) -> Dict[str, Any]:
        cache = self._regime_market_cache.get(symbol)
        if cache and (now - _to_int(cache.get("fetched_at", 0), 0)) <= 90:
            return cache

        prev_pair, prev_coin = self.trade_pair, self.trade_coin
        self.trade_pair = symbol
        self.trade_coin = self._normalize_coin(symbol)
        try:
            candles = self._get_closed_4h_candles(bars=bars)
            snapshot = compute_regime_switch_snapshot(candles)
            candle_key = _to_int(snapshot.get("last_candle_open_time", 0), 0)
            payload = {
                "fetched_at": now,
                "candles": candles,
                "snapshot": snapshot,
                "candle_key": candle_key,
            }
            self._regime_market_cache[symbol] = payload
            return payload
        finally:
            self.trade_pair = prev_pair
            self.trade_coin = prev_coin

    def _build_regime_open_payload(
        self,
        signal: Dict[str, Any],
        account: Dict[str, Any],
        positions: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        capital = self._account_total_equity(account, positions)
        entry_price = _to_float(signal.get("close", 0), 0.0)
        atr_now = _to_float(signal.get("atr14", 0), 0.0)
        regime = str(signal.get("regime", "NO_TRADE"))
        if capital <= 0 or entry_price <= 0 or atr_now <= 0:
            return None

        stop_price = entry_price - (
            (self.REGIME_TREND_STOP_ATR_MULT if regime == "TREND" else self.REGIME_RANGE_STOP_ATR_MULT) * atr_now
        )
        if stop_price <= 0 or stop_price >= entry_price:
            return None

        margin_to_use = self._build_regime_margin(entry_price, stop_price, capital, positions)
        if regime == "RANGE":
            take_profit = _to_float(signal.get("bb_mid", 0), 0.0)
        else:
            risk_targets = build_long_sl_tp_prices(
                entry_price=entry_price,
                capital=capital,
                margin=margin_to_use,
                leverage=self.leverage,
                sl_capital_pct=self.sl_capital_pct,
                tp_capital_pct=self.tp_capital_pct,
            )
            take_profit = _to_float(risk_targets.get("take_profit", 0.0), 0.0)
        if take_profit <= 0:
            return None

        comment = (
            "Regime TREND breakout on closed 4H candle. Long setup."
            if regime == "TREND"
            else "Regime RANGE mean-reversion on closed 4H candle. Long setup."
        )
        return {
            "coin": self._normalize_coin(self.trade_pair),
            "side": "LONG",
            "margin": margin_to_use,
            "leverage": self.leverage,
            "stopLoss": round(stop_price, 6),
            "takeProfit": round(take_profit, 6),
            "comment": comment,
            "entry_price": entry_price,
            "atr14": atr_now,
            "regime": regime,
            "entry_type": str(signal.get("entry_type", "")),
        }

    def _manage_regime_strategy_position(
        self,
        now: int,
        account: Dict[str, Any],
        positions: List[Dict[str, Any]],
        position: Dict[str, Any],
    ) -> None:
        position_id = str(position.get("positionId", "") or "")
        if not position_id:
            return
        try:
            candles = self._get_closed_4h_candles()
        except Exception as exc:
            self._log_structured(now, "ERROR", "regime_manage_market_data_failed", symbol=self.trade_pair, error=str(exc))
            return

        snapshot = compute_regime_switch_snapshot(candles)
        if not snapshot.get("ok"):
            self._log_structured(
                now,
                "INFO",
                "regime_manage_skipped_snapshot",
                symbol=self.trade_pair,
                reason=str(snapshot.get("reason", "indicator_unavailable")),
            )
            return

        candle_key = _to_int(snapshot.get("last_candle_open_time", 0), 0)
        state = self._get_regime_state()
        if _to_int(state.get("last_processed_candle", 0), 0) == candle_key:
            return

        equity = self._account_total_equity(account, positions)
        day_key = self._current_day_key(now)
        if str(state.get("day_key", "")) != day_key:
            state["day_key"] = day_key
            state["day_start_equity"] = equity
            state["trading_blocked_today"] = False
        day_start_equity = max(_to_float(state.get("day_start_equity", equity), equity), 1e-9)
        day_drawdown_pct = (equity - day_start_equity) / day_start_equity
        state["day_drawdown_pct"] = day_drawdown_pct
        if day_drawdown_pct <= -self.REGIME_MAX_DAILY_DRAWDOWN:
            state["trading_blocked_today"] = True

        state["last_processed_candle"] = candle_key
        state["last_regime"] = str(snapshot.get("regime", "NO_TRADE"))
        state["position_id"] = position_id
        state.setdefault("entry_price", _to_float(position.get("entryPrice", 0), 0.0))
        state.setdefault("stop_price", _to_float(position.get("stopLoss", 0), 0.0))
        state.setdefault("initial_stop_price", _to_float(position.get("stopLoss", 0), 0.0))
        state.setdefault("take_profit_price", _to_float(position.get("takeProfit", 0), 0.0))
        state.setdefault("trailing_stop_price", 0.0)
        state.setdefault("moved_to_be", False)
        state.setdefault("regime_at_entry", str(snapshot.get("regime", "TREND")))

        action = evaluate_regime_switch_manage_long_4h(
            candles,
            state,
            trend_trail_atr_mult=self.REGIME_TREND_TRAIL_ATR_MULT,
            trend_move_stop_to_be_atr=self.REGIME_MOVE_STOP_TO_BE_ATR,
            range_move_sl_to_be_r=self.REGIME_RANGE_MOVE_SL_TO_BE_R,
        )

        patch = action.get("state_patch")
        if isinstance(patch, dict) and patch:
            state.update(patch)

        move_action = str(action.get("action", "HOLD") or "HOLD").upper()
        if move_action.startswith("EXIT"):
            reason = str(action.get("reason", "regime_exit") or "regime_exit")
            comment = f"Regime strategy exit: {reason}."
            self._close_position(
                now,
                position_id,
                f"Regime strategy close ({reason})",
                comment=comment,
                owner="strategy",
            )
            state["cooldown_remaining_bars"] = self.REGIME_COOLDOWN_BARS_AFTER_EXIT
            state["position_id"] = ""
            state["regime_at_entry"] = ""
            state["entry_price"] = 0.0
            state["stop_price"] = 0.0
            state["initial_stop_price"] = 0.0
            state["take_profit_price"] = 0.0
            state["trailing_stop_price"] = 0.0
            state["moved_to_be"] = False

        self._set_regime_state(state)

    def _extract_position_id_from_open_response(self, response: Dict[str, Any]) -> str:
        if not isinstance(response, dict):
            return ""
        direct = str(response.get("positionId", ""))
        if direct:
            return direct
        for key in ("position", "data", "result"):
            nested = response.get(key)
            if isinstance(nested, dict):
                pid = str(nested.get("positionId", ""))
                if pid:
                    return pid
        return ""

    def _capture_owner_position_id(
        self,
        owner: str,
        now: int,
        before_positions: List[Dict[str, Any]],
        open_response: Dict[str, Any],
    ) -> None:
        before_ids = {str(p.get("positionId", "")) for p in self._eth_long_positions(before_positions)}
        after_positions = self._fetch_positions(now)
        eth_after = self._eth_long_positions(after_positions)
        after_ids = {str(p.get("positionId", "")) for p in eth_after}

        new_ids = [pid for pid in after_ids if pid and pid not in before_ids]
        if len(new_ids) == 1:
            self._set_owner_position_id(owner, new_ids[0])
            add_log(self.db_path, now, "INFO", f"Mapped {owner} position id {new_ids[0]}.")
            return

        response_id = self._extract_position_id_from_open_response(open_response)
        if response_id and response_id in after_ids:
            self._set_owner_position_id(owner, response_id)
            add_log(self.db_path, now, "INFO", f"Mapped {owner} position id {response_id} from open response.")
            return

        if eth_after:
            sorted_after = sorted(eth_after, key=lambda x: _to_int(x.get("openedAt", 0), 0), reverse=True)
            fallback_id = str(sorted_after[0].get("positionId", ""))
            if fallback_id:
                self._set_owner_position_id(owner, fallback_id)
                add_log(self.db_path, now, "WARN", f"Mapped {owner} position id {fallback_id} using fallback matching.")

    def _capture_manual_position_id(
        self,
        now: int,
        before_positions: List[Dict[str, Any]],
        open_response: Dict[str, Any],
        coin: str,
        side: str,
    ) -> None:
        target_side = str(side or "LONG").upper().strip()
        before_ids = {
            str(p.get("positionId", ""))
            for p in before_positions
            if str(p.get("coin", "")).upper() == coin and str(p.get("side", "")).upper() == target_side
        }
        after_positions = self._fetch_positions(now)
        after_candidates = [
            p
            for p in after_positions
            if str(p.get("coin", "")).upper() == coin and str(p.get("side", "")).upper() == target_side
        ]
        after_ids = {str(p.get("positionId", "")) for p in after_candidates}

        new_ids = [pid for pid in after_ids if pid and pid not in before_ids]
        if len(new_ids) == 1:
            self._add_manual_position_id(new_ids[0])
            add_log(self.db_path, now, "INFO", f"Mapped manual position id {new_ids[0]}.")
            return

        response_id = self._extract_position_id_from_open_response(open_response)
        if response_id and response_id in after_ids:
            self._add_manual_position_id(response_id)
            add_log(self.db_path, now, "INFO", f"Mapped manual position id {response_id} from open response.")
            return

        if after_candidates:
            sorted_after = sorted(after_candidates, key=lambda x: _to_int(x.get("openedAt", 0), 0), reverse=True)
            fallback_id = str(sorted_after[0].get("positionId", ""))
            if fallback_id:
                self._add_manual_position_id(fallback_id)
                add_log(self.db_path, now, "WARN", f"Mapped manual position id {fallback_id} using fallback matching.")

    def classify_open_positions(self, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        strategy_map = self._get_strategy_position_map()
        manual_ids = self._get_manual_position_ids()

        strategy_positions: List[Dict[str, Any]] = []
        seen_strategy_ids: set[str] = set()
        for strategy_id in strategy_map.values():
            if not strategy_id or strategy_id in seen_strategy_ids:
                continue
            pos = self._find_position_by_id(positions, strategy_id)
            if pos is not None:
                strategy_positions.append(pos)
                seen_strategy_ids.add(strategy_id)
        strategy_position = strategy_positions[0] if strategy_positions else None
        manual_positions = [self._find_position_by_id(positions, pid) for pid in manual_ids]
        manual_positions = [p for p in manual_positions if p is not None]
        manual_position = manual_positions[0] if manual_positions else None

        unknown_positions: List[Dict[str, Any]] = []
        known_ids = set(seen_strategy_ids).union(set(manual_ids))
        for pos in positions:
            pid = str(pos.get("positionId", ""))
            if pid and pid not in known_ids:
                unknown_positions.append(pos)

        return {
            "strategy_position": strategy_position,
            "strategy_positions": strategy_positions,
            "manual_position": manual_position,
            "manual_positions": manual_positions,
            "unknown_positions": unknown_positions,
            "items": positions,
        }

    def _manage_open_positions(self, now: int, account: Dict[str, Any], positions: List[Dict[str, Any]]) -> None:
        strategy_id = self._get_owner_position_id("strategy")
        strategy_pos = self._find_position_by_id(positions, strategy_id)
        if not strategy_pos:
            if self.active_strategy == self.STRATEGY_EMA_RSI:
                self._clear_ema_state()
            if self.active_strategy == self.STRATEGY_REGIME_SWITCH:
                state = self._get_regime_state()
                if state and str(state.get("position_id", "")):
                    state.pop("position_id", None)
                    self._set_regime_state(state)
            return

        if self.active_strategy == self.STRATEGY_EMA_RSI:
            self._manage_ema_strategy_position(now, account, strategy_pos)
            return

        if self.active_strategy == self.STRATEGY_REGIME_SWITCH:
            self._manage_regime_strategy_position(now, account, positions, strategy_pos)
            return

        capital = parse_total_capital(account)
        if capital <= 0:
            return

        sl_target = -abs(capital * self.sl_capital_pct)
        tp_target = abs(capital * self.tp_capital_pct)
        pnl = float(strategy_pos.get("unrealizedPnl", 0) or 0)
        position_id = str(strategy_pos.get("positionId", ""))
        if not position_id:
            return

        if pnl <= sl_target:
            self._close_position(
                now,
                position_id,
                f"SL hit on total capital ({pnl:.2f} BOKS)",
                owner="strategy",
            )
        elif pnl >= tp_target:
            self._close_position(
                now,
                position_id,
                f"TP hit on total capital ({pnl:.2f} BOKS)",
                owner="strategy",
            )

    def _close_position(
        self,
        now: int,
        position_id: str,
        note: str,
        comment: str = "Risk exit: capital threshold reached.",
        owner: str = "",
    ) -> None:
        payload = {
            "positionId": position_id,
            "comment": comment,
        }
        source_hint = "strategy" if owner == "strategy" else "manual"
        close_mode = "strategy_auto"
        positions = self._fetch_positions(now)
        target = self._find_position_by_id(positions, position_id)
        close_snapshot = self._compact_position_snapshot(target)
        if self.dry_run:
            self._log_structured(
                now,
                "INFO",
                "close_dry_run",
                position_id=position_id,
                external_id=self._close_external_id(position_id),
                note=note,
                source=source_hint,
                close_mode=close_mode,
            )
            add_trade(
                self.db_path,
                now,
                "CLOSE",
                self.trade_coin,
                "LONG",
                self.margin_boks,
                self.leverage,
                "DRY_RUN",
                json.dumps(
                    {
                        "message": note,
                        "positionId": position_id,
                        "source": source_hint,
                        "close_mode": close_mode,
                        "comment": comment,
                        "close_snapshot": close_snapshot,
                    }
                ),
            )
            return
        if not self._can_send_trade(now):
            self._log_structured(
                now,
                "WARN",
                "close_rate_limited",
                position_id=position_id,
                source=source_hint,
                close_mode=close_mode,
            )
            return
        try:
            response = self.client.close_trade(payload)
            add_trade(
                self.db_path,
                now,
                "CLOSE",
                self.trade_coin,
                "LONG",
                self.margin_boks,
                self.leverage,
                "OK",
                json.dumps(
                    {
                        **(response if isinstance(response, dict) else {}),
                        "positionId": position_id,
                        "source": source_hint,
                        "close_mode": close_mode,
                        "note": note,
                        "close_snapshot": close_snapshot,
                    }
                ),
            )
            if owner:
                self._set_owner_position_id(owner, "")
            self._log_structured(
                now,
                "INFO",
                "close_submitted",
                position_id=position_id,
                external_id=self._close_external_id(position_id),
                source=source_hint,
                close_mode=close_mode,
                note=note,
            )
        except MTCClientError as exc:
            self._log_structured(
                now,
                "ERROR",
                "close_failed",
                position_id=position_id,
                source=source_hint,
                close_mode=close_mode,
                error=str(exc),
                error_code=exc.code,
            )

    def manual_force_open(self, side: str, symbol: str = "ETHUSDT", comment: str = "Manual force open") -> Dict[str, Any]:
        now = int(time.time())
        if not self.client.api_key:
            return {"success": False, "message": "MTC_API_KEY is missing."}

        target_side = str(side or "").upper().strip()
        if target_side not in {"LONG", "SHORT"}:
            return {"success": False, "message": f"Unsupported side: {side}."}

        target_symbol = str(symbol or "ETHUSDT").upper().strip()
        if target_symbol not in self.MANUAL_ALLOWED_SYMBOLS:
            return {"success": False, "message": f"Unsupported manual symbol: {target_symbol}."}
        target_coin = self._normalize_coin(target_symbol)

        account = self._fetch_account(now)
        positions = self._fetch_positions(now)
        self._sync_owned_position_ids(now, positions)

        manual_ids = self._get_manual_position_ids()
        if len(manual_ids) >= self.MANUAL_MAX_POSITIONS:
            return {"success": False, "message": f"Manual position limit reached ({self.MANUAL_MAX_POSITIONS})."}
        if self._manual_has_open_symbol(positions, target_symbol):
            return {"success": False, "message": f"Manual {target_symbol} position is already open."}
        if self._has_open_side_on_coin(positions, target_coin, "LONG" if target_side == "SHORT" else "SHORT"):
            return {"success": False, "message": f"Hedge is disabled: opposite side already open on {target_symbol}."}
        if self._has_open_side_on_coin(positions, target_coin, target_side):
            return {"success": False, "message": f"{target_symbol} already has an open {target_side} position."}
        if len(positions) >= self.max_positions:
            return {"success": False, "message": "Max positions reached."}

        capital = parse_total_capital(account)
        if capital <= 0:
            return {"success": False, "message": "Capital unavailable, cannot open trade."}

        try:
            candles = self.hyperliquid.get_candles(target_coin, interval="4h", bars=5)
        except Exception as exc:
            self._log_structured(
                now,
                "ERROR",
                "manual_open_market_data_failed",
                symbol=target_symbol,
                side=target_side,
                error=str(exc),
            )
            return {"success": False, "message": f"Failed to fetch market data: {exc}"}

        if not candles:
            return {"success": False, "message": "No candles returned from Hyperliquid."}

        entry_price = _to_float(candles[-1].get("close", 0), 0.0)
        if entry_price <= 0:
            return {"success": False, "message": "Invalid entry price from candle data."}

        risk_targets = (
            build_long_sl_tp_prices(
                entry_price=entry_price,
                capital=capital,
                margin=self.margin_boks,
                leverage=self.leverage,
                sl_capital_pct=self.sl_capital_pct,
                tp_capital_pct=self.tp_capital_pct,
            )
            if target_side == "LONG"
            else build_short_sl_tp_prices(
                entry_price=entry_price,
                capital=capital,
                margin=self.margin_boks,
                leverage=self.leverage,
                sl_capital_pct=self.sl_capital_pct,
                tp_capital_pct=self.tp_capital_pct,
            )
        )

        stop_loss = round(risk_targets["stop_loss"], 6)
        take_profit = round(risk_targets["take_profit"], 6)
        if target_side == "LONG":
            if stop_loss >= entry_price or take_profit <= entry_price:
                return {"success": False, "message": "Invalid LONG risk targets generated from runtime settings."}
        else:
            if stop_loss <= entry_price or take_profit >= entry_price:
                return {"success": False, "message": "Invalid SHORT risk targets generated from runtime settings."}

        payload_comment = str(comment or "").strip() or f"Manual force open {target_side} {target_symbol}."
        payload = {
            "coin": target_coin,
            "side": target_side,
            "margin": self.margin_boks,
            "leverage": self.leverage,
            "stopLoss": stop_loss,
            "takeProfit": take_profit,
            "comment": payload_comment,
        }

        if self.dry_run:
            add_trade(
                self.db_path,
                now,
                "OPEN",
                target_coin,
                target_side,
                self.margin_boks,
                self.leverage,
                "DRY_RUN",
                json.dumps(payload),
            )
            self._log_structured(
                now,
                "INFO",
                "manual_open_dry_run",
                symbol=target_symbol,
                side=target_side,
                payload=payload,
            )
            return {
                "success": True,
                "dry_run": True,
                "message": "DRY_RUN enabled. No live order was sent.",
                "symbol": target_symbol,
                "side": target_side,
                "payload": payload,
            }

        if not self._can_send_trade(now):
            return {"success": False, "message": "Rate limit guard blocked this request."}

        try:
            response = self.client.open_trade(payload)
            add_trade(
                self.db_path,
                now,
                "OPEN",
                target_coin,
                target_side,
                self.margin_boks,
                self.leverage,
                "OK",
                json.dumps(response),
            )
            self._capture_manual_position_id(now, positions, response, target_coin, target_side)
            self._log_structured(
                now,
                "INFO",
                "manual_open_submitted",
                symbol=target_symbol,
                side=target_side,
                position_id=str(response.get("positionId", "") or ""),
            )
            return {
                "success": True,
                "dry_run": False,
                "message": "Force open submitted.",
                "symbol": target_symbol,
                "side": target_side,
                "response": response,
            }
        except MTCClientError as exc:
            add_trade(
                self.db_path,
                now,
                "OPEN",
                target_coin,
                target_side,
                self.margin_boks,
                self.leverage,
                "ERROR",
                f"{exc} ({exc.code})",
            )
            self._log_structured(
                now,
                "ERROR",
                "manual_open_failed",
                symbol=target_symbol,
                side=target_side,
                error=str(exc),
                error_code=exc.code,
            )
            return {"success": False, "message": f"Open failed: {exc}", "code": exc.code}

    def manual_force_open_long(self, symbol: str = "ETHUSDT", comment: str = "Manual force open") -> Dict[str, Any]:
        return self.manual_force_open(side="LONG", symbol=symbol, comment=comment)

    def manual_force_open_short(self, symbol: str = "ETHUSDT", comment: str = "Manual force open") -> Dict[str, Any]:
        return self.manual_force_open(side="SHORT", symbol=symbol, comment=comment)

    def manual_close_eth_positions(self, position_id: str, comment: str = "Manual close position") -> Dict[str, Any]:
        now = int(time.time())
        if not self.client.api_key:
            return {"success": False, "message": "MTC_API_KEY is missing."}

        positions = self._fetch_positions(now)
        self._sync_owned_position_ids(now, positions)
        target_position_id = str(position_id or "").strip()
        if not target_position_id:
            return {"success": False, "message": "Please select manual position to close."}

        manual_ids = self._get_manual_position_ids()
        if target_position_id not in manual_ids:
            return {"success": False, "message": "Selected position is not a manual-owned position."}

        target = self._find_position_by_id(positions, target_position_id)

        if not target:
            return {"success": False, "message": "Selected manual position is not open."}

        resolved_position_id = str(target.get("positionId", ""))
        if not resolved_position_id:
            return {"success": False, "message": "Manual position id is invalid."}
        position_coin = str(target.get("coin", "")).upper() or "UNKNOWN"
        position_side = str(target.get("side", "")).upper() or "UNKNOWN"
        close_snapshot = self._compact_position_snapshot(target)

        if self.dry_run:
            add_trade(
                self.db_path,
                now,
                "CLOSE",
                position_coin,
                position_side,
                self.margin_boks,
                self.leverage,
                "DRY_RUN",
                json.dumps(
                    {
                        "message": f"manual close {resolved_position_id}",
                        "positionId": resolved_position_id,
                        "source": "manual",
                        "close_mode": "manual",
                        "comment": comment,
                        "close_snapshot": close_snapshot,
                    }
                ),
            )
            self._log_structured(
                now,
                "INFO",
                "manual_close_dry_run",
                position_id=resolved_position_id,
                external_id=self._close_external_id(resolved_position_id),
            )
            return {
                "success": True,
                "dry_run": True,
                "message": "DRY_RUN enabled. Simulated manual position close.",
                "closed": 1,
                "position_id": resolved_position_id,
            }

        if not self._can_send_trade(now):
            return {"success": False, "message": "Rate limit guard blocked this request."}

        try:
            response = self.client.close_trade({"positionId": resolved_position_id, "comment": comment})
            add_trade(
                self.db_path,
                now,
                "CLOSE",
                position_coin,
                position_side,
                self.margin_boks,
                self.leverage,
                "OK",
                json.dumps(
                    {
                        **(response if isinstance(response, dict) else {}),
                        "positionId": resolved_position_id,
                        "source": "manual",
                        "close_mode": "manual",
                        "close_snapshot": close_snapshot,
                    }
                ),
            )
            self._set_manual_position_ids([pid for pid in manual_ids if pid != resolved_position_id])
            self._log_structured(
                now,
                "INFO",
                "manual_close_submitted",
                position_id=resolved_position_id,
                external_id=self._close_external_id(resolved_position_id),
            )
            return {"success": True, "closed": 1, "message": "Closed manual position.", "position_id": resolved_position_id}
        except MTCClientError as exc:
            self._log_structured(
                now,
                "ERROR",
                "manual_close_failed",
                position_id=resolved_position_id,
                error=str(exc),
                error_code=exc.code,
            )
            return {"success": False, "message": f"Close failed: {exc}", "code": exc.code}

    def manual_close_all_positions(self, comment: str = "Manual close all positions") -> Dict[str, Any]:
        now = int(time.time())
        if not self.client.api_key:
            return {"success": False, "message": "MTC_API_KEY is missing."}

        positions = self._fetch_positions(now)
        self._sync_owned_position_ids(now, positions)
        manual_ids = self._get_manual_position_ids()
        if not manual_ids:
            return {"success": True, "closed": 0, "message": "No open manual positions."}

        targets: List[Dict[str, Any]] = []
        for pid in manual_ids:
            pos = self._find_position_by_id(positions, pid)
            if pos:
                targets.append(pos)

        if not targets:
            self._set_manual_position_ids([])
            return {"success": True, "closed": 0, "message": "No open manual positions."}

        closed_ids: List[str] = []
        errors: List[str] = []

        for target in targets:
            position_id = str(target.get("positionId", "")).strip()
            if not position_id:
                continue
            position_coin = str(target.get("coin", "")).upper() or "UNKNOWN"
            position_side = str(target.get("side", "")).upper() or "UNKNOWN"
            close_snapshot = self._compact_position_snapshot(target)

            if self.dry_run:
                add_trade(
                    self.db_path,
                    now,
                    "CLOSE",
                    position_coin,
                    position_side,
                    self.margin_boks,
                    self.leverage,
                    "DRY_RUN",
                    json.dumps(
                        {
                            "message": f"manual close {position_id}",
                            "positionId": position_id,
                            "source": "manual",
                            "close_mode": "manual",
                            "comment": comment,
                            "close_snapshot": close_snapshot,
                        }
                    ),
                )
                closed_ids.append(position_id)
                continue

            if not self._can_send_trade(now):
                errors.append(f"{position_id}: rate limit guard blocked this request")
                continue

            try:
                response = self.client.close_trade({"positionId": position_id, "comment": comment})
                add_trade(
                    self.db_path,
                    now,
                    "CLOSE",
                    position_coin,
                    position_side,
                    self.margin_boks,
                    self.leverage,
                    "OK",
                    json.dumps(
                        {
                            **(response if isinstance(response, dict) else {}),
                            "positionId": position_id,
                            "source": "manual",
                            "close_mode": "manual",
                            "close_snapshot": close_snapshot,
                        }
                    ),
                )
                closed_ids.append(position_id)
            except MTCClientError as exc:
                errors.append(f"{position_id}: {exc} ({exc.code})")

        if closed_ids:
            self._set_manual_position_ids([pid for pid in manual_ids if pid not in set(closed_ids)])

        if self.dry_run:
            self._log_structured(now, "INFO", "manual_close_all_dry_run", closed_count=len(closed_ids), closed_ids=closed_ids)
        elif closed_ids:
            self._log_structured(now, "INFO", "manual_close_all_submitted", closed_count=len(closed_ids), closed_ids=closed_ids)

        if errors:
            self._log_structured(now, "WARN", "manual_close_all_partial_failures", failed_count=len(errors), errors=errors)

        success = len(errors) == 0
        message = (
            f"Closed {len(closed_ids)} manual positions."
            if success
            else f"Closed {len(closed_ids)} manual positions, {len(errors)} failed."
        )
        result = {
            "success": success,
            "closed": len(closed_ids),
            "failed": len(errors),
            "closed_ids": closed_ids,
            "errors": errors,
            "message": message,
        }
        if self.dry_run:
            result["dry_run"] = True
        return result

    def close_strategy_position(self, position_id: str = "", comment: str = "Manual close strategy position") -> Dict[str, Any]:
        now = int(time.time())
        if not self.client.api_key:
            return {"success": False, "message": "MTC_API_KEY is missing."}

        positions = self._fetch_positions(now)
        self._sync_owned_position_ids(now, positions)
        strategy_map = self._get_strategy_position_map()
        strategy_ids = list(dict.fromkeys([str(pid) for pid in strategy_map.values() if str(pid)]))
        if not strategy_ids:
            return {"success": True, "closed": 0, "message": "No open strategy positions."}

        selected_id = str(position_id or "").strip()
        if selected_id and selected_id not in strategy_ids:
            return {"success": False, "message": "Selected position is not a strategy-owned position."}

        target_id = selected_id or strategy_ids[0]
        target = self._find_position_by_id(positions, target_id)

        if not target:
            return {"success": False, "message": "Selected strategy position is not open."}

        resolved_position_id = str(target.get("positionId", ""))
        if not resolved_position_id:
            return {"success": False, "message": "Strategy position id is invalid."}
        position_coin = str(target.get("coin", "")).upper() or "UNKNOWN"
        position_side = str(target.get("side", "")).upper() or "UNKNOWN"
        close_snapshot = self._compact_position_snapshot(target)

        if self.dry_run:
            add_trade(
                self.db_path,
                now,
                "CLOSE",
                position_coin,
                position_side,
                self.margin_boks,
                self.leverage,
                "DRY_RUN",
                json.dumps(
                    {
                        "message": f"strategy close {resolved_position_id}",
                        "positionId": resolved_position_id,
                        "source": "strategy",
                        "close_mode": "strategy_manual",
                        "comment": comment,
                        "close_snapshot": close_snapshot,
                    }
                ),
            )
            self._log_structured(
                now,
                "INFO",
                "strategy_close_dry_run",
                position_id=resolved_position_id,
                external_id=self._close_external_id(resolved_position_id),
            )
            return {
                "success": True,
                "dry_run": True,
                "message": "DRY_RUN simulated strategy position close.",
                "closed": 1,
                "position_id": resolved_position_id,
            }

        if not self._can_send_trade(now):
            return {"success": False, "message": "Rate limit guard blocked this request."}

        try:
            response = self.client.close_trade({"positionId": resolved_position_id, "comment": comment})
            add_trade(
                self.db_path,
                now,
                "CLOSE",
                position_coin,
                position_side,
                self.margin_boks,
                self.leverage,
                "OK",
                json.dumps(
                    {
                        **(response if isinstance(response, dict) else {}),
                        "positionId": resolved_position_id,
                        "source": "strategy",
                        "close_mode": "strategy_manual",
                        "close_snapshot": close_snapshot,
                    }
                ),
            )
            next_strategy_map = {slot: pid for slot, pid in strategy_map.items() if pid != resolved_position_id}
            self._set_strategy_position_map(next_strategy_map)
            self._log_structured(
                now,
                "INFO",
                "strategy_close_manual_submitted",
                position_id=resolved_position_id,
                external_id=self._close_external_id(resolved_position_id),
            )
            return {
                "success": True,
                "closed": 1,
                "message": "Closed strategy position.",
                "position_id": resolved_position_id,
            }
        except MTCClientError as exc:
            self._log_structured(
                now,
                "ERROR",
                "strategy_close_manual_failed",
                position_id=resolved_position_id,
                error=str(exc),
                error_code=exc.code,
            )
            return {"success": False, "message": f"Close failed: {exc}", "code": exc.code}

    def close_all_strategy_positions(self, comment: str = "Manual close all strategy positions") -> Dict[str, Any]:
        now = int(time.time())
        if not self.client.api_key:
            return {"success": False, "message": "MTC_API_KEY is missing."}

        positions = self._fetch_positions(now)
        self._sync_owned_position_ids(now, positions)
        strategy_map = self._get_strategy_position_map()
        strategy_ids = list(dict.fromkeys([str(pid) for pid in strategy_map.values() if str(pid)]))
        if not strategy_ids:
            return {"success": True, "closed": 0, "message": "No open strategy positions."}

        targets: List[Dict[str, Any]] = []
        for pid in strategy_ids:
            pos = self._find_position_by_id(positions, pid)
            if pos:
                targets.append(pos)

        if not targets:
            self._set_strategy_position_map({})
            return {"success": True, "closed": 0, "message": "No open strategy positions."}

        closed_ids: List[str] = []
        errors: List[str] = []

        for target in targets:
            resolved_position_id = str(target.get("positionId", "")).strip()
            if not resolved_position_id:
                continue
            position_coin = str(target.get("coin", "")).upper() or "UNKNOWN"
            position_side = str(target.get("side", "")).upper() or "UNKNOWN"
            close_snapshot = self._compact_position_snapshot(target)

            if self.dry_run:
                add_trade(
                    self.db_path,
                    now,
                    "CLOSE",
                    position_coin,
                    position_side,
                    self.margin_boks,
                    self.leverage,
                    "DRY_RUN",
                    json.dumps(
                        {
                            "message": f"strategy close {resolved_position_id}",
                            "positionId": resolved_position_id,
                            "source": "strategy",
                            "close_mode": "strategy_manual_all",
                            "comment": comment,
                            "close_snapshot": close_snapshot,
                        }
                    ),
                )
                closed_ids.append(resolved_position_id)
                continue

            if not self._can_send_trade(now):
                errors.append(f"{resolved_position_id}: rate limit guard blocked this request")
                continue

            try:
                response = self.client.close_trade({"positionId": resolved_position_id, "comment": comment})
                add_trade(
                    self.db_path,
                    now,
                    "CLOSE",
                    position_coin,
                    position_side,
                    self.margin_boks,
                    self.leverage,
                    "OK",
                    json.dumps(
                        {
                            **(response if isinstance(response, dict) else {}),
                            "positionId": resolved_position_id,
                            "source": "strategy",
                            "close_mode": "strategy_manual_all",
                            "close_snapshot": close_snapshot,
                        }
                    ),
                )
                closed_ids.append(resolved_position_id)
            except MTCClientError as exc:
                errors.append(f"{resolved_position_id}: {exc} ({exc.code})")

        if closed_ids:
            closed_set = set(closed_ids)
            next_strategy_map = {slot: pid for slot, pid in strategy_map.items() if pid not in closed_set}
            self._set_strategy_position_map(next_strategy_map)

        if self.dry_run:
            self._log_structured(now, "INFO", "strategy_close_all_dry_run", closed_count=len(closed_ids), closed_ids=closed_ids)
        elif closed_ids:
            self._log_structured(now, "INFO", "strategy_close_all_submitted", closed_count=len(closed_ids), closed_ids=closed_ids)

        if errors:
            self._log_structured(now, "WARN", "strategy_close_all_partial_failures", failed_count=len(errors), errors=errors)

        success = len(errors) == 0
        message = (
            f"Closed {len(closed_ids)} strategy positions."
            if success
            else f"Closed {len(closed_ids)} strategy positions, {len(errors)} failed."
        )
        result = {
            "success": success,
            "closed": len(closed_ids),
            "failed": len(errors),
            "closed_ids": closed_ids,
            "errors": errors,
            "message": message,
        }
        if self.dry_run:
            result["dry_run"] = True
        return result

    def _collect_regime_candidates(self, now: int, account: Dict[str, Any], positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for symbol in self.STRATEGY_TARGET_SYMBOLS:
            self._set_strategy_context(self.STRATEGY_REGIME_SWITCH, symbol)
            if self._count_regime_open_longs_for_coin(self.trade_coin, positions) >= self.REGIME_MAX_OPEN_LONGS_PER_SYMBOL:
                self._inc_regime_metric("symbol_cap_blocked_total", 1)
                continue

            state = self._get_regime_state()
            market = self._get_regime_market_snapshot(now, symbol)
            snapshot = market.get("snapshot", {}) if isinstance(market, dict) else {}
            candles = market.get("candles", []) if isinstance(market, dict) else []
            candle_key = _to_int(market.get("candle_key", 0), 0)
            if not isinstance(snapshot, dict) or not snapshot.get("ok"):
                continue
            if _to_int(state.get("last_processed_candle", 0), 0) == candle_key:
                continue

            equity = self._account_total_equity(account, positions)
            day_key = self._current_day_key(now)
            if str(state.get("day_key", "")) != day_key:
                state["day_key"] = day_key
                state["day_start_equity"] = equity
                state["trading_blocked_today"] = False
            day_start = max(_to_float(state.get("day_start_equity", equity), equity), 1e-9)
            day_drawdown_pct = (equity - day_start) / day_start
            state["day_drawdown_pct"] = day_drawdown_pct
            if day_drawdown_pct <= -self.REGIME_MAX_DAILY_DRAWDOWN:
                state["trading_blocked_today"] = True

            cooldown = _to_int(state.get("cooldown_remaining_bars", 0), 0)
            if cooldown > 0:
                state["cooldown_remaining_bars"] = cooldown - 1
                state["last_processed_candle"] = candle_key
                self._set_regime_state(state)
                continue
            if bool(state.get("trading_blocked_today", False)):
                state["last_processed_candle"] = candle_key
                self._set_regime_state(state)
                continue

            signal = evaluate_regime_switch_entry_long_4h(candles)
            add_signal(self.db_path, now, self.trade_coin, "4h", bool(signal.get("signal")), json.dumps(signal))
            if not signal.get("signal"):
                state["last_processed_candle"] = _to_int(signal.get("last_candle_open_time", candle_key), candle_key)
                state["last_regime"] = str(signal.get("regime", snapshot.get("regime", "NO_TRADE")))
                self._set_regime_state(state)
                continue

            atr_now = _to_float(signal.get("atr14", 0.0), 0.0)
            atr_prev = _to_float(signal.get("atr14_prev", atr_now), atr_now)
            if atr_prev > 0 and atr_now >= (atr_prev * self.REGIME_VOLATILITY_SHOCK_MULT):
                self._inc_regime_metric("volatility_shock_skipped_total", 1)
                state["cooldown_remaining_bars"] = max(_to_int(state.get("cooldown_remaining_bars", 0), 0), 1)
                state["last_processed_candle"] = _to_int(signal.get("last_candle_open_time", candle_key), candle_key)
                state["last_regime"] = str(signal.get("regime", snapshot.get("regime", "NO_TRADE")))
                self._set_regime_state(state)
                self._log_structured(
                    now,
                    "WARN",
                    "regime_entry_skipped_volatility_shock",
                    symbol=symbol,
                    atr_now=atr_now,
                    atr_prev=atr_prev,
                    mult=self.REGIME_VOLATILITY_SHOCK_MULT,
                )
                continue

            signal["_score"] = self._score_regime_candidate(signal)
            signal["_symbol"] = symbol
            self._inc_regime_metric("candidates_total", 1)
            candidates.append(signal)
        return candidates

    def _open_regime_candidate(self, now: int, candidate: Dict[str, Any], account: Dict[str, Any], positions: List[Dict[str, Any]]) -> bool:
        symbol = str(candidate.get("_symbol", self.trade_pair) or self.trade_pair)
        self._set_strategy_context(self.STRATEGY_REGIME_SWITCH, symbol)
        signal_key = self._regime_entry_key()
        candle_key = str(int(_to_float(candidate.get("last_candle_open_time", 0), 0.0)))
        if get_kv(self.db_path, signal_key, "") == candle_key:
            return False

        payload = self._build_regime_open_payload(candidate, account, positions)
        if not payload:
            return False

        if self.dry_run:
            add_trade(
                self.db_path,
                now,
                "OPEN",
                self.trade_coin,
                "LONG",
                _to_float(payload.get("margin", self.margin_boks), self.margin_boks),
                self.leverage,
                "DRY_RUN",
                json.dumps(payload),
            )
            set_kv(self.db_path, signal_key, candle_key)
            state = self._get_regime_state()
            state.update(
                {
                    "position_id": "",
                    "entry_price": _to_float(payload.get("entry_price", 0), 0.0),
                    "stop_price": _to_float(payload.get("stopLoss", 0), 0.0),
                    "initial_stop_price": _to_float(payload.get("stopLoss", 0), 0.0),
                    "take_profit_price": _to_float(payload.get("takeProfit", 0), 0.0),
                    "trailing_stop_price": max(
                        _to_float(payload.get("entry_price", 0), 0.0) - (self.REGIME_TREND_TRAIL_ATR_MULT * _to_float(payload.get("atr14", 0), 0.0)),
                        0.0,
                    ),
                    "moved_to_be": False,
                    "regime_at_entry": str(payload.get("regime", "NO_TRADE")),
                    "last_regime": str(payload.get("regime", "NO_TRADE")),
                    "last_processed_candle": _to_int(candidate.get("last_candle_open_time", 0), 0),
                    "last_entry_type": str(payload.get("entry_type", "")),
                }
            )
            self._set_regime_state(state)
            return True

        if not self._can_send_trade(now):
            return False

        response = self.client.open_trade(
            {
                "coin": payload["coin"],
                "side": payload["side"],
                "margin": payload["margin"],
                "leverage": payload["leverage"],
                "stopLoss": payload["stopLoss"],
                "takeProfit": payload["takeProfit"],
                "comment": payload["comment"],
            }
        )
        add_trade(
            self.db_path,
            now,
            "OPEN",
            self.trade_coin,
            "LONG",
            _to_float(payload.get("margin", self.margin_boks), self.margin_boks),
            self.leverage,
            "OK",
            json.dumps(response),
        )
        self._capture_owner_position_id("strategy", now, positions, response)
        set_kv(self.db_path, signal_key, candle_key)
        state = self._get_regime_state()
        strategy_position_id = self._get_owner_position_id("strategy")
        state.update(
            {
                "position_id": strategy_position_id,
                "entry_price": _to_float(payload.get("entry_price", 0), 0.0),
                "stop_price": _to_float(payload.get("stopLoss", 0), 0.0),
                "initial_stop_price": _to_float(payload.get("stopLoss", 0), 0.0),
                "take_profit_price": _to_float(payload.get("takeProfit", 0), 0.0),
                "trailing_stop_price": max(
                    _to_float(payload.get("entry_price", 0), 0.0) - (self.REGIME_TREND_TRAIL_ATR_MULT * _to_float(payload.get("atr14", 0), 0.0)),
                    0.0,
                ),
                "moved_to_be": False,
                "regime_at_entry": str(payload.get("regime", "NO_TRADE")),
                "last_regime": str(payload.get("regime", "NO_TRADE")),
                "last_processed_candle": _to_int(candidate.get("last_candle_open_time", 0), 0),
                "last_entry_type": str(payload.get("entry_type", "")),
            }
        )
        self._set_regime_state(state)
        self._log_structured(
            now,
            "INFO",
            "regime_open_submitted",
            symbol=symbol,
            side="LONG",
            margin=_to_float(payload.get("margin", 0), 0.0),
            score=_to_float(candidate.get("_score", 0), 0.0),
            position_id=strategy_position_id,
        )
        return True

    def _maybe_open_long(self, now: int, account: Dict[str, Any], positions: List[Dict[str, Any]]) -> None:
        if self._owner_has_open_position("strategy", positions):
            self._log_structured(now, "INFO", "strategy_entry_skipped_position_exists", symbol=self.trade_pair)
            return
        if self.active_strategy == self.STRATEGY_EMA_RSI and self._has_any_open_long_on_coin(positions, self.trade_coin):
            self._log_structured(now, "INFO", "strategy_entry_skipped_long_exists", symbol=self.trade_pair, strategy=self.active_strategy)
            return
        if self.active_strategy == self.STRATEGY_REGIME_SWITCH and self._has_any_open_long_on_coin(positions, self.trade_coin):
            self._log_structured(now, "INFO", "strategy_entry_skipped_long_exists", symbol=self.trade_pair, strategy=self.active_strategy)
            return
        if self.active_strategy == self.STRATEGY_REGIME_SWITCH and self._available_regime_slots(positions) <= 0:
            self._inc_regime_metric("cap_blocked_total", 1)
            self._log_structured(now, "INFO", "regime_entry_skipped_total_cap", cap=self.REGIME_MAX_OPEN_LONGS_TOTAL)
            return
        if len(positions) >= self.max_positions:
            self._log_structured(now, "WARN", "strategy_entry_skipped_max_positions", max_positions=self.max_positions)
            return

        signal = {}
        signal_timeframe = "4h"
        signal_key = "last_entry_candle"
        regime_state: Dict[str, Any] = {}
        regime_entry_type = ""
        try:
            if self.active_strategy == self.STRATEGY_EMA_RSI:
                candles = self.hyperliquid.get_candles(self.trade_coin, interval="15m", bars=300)
                if len(candles) >= 2:
                    maybe_open = _to_float(candles[-1].get("close_time", 0), 0.0)
                    if maybe_open > (now * 1000):
                        candles = candles[:-1]
                signal = evaluate_long_ema_rsi_15m(candles)
                signal_timeframe = "15m"
                signal_key = "last_entry_candle_ema_rsi"
            elif self.active_strategy == self.STRATEGY_REGIME_SWITCH:
                candles = self._get_closed_4h_candles()
                signal = evaluate_regime_switch_entry_long_4h(candles)
                signal_timeframe = "4h"
                signal_key = self._regime_entry_key()

                regime_state = self._get_regime_state()
                candle_key_now = _to_int(signal.get("last_candle_open_time", 0), 0)
                if _to_int(regime_state.get("last_processed_candle", 0), 0) == candle_key_now:
                    return

                equity = self._account_total_equity(account, positions)
                day_key = self._current_day_key(now)
                if str(regime_state.get("day_key", "")) != day_key:
                    regime_state["day_key"] = day_key
                    regime_state["day_start_equity"] = equity
                    regime_state["trading_blocked_today"] = False
                day_start = max(_to_float(regime_state.get("day_start_equity", equity), equity), 1e-9)
                day_drawdown_pct = (equity - day_start) / day_start
                regime_state["day_drawdown_pct"] = day_drawdown_pct
                if day_drawdown_pct <= -self.REGIME_MAX_DAILY_DRAWDOWN:
                    regime_state["trading_blocked_today"] = True

                cooldown = _to_int(regime_state.get("cooldown_remaining_bars", 0), 0)
                if cooldown > 0:
                    regime_state["cooldown_remaining_bars"] = cooldown - 1
                    regime_state["last_processed_candle"] = candle_key_now
                    self._set_regime_state(regime_state)
                    self._log_structured(
                        now,
                        "INFO",
                        "regime_entry_skipped_cooldown",
                        strategy=self.active_strategy,
                        symbol=self.trade_pair,
                        cooldown_remaining=regime_state["cooldown_remaining_bars"],
                    )
                    return

                if bool(regime_state.get("trading_blocked_today", False)):
                    regime_state["last_processed_candle"] = candle_key_now
                    self._set_regime_state(regime_state)
                    self._log_structured(
                        now,
                        "WARN",
                        "regime_entry_blocked_daily_drawdown",
                        strategy=self.active_strategy,
                        symbol=self.trade_pair,
                        day_drawdown_pct=day_drawdown_pct,
                    )
                    return
                regime_entry_type = str(signal.get("entry_type", "") or "")
            else:
                candles = self.hyperliquid.get_candles(self.trade_coin, interval="4h", bars=90)
                signal = evaluate_long_ma50_cross_3_candles(candles)
                signal_timeframe = "4h"
                signal_key = "last_entry_candle"
        except Exception as exc:
            self._log_structured(now, "ERROR", "strategy_entry_market_data_failed", strategy=self.active_strategy, error=str(exc))
            return

        add_signal(self.db_path, now, self.trade_coin, signal_timeframe, bool(signal.get("signal")), json.dumps(signal))
        set_kv(self.db_path, "last_signal", json.dumps(signal))

        if not signal.get("signal"):
            if self.active_strategy == self.STRATEGY_REGIME_SWITCH and regime_state:
                regime_state["last_processed_candle"] = _to_int(signal.get("last_candle_open_time", 0), 0)
                regime_state["last_regime"] = str(signal.get("regime", "NO_TRADE"))
                self._set_regime_state(regime_state)
            self._log_structured(
                now,
                "INFO",
                "strategy_entry_skipped_no_signal",
                strategy=self.active_strategy,
                reason=str(signal.get("reason", "") or ""),
            )
            return

        candle_key = str(int(_to_float(signal.get("last_candle_open_time", 0), 0.0)))
        if get_kv(self.db_path, signal_key, "") == candle_key:
            self._log_structured(now, "INFO", "strategy_entry_skipped_candle_already_traded", strategy=self.active_strategy, candle_key=candle_key)
            return

        capital = parse_total_capital(account)
        if capital <= 0:
            self._log_structured(now, "WARN", "strategy_entry_skipped_no_capital", strategy=self.active_strategy)
            return

        entry_price = _to_float(signal.get("close", 0), 0.0)
        if entry_price <= 0:
            self._log_structured(now, "WARN", "strategy_entry_skipped_invalid_entry_price", strategy=self.active_strategy)
            return

        risk_targets = build_long_sl_tp_prices(
            entry_price=entry_price,
            capital=capital,
            margin=self.margin_boks,
            leverage=self.leverage,
            sl_capital_pct=self.sl_capital_pct,
            tp_capital_pct=(self.sl_capital_pct * 2) if self.active_strategy == self.STRATEGY_EMA_RSI else self.tp_capital_pct,
        )

        comment = "MA50(4H) cross-up confirmed by 3 closes. Long setup."
        if self.active_strategy == self.STRATEGY_EMA_RSI:
            comment = "EMA20>EMA50 with RSI 50-70 on closed 15m candle. Long setup."
        margin_to_use = self.margin_boks
        if self.active_strategy == self.STRATEGY_REGIME_SWITCH:
            regime = str(signal.get("regime", "NO_TRADE"))
            atr_now = _to_float(signal.get("atr14", 0), 0.0)
            if regime == "TREND":
                stop_price = entry_price - (self.REGIME_TREND_STOP_ATR_MULT * atr_now)
            else:
                stop_price = entry_price - (self.REGIME_RANGE_STOP_ATR_MULT * atr_now)
            stop_price = max(stop_price, 0.0)
            if stop_price <= 0 or stop_price >= entry_price:
                self._log_structured(
                    now,
                    "WARN",
                    "regime_entry_skipped_invalid_stop",
                    strategy=self.active_strategy,
                    symbol=self.trade_pair,
                    stop_price=stop_price,
                    entry_price=entry_price,
                )
                return
            margin_to_use = self._build_regime_margin(entry_price, stop_price, capital, positions)
            if regime == "RANGE":
                take_profit = _to_float(signal.get("bb_mid", 0), 0.0)
            else:
                take_profit = risk_targets["take_profit"]
            risk_targets = {
                **risk_targets,
                "stop_loss": stop_price,
                "take_profit": max(take_profit, 0.0),
            }
            comment = (
                "Regime TREND breakout on closed 4H candle. Long setup."
                if regime == "TREND"
                else "Regime RANGE mean-reversion on closed 4H candle. Long setup."
            )

        payload = {
            "coin": self.trade_coin,
            "side": "LONG",
            "margin": margin_to_use,
            "leverage": self.leverage,
            "stopLoss": round(risk_targets["stop_loss"], 6),
            "takeProfit": round(risk_targets["take_profit"], 6),
            "comment": comment,
        }

        if self.dry_run:
            self._log_structured(now, "INFO", "strategy_open_dry_run", symbol=self.trade_pair, side="LONG", payload=payload)
            add_trade(
                self.db_path,
                now,
                "OPEN",
                self.trade_coin,
                "LONG",
                margin_to_use,
                self.leverage,
                "DRY_RUN",
                json.dumps(payload),
            )
            set_kv(self.db_path, signal_key, candle_key)
            if self.active_strategy == self.STRATEGY_REGIME_SWITCH:
                regime = str(signal.get("regime", "NO_TRADE"))
                regime_state = regime_state or self._get_regime_state()
                regime_state.update(
                    {
                        "position_id": "",
                        "entry_price": entry_price,
                        "stop_price": payload["stopLoss"],
                        "initial_stop_price": payload["stopLoss"],
                        "take_profit_price": payload["takeProfit"],
                        "trailing_stop_price": max(entry_price - (self.REGIME_TREND_TRAIL_ATR_MULT * _to_float(signal.get("atr14", 0), 0.0)), 0.0),
                        "moved_to_be": False,
                        "regime_at_entry": regime,
                        "last_regime": regime,
                        "last_processed_candle": _to_int(signal.get("last_candle_open_time", 0), 0),
                    }
                )
                self._set_regime_state(regime_state)
            return

        if not self._can_send_trade(now):
            self._log_structured(now, "WARN", "strategy_open_rate_limited", symbol=self.trade_pair, side="LONG")
            return

        try:
            response = self.client.open_trade(payload)
            add_trade(
                self.db_path,
                now,
                "OPEN",
                self.trade_coin,
                "LONG",
                margin_to_use,
                self.leverage,
                "OK",
                json.dumps(response),
            )
            self._capture_owner_position_id("strategy", now, positions, response)
            if self.active_strategy == self.STRATEGY_EMA_RSI:
                latest_positions = self._fetch_positions(now)
                strategy_position_id = self._get_owner_position_id("strategy")
                strategy_position = self._find_position_by_id(latest_positions, strategy_position_id)
                if strategy_position:
                    self._ensure_ema_state(now, strategy_position, account)
            if self.active_strategy == self.STRATEGY_REGIME_SWITCH:
                latest_positions = self._fetch_positions(now)
                strategy_position_id = self._get_owner_position_id("strategy")
                strategy_position = self._find_position_by_id(latest_positions, strategy_position_id)
                regime = str(signal.get("regime", "NO_TRADE"))
                regime_state = regime_state or self._get_regime_state()
                regime_state.update(
                    {
                        "position_id": strategy_position_id,
                        "entry_price": entry_price,
                        "stop_price": payload["stopLoss"],
                        "initial_stop_price": payload["stopLoss"],
                        "take_profit_price": payload["takeProfit"],
                        "trailing_stop_price": max(entry_price - (self.REGIME_TREND_TRAIL_ATR_MULT * _to_float(signal.get("atr14", 0), 0.0)), 0.0),
                        "moved_to_be": False,
                        "regime_at_entry": regime,
                        "last_regime": regime,
                        "last_processed_candle": _to_int(signal.get("last_candle_open_time", 0), 0),
                        "last_entry_type": regime_entry_type,
                    }
                )
                if strategy_position:
                    regime_state["position_id"] = str(strategy_position.get("positionId", "") or strategy_position_id)
                self._set_regime_state(regime_state)
            set_kv(self.db_path, signal_key, candle_key)
            position_id = str(response.get("positionId", "") or "")
            self._log_structured(
                now,
                "INFO",
                "strategy_open_submitted",
                symbol=self.trade_pair,
                side="LONG",
                position_id=position_id,
                margin=margin_to_use,
            )
        except MTCClientError as exc:
            add_trade(
                self.db_path,
                now,
                "OPEN",
                self.trade_coin,
                "LONG",
                self.margin_boks,
                self.leverage,
                "ERROR",
                f"{exc} ({exc.code})",
            )
            self._log_structured(
                now,
                "ERROR",
                "strategy_open_failed",
                symbol=self.trade_pair,
                side="LONG",
                error=str(exc),
                error_code=exc.code,
            )

    def _maybe_daily_claim(self, now: int) -> None:
        if self.dry_run:
            return
        last_claim_try = int(get_kv(self.db_path, "last_daily_claim_try", "0") or 0)
        if now - last_claim_try < 3600:
            return
        set_kv(self.db_path, "last_daily_claim_try", str(now))
        try:
            result = self.client.daily_claim()
            add_log(self.db_path, now, "INFO", f"Daily claim result: {result}")
        except MTCClientError as exc:
            if exc.code != "COOLDOWN":
                add_log(self.db_path, now, "WARN", f"Daily claim failed: {exc} ({exc.code})")

    def _can_send_trade(self, now: int) -> bool:
        with self._trade_lock:
            while self._trade_timestamps and (now - self._trade_timestamps[0]) > 60:
                self._trade_timestamps.popleft()
            if len(self._trade_timestamps) >= 9:
                return False
            self._trade_timestamps.append(now)
            return True
