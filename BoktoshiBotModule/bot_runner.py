import json
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from .hyperliquid_client import HyperliquidClient
from .mtc_client import MTCClient, MTCClientError
from .risk import build_long_sl_tp_prices, parse_total_capital
from .storage import add_equity_snapshot, add_log, add_signal, add_trade, get_kv, set_kv
from .strategy import evaluate_exit_ema_cross_down_15m, evaluate_long_ema_rsi_15m, evaluate_long_ma50_cross_3_candles


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
    MANUAL_ALLOWED_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "HYPEUSDT", "PUMPUSDT", "DOGEUSDT"]
    MANUAL_MAX_POSITIONS = 3
    STRATEGY_MA50 = "MA50_4H_CROSSUP_3C_LONG_ONLY"
    STRATEGY_EMA_RSI = "EMA_RSI_15M_ETH_ONLY"
    EMA_STATE_KEY = "ema_strategy_state"

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
        self._strategy_paused = False
        self.active_strategy = self.STRATEGY_MA50

    def get_runtime_settings(self) -> Dict[str, float]:
        with self._state_lock:
            return {
                "margin_boks": float(self.margin_boks),
                "leverage": float(self.leverage),
                "sl_capital_pct": float(self.sl_capital_pct),
                "tp_capital_pct": float(self.tp_capital_pct),
            }

    def get_active_strategy(self) -> str:
        return self.active_strategy

    def list_strategies(self) -> List[Dict[str, str]]:
        return [
            {
                "id": self.STRATEGY_MA50,
                "label": "MA50 4H CrossUp 3 Candles (ETH only)",
                "entry": "Price crosses above MA50 then closes above MA50 for 3 consecutive 4H candles.",
            },
            {
                "id": self.STRATEGY_EMA_RSI,
                "label": "EMA20/50 + RSI filter 15m (ETH only)",
                "entry": "EMA20 cross above EMA50 with RSI in 50-70 band on closed 15m candle.",
            },
        ]

    def set_active_strategy(self, strategy_id: str) -> Dict[str, Any]:
        selected = str(strategy_id or "").strip().upper()
        valid_ids = {item["id"] for item in self.list_strategies()}
        if selected not in valid_ids:
            return {"success": False, "message": f"Unsupported strategy: {strategy_id}"}
        self.active_strategy = selected
        set_kv(self.db_path, "active_strategy", selected)
        add_log(self.db_path, int(time.time()), "INFO", f"Active strategy set to {selected}.")
        return {"success": True, "strategy_id": selected}

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
        selected = get_kv(self.db_path, "active_strategy", self.STRATEGY_MA50).upper().strip()
        valid_ids = {item["id"] for item in self.list_strategies()}
        self.active_strategy = selected if selected in valid_ids else self.STRATEGY_MA50
        return self.get_runtime_settings()

    @staticmethod
    def _normalize_coin(symbol: str) -> str:
        value = symbol.upper().strip()
        if value.endswith("USDT"):
            return value[:-4]
        return value

    def _owner_key(self, owner: str) -> str:
        if owner == "manual":
            return "manual_position_ids"
        return f"{owner}_position_id"

    def _get_owner_position_id(self, owner: str) -> str:
        if owner == "manual":
            ids = self._get_manual_position_ids()
            return ids[0] if ids else ""
        return get_kv(self.db_path, self._owner_key(owner), "")

    def _set_owner_position_id(self, owner: str, position_id: str) -> None:
        if owner == "manual":
            if position_id:
                self._set_manual_position_ids([position_id])
            else:
                self._set_manual_position_ids([])
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

            try:
                self._tick(now)
            except Exception as exc:
                add_log(self.db_path, now, "ERROR", f"Tick failure: {exc}")

            time.sleep(self.poll_seconds)

    def _tick(self, now: int) -> None:
        account = self._fetch_account(now)
        positions = self._fetch_positions(now)
        self._sync_owned_position_ids(now, positions)
        history = self._fetch_history(now)
        self._record_equity(now, account, positions)
        self._manage_open_positions(now, account, positions)
        if not self.is_strategy_paused():
            self._maybe_open_long(now, account, positions)
        if now % 3600 < self.poll_seconds:
            self._maybe_daily_claim(now)
        set_kv(self.db_path, "last_history", json.dumps(history))

    def is_strategy_paused(self) -> bool:
        with self._state_lock:
            return self._strategy_paused

    def pause_strategy(self) -> Dict[str, Any]:
        now = int(time.time())
        with self._state_lock:
            if self._strategy_paused:
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
            return account if isinstance(account, dict) else {}
        except MTCClientError as exc:
            set_kv(self.db_path, "account_ok", "false")
            add_log(self.db_path, now, "ERROR", f"Account fetch failed: {exc} ({exc.code})")
            return {}

    def _fetch_positions(self, now: int) -> List[Dict[str, Any]]:
        try:
            response = self.client.get_positions()
            set_kv(self.db_path, "positions", json.dumps(response))
            positions = response.get("positions", response if isinstance(response, list) else [])
            return positions if isinstance(positions, list) else []
        except MTCClientError as exc:
            add_log(self.db_path, now, "ERROR", f"Positions fetch failed: {exc} ({exc.code})")
            return []

    def _fetch_history(self, now: int) -> List[Dict[str, Any]]:
        try:
            response = self.client.get_history(limit=100)
            history = response.get("history", response.get("items", response))
            if isinstance(history, list):
                return history
            return []
        except MTCClientError as exc:
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

    def _sync_owned_position_ids(self, now: int, positions: List[Dict[str, Any]]) -> None:
        strategy_id = self._get_owner_position_id("strategy")
        manual_ids = self._get_manual_position_ids()

        if strategy_id and not self._find_position_by_id(positions, strategy_id):
            self._set_owner_position_id("strategy", "")
            add_log(self.db_path, now, "INFO", f"Cleared stale strategy position id {strategy_id}.")

        valid_manual_ids = [pid for pid in manual_ids if self._find_position_by_id(positions, pid)]
        cleared_ids = [pid for pid in manual_ids if pid not in valid_manual_ids]
        if cleared_ids:
            self._set_manual_position_ids(valid_manual_ids)
            add_log(self.db_path, now, "INFO", f"Cleared stale manual position ids: {', '.join(cleared_ids)}")

        strategy_id = self._get_owner_position_id("strategy")
        manual_ids = self._get_manual_position_ids()
        if strategy_id or manual_ids:
            return

        eth_positions = self._eth_long_positions(positions)
        if not eth_positions:
            return

        if len(eth_positions) == 1:
            fallback_manual = str(eth_positions[0].get("positionId", ""))
            if fallback_manual:
                self._set_manual_position_ids([fallback_manual])
                add_log(
                    self.db_path,
                    now,
                    "WARN",
                    f"Mapped legacy unknown ETH position {fallback_manual} to manual owner.",
                )
            return

        sorted_positions = sorted(eth_positions, key=lambda x: _to_int(x.get("openedAt", 0), 0))
        strategy_fallback = str(sorted_positions[0].get("positionId", ""))
        manual_fallback = str(sorted_positions[-1].get("positionId", ""))
        if strategy_fallback:
            self._set_owner_position_id("strategy", strategy_fallback)
        if manual_fallback and manual_fallback != strategy_fallback:
            self._set_manual_position_ids([manual_fallback])
        add_log(
            self.db_path,
            now,
            "WARN",
            f"Mapped legacy unknown ETH positions to owners strategy={strategy_fallback}, manual={manual_fallback}.",
        )

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
            if str(pos.get("side", "")).upper() != "LONG":
                continue
            if str(pos.get("coin", "")).upper() == coin:
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
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _set_ema_state(self, state: Dict[str, Any]) -> None:
        set_kv(self.db_path, self.EMA_STATE_KEY, json.dumps(state))

    def _clear_ema_state(self) -> None:
        set_kv(self.db_path, self.EMA_STATE_KEY, "")

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
    ) -> None:
        before_ids = {
            str(p.get("positionId", ""))
            for p in before_positions
            if str(p.get("coin", "")).upper() == coin and str(p.get("side", "")).upper() == "LONG"
        }
        after_positions = self._fetch_positions(now)
        after_candidates = [
            p
            for p in after_positions
            if str(p.get("coin", "")).upper() == coin and str(p.get("side", "")).upper() == "LONG"
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
        strategy_id = self._get_owner_position_id("strategy")
        manual_ids = self._get_manual_position_ids()

        strategy_position = self._find_position_by_id(positions, strategy_id)
        manual_positions = [self._find_position_by_id(positions, pid) for pid in manual_ids]
        manual_positions = [p for p in manual_positions if p is not None]
        manual_position = manual_positions[0] if manual_positions else None

        unknown_positions: List[Dict[str, Any]] = []
        for pos in self._eth_long_positions(positions):
            pid = str(pos.get("positionId", ""))
            if pid and pid not in {strategy_id, *manual_ids}:
                unknown_positions.append(pos)

        return {
            "strategy_position": strategy_position,
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
            return

        if self.active_strategy == self.STRATEGY_EMA_RSI:
            self._manage_ema_strategy_position(now, account, strategy_pos)
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
        if self.dry_run:
            add_log(self.db_path, now, "INFO", f"DRY_RUN close {position_id}: {note}")
            add_trade(self.db_path, now, "CLOSE", self.trade_coin, "LONG", self.margin_boks, self.leverage, "DRY_RUN", note)
            return
        if not self._can_send_trade(now):
            add_log(self.db_path, now, "WARN", "Skipped close trade due to rate limit guard.")
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
                json.dumps(response),
            )
            if owner:
                self._set_owner_position_id(owner, "")
            add_log(self.db_path, now, "INFO", f"Closed position {position_id}: {note}")
        except MTCClientError as exc:
            add_log(self.db_path, now, "ERROR", f"Close trade failed: {exc} ({exc.code})")

    def manual_force_open_long(self, symbol: str = "ETHUSDT", comment: str = "Manual force open LONG") -> Dict[str, Any]:
        now = int(time.time())
        if not self.client.api_key:
            return {"success": False, "message": "MTC_API_KEY is missing."}

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
        if len(positions) >= self.max_positions:
            return {"success": False, "message": "Max positions reached."}

        capital = parse_total_capital(account)
        if capital <= 0:
            return {"success": False, "message": "Capital unavailable, cannot open trade."}

        try:
            candles = self.hyperliquid.get_candles(target_coin, interval="4h", bars=5)
        except Exception as exc:
            add_log(self.db_path, now, "ERROR", f"Manual force open failed to fetch candles: {exc}")
            return {"success": False, "message": f"Failed to fetch market data: {exc}"}

        if not candles:
            return {"success": False, "message": "No candles returned from Hyperliquid."}

        entry_price = _to_float(candles[-1].get("close", 0), 0.0)
        if entry_price <= 0:
            return {"success": False, "message": "Invalid entry price from candle data."}

        risk_targets = build_long_sl_tp_prices(
            entry_price=entry_price,
            capital=capital,
            margin=self.margin_boks,
            leverage=self.leverage,
            sl_capital_pct=self.sl_capital_pct,
            tp_capital_pct=self.tp_capital_pct,
        )
        payload = {
            "coin": target_coin,
            "side": "LONG",
            "margin": self.margin_boks,
            "leverage": self.leverage,
            "stopLoss": round(risk_targets["stop_loss"], 6),
            "takeProfit": round(risk_targets["take_profit"], 6),
            "comment": f"{comment} {target_symbol}".strip(),
        }

        if self.dry_run:
            add_trade(
                self.db_path,
                now,
                "OPEN",
                target_coin,
                "LONG",
                self.margin_boks,
                self.leverage,
                "DRY_RUN",
                json.dumps(payload),
            )
            add_log(self.db_path, now, "INFO", f"DRY_RUN manual force open payload: {payload}")
            return {
                "success": True,
                "dry_run": True,
                "message": "DRY_RUN enabled. No live order was sent.",
                "symbol": target_symbol,
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
                "LONG",
                self.margin_boks,
                self.leverage,
                "OK",
                json.dumps(response),
            )
            self._capture_manual_position_id(now, positions, response, target_coin)
            add_log(self.db_path, now, "INFO", f"Manual force open success on {target_symbol}.")
            return {"success": True, "dry_run": False, "message": "Force open submitted.", "symbol": target_symbol, "response": response}
        except MTCClientError as exc:
            add_trade(
                self.db_path,
                now,
                "OPEN",
                target_coin,
                "LONG",
                self.margin_boks,
                self.leverage,
                "ERROR",
                f"{exc} ({exc.code})",
            )
            add_log(self.db_path, now, "ERROR", f"Manual force open failed: {exc} ({exc.code})")
            return {"success": False, "message": f"Open failed: {exc}", "code": exc.code}

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

        if self.dry_run:
            add_trade(
                self.db_path,
                now,
                "CLOSE",
                position_coin,
                "LONG",
                self.margin_boks,
                self.leverage,
                "DRY_RUN",
                f"manual close {resolved_position_id}",
            )
            add_log(self.db_path, now, "INFO", "DRY_RUN manual close for manual-owned position.")
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
                "LONG",
                self.margin_boks,
                self.leverage,
                "OK",
                json.dumps(response),
            )
            self._set_manual_position_ids([pid for pid in manual_ids if pid != resolved_position_id])
            add_log(self.db_path, now, "INFO", f"Manual close success for manual position {resolved_position_id}.")
            return {"success": True, "closed": 1, "message": "Closed manual position.", "position_id": resolved_position_id}
        except MTCClientError as exc:
            add_log(self.db_path, now, "ERROR", f"Manual close failed {resolved_position_id}: {exc} ({exc.code})")
            return {"success": False, "message": f"Close failed: {exc}", "code": exc.code}

    def close_strategy_position(self, comment: str = "Manual close strategy ETHUSDT") -> Dict[str, Any]:
        now = int(time.time())
        if not self.client.api_key:
            return {"success": False, "message": "MTC_API_KEY is missing."}

        positions = self._fetch_positions(now)
        self._sync_owned_position_ids(now, positions)
        strategy_id = self._get_owner_position_id("strategy")
        target = self._find_position_by_id(positions, strategy_id)

        if not target:
            return {"success": False, "message": "No open strategy ETHUSDT position."}

        position_id = str(target.get("positionId", ""))
        if not position_id:
            return {"success": False, "message": "Strategy position id is invalid."}

        if self.dry_run:
            add_trade(
                self.db_path,
                now,
                "CLOSE",
                self.trade_coin,
                "LONG",
                self.margin_boks,
                self.leverage,
                "DRY_RUN",
                f"strategy close {position_id}",
            )
            add_log(self.db_path, now, "INFO", "DRY_RUN close strategy position request accepted.")
            return {"success": True, "dry_run": True, "message": "DRY_RUN simulated strategy position close.", "closed": 1}

        if not self._can_send_trade(now):
            return {"success": False, "message": "Rate limit guard blocked this request."}

        try:
            response = self.client.close_trade({"positionId": position_id, "comment": comment})
            add_trade(
                self.db_path,
                now,
                "CLOSE",
                self.trade_coin,
                "LONG",
                self.margin_boks,
                self.leverage,
                "OK",
                json.dumps(response),
            )
            self._set_owner_position_id("strategy", "")
            add_log(self.db_path, now, "INFO", f"Manual close success for strategy position {position_id}.")
            return {"success": True, "closed": 1, "message": "Closed strategy position."}
        except MTCClientError as exc:
            add_log(self.db_path, now, "ERROR", f"Close strategy failed {position_id}: {exc} ({exc.code})")
            return {"success": False, "message": f"Close failed: {exc}", "code": exc.code}

    def _maybe_open_long(self, now: int, account: Dict[str, Any], positions: List[Dict[str, Any]]) -> None:
        if self._owner_has_open_position("strategy", positions):
            add_log(self.db_path, now, "INFO", f"Strategy position already open for {self.trade_coin}. No new entry.")
            return
        if self.active_strategy == self.STRATEGY_EMA_RSI and self._has_any_open_long_on_coin(positions, self.trade_coin):
            add_log(self.db_path, now, "INFO", f"Open LONG already exists on {self.trade_coin}. EMA strategy keeps one position per symbol.")
            return
        if len(positions) >= self.max_positions:
            add_log(self.db_path, now, "WARN", "Max positions reached. Skip entry.")
            return

        signal = {}
        signal_timeframe = "4h"
        signal_key = "last_entry_candle"
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
            else:
                candles = self.hyperliquid.get_candles(self.trade_coin, interval="4h", bars=90)
                signal = evaluate_long_ma50_cross_3_candles(candles)
                signal_timeframe = "4h"
                signal_key = "last_entry_candle"
        except Exception as exc:
            add_log(self.db_path, now, "ERROR", f"Hyperliquid candles fetch failed: {exc}")
            return

        add_signal(self.db_path, now, self.trade_coin, signal_timeframe, bool(signal.get("signal")), json.dumps(signal))
        set_kv(self.db_path, "last_signal", json.dumps(signal))

        if not signal.get("signal"):
            add_log(self.db_path, now, "INFO", f"No entry signal: {signal.get('reason')}")
            return

        candle_key = str(int(_to_float(signal.get("last_candle_open_time", 0), 0.0)))
        if get_kv(self.db_path, signal_key, "") == candle_key:
            add_log(self.db_path, now, "INFO", "Signal already traded for this candle.")
            return

        capital = parse_total_capital(account)
        if capital <= 0:
            add_log(self.db_path, now, "WARN", "Capital unavailable. Skip entry.")
            return

        entry_price = _to_float(signal.get("close", 0), 0.0)
        if entry_price <= 0:
            add_log(self.db_path, now, "WARN", "Invalid entry price from candles.")
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

        payload = {
            "coin": self.trade_coin,
            "side": "LONG",
            "margin": self.margin_boks,
            "leverage": self.leverage,
            "stopLoss": round(risk_targets["stop_loss"], 6),
            "takeProfit": round(risk_targets["take_profit"], 6),
            "comment": comment,
        }

        if self.dry_run:
            add_log(self.db_path, now, "INFO", f"DRY_RUN open long payload: {payload}")
            add_trade(
                self.db_path,
                now,
                "OPEN",
                self.trade_coin,
                "LONG",
                self.margin_boks,
                self.leverage,
                "DRY_RUN",
                json.dumps(payload),
            )
            set_kv(self.db_path, signal_key, candle_key)
            return

        if not self._can_send_trade(now):
            add_log(self.db_path, now, "WARN", "Skipped open trade due to rate limit guard.")
            return

        try:
            response = self.client.open_trade(payload)
            add_trade(
                self.db_path,
                now,
                "OPEN",
                self.trade_coin,
                "LONG",
                self.margin_boks,
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
            set_kv(self.db_path, signal_key, candle_key)
            add_log(self.db_path, now, "INFO", f"Opened strategy long on {self.trade_coin}.")
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
            add_log(self.db_path, now, "ERROR", f"Open trade failed: {exc} ({exc.code})")

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
