from typing import Any, Dict, List, Optional


def sma(values: List[float], period: int) -> List[float]:
    if period <= 0:
        raise ValueError("period must be > 0")
    if len(values) < period:
        return []
    out: List[float] = []
    rolling = sum(values[:period])
    out.append(rolling / period)
    for idx in range(period, len(values)):
        rolling += values[idx] - values[idx - period]
        out.append(rolling / period)
    return out


def ema(values: List[float], period: int) -> List[float]:
    if period <= 0:
        raise ValueError("period must be > 0")
    if len(values) < period:
        return []
    seed = sum(values[:period]) / period
    out: List[float] = [seed]
    alpha = 2 / (period + 1)
    prev = seed
    for idx in range(period, len(values)):
        current = (values[idx] - prev) * alpha + prev
        out.append(current)
        prev = current
    return out


def stddev(values: List[float], period: int) -> List[float]:
    if period <= 0:
        raise ValueError("period must be > 0")
    if len(values) < period:
        return []
    out: List[float] = []
    for idx in range(period - 1, len(values)):
        window = values[idx - period + 1 : idx + 1]
        mean = sum(window) / period
        variance = sum((v - mean) ** 2 for v in window) / period
        out.append(variance ** 0.5)
    return out


def rsi(values: List[float], period: int) -> List[float]:
    if period <= 0:
        raise ValueError("period must be > 0")
    if len(values) < period + 1:
        return []

    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    out: List[float] = []
    if avg_loss == 0:
        out.append(100.0)
    else:
        rs = avg_gain / avg_loss
        out.append(100 - (100 / (1 + rs)))

    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        if avg_loss == 0:
            out.append(100.0)
        else:
            rs = avg_gain / avg_loss
            out.append(100 - (100 / (1 + rs)))
    return out


def atr(candles: List[Dict[str, float]], period: int = 14) -> List[float]:
    if period <= 0:
        raise ValueError("period must be > 0")
    if len(candles) < period + 1:
        return []

    true_ranges: List[float] = []
    for i in range(1, len(candles)):
        high = float(candles[i].get("high", 0.0))
        low = float(candles[i].get("low", 0.0))
        prev_close = float(candles[i - 1].get("close", 0.0))
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    seed = sum(true_ranges[:period]) / period
    out: List[float] = [seed]
    prev = seed
    for i in range(period, len(true_ranges)):
        current = ((prev * (period - 1)) + true_ranges[i]) / period
        out.append(current)
        prev = current
    return out


def adx(candles: List[Dict[str, float]], period: int = 14) -> List[float]:
    if period <= 0:
        raise ValueError("period must be > 0")
    if len(candles) < (period * 2) + 1:
        return []

    tr_values: List[float] = []
    plus_dm_values: List[float] = []
    minus_dm_values: List[float] = []
    for i in range(1, len(candles)):
        high = float(candles[i].get("high", 0.0))
        low = float(candles[i].get("low", 0.0))
        prev_high = float(candles[i - 1].get("high", 0.0))
        prev_low = float(candles[i - 1].get("low", 0.0))
        prev_close = float(candles[i - 1].get("close", 0.0))

        up_move = high - prev_high
        down_move = prev_low - low
        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_values.append(tr)
        plus_dm_values.append(plus_dm)
        minus_dm_values.append(minus_dm)

    tr_smooth = sum(tr_values[:period])
    plus_dm_smooth = sum(plus_dm_values[:period])
    minus_dm_smooth = sum(minus_dm_values[:period])

    dx_values: List[float] = []
    for i in range(period, len(tr_values)):
        if i > period:
            tr_smooth = tr_smooth - (tr_smooth / period) + tr_values[i]
            plus_dm_smooth = plus_dm_smooth - (plus_dm_smooth / period) + plus_dm_values[i]
            minus_dm_smooth = minus_dm_smooth - (minus_dm_smooth / period) + minus_dm_values[i]

        if tr_smooth <= 0:
            dx_values.append(0.0)
            continue

        plus_di = 100.0 * (plus_dm_smooth / tr_smooth)
        minus_di = 100.0 * (minus_dm_smooth / tr_smooth)
        di_sum = plus_di + minus_di
        if di_sum <= 0:
            dx_values.append(0.0)
            continue
        dx = 100.0 * abs(plus_di - minus_di) / di_sum
        dx_values.append(dx)

    if len(dx_values) < period:
        return []

    adx_seed = sum(dx_values[:period]) / period
    out: List[float] = [adx_seed]
    prev_adx = adx_seed
    for i in range(period, len(dx_values)):
        current = ((prev_adx * (period - 1)) + dx_values[i]) / period
        out.append(current)
        prev_adx = current
    return out


def linear_regression_slope(values: List[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    num = 0.0
    den = 0.0
    for idx, val in enumerate(values):
        dx = idx - x_mean
        num += dx * (val - y_mean)
        den += dx * dx
    if den == 0:
        return 0.0
    return num / den


def _align_series(values: List[float], pad: int) -> List[Optional[float]]:
    if pad <= 0:
        return [float(v) for v in values]
    return [None] * pad + [float(v) for v in values]


def _rolling_max(values: List[float], period: int) -> List[float]:
    if period <= 0:
        raise ValueError("period must be > 0")
    if len(values) < period:
        return []
    out: List[float] = []
    for idx in range(period - 1, len(values)):
        out.append(max(values[idx - period + 1 : idx + 1]))
    return out


def _rolling_min(values: List[float], period: int) -> List[float]:
    if period <= 0:
        raise ValueError("period must be > 0")
    if len(values) < period:
        return []
    out: List[float] = []
    for idx in range(period - 1, len(values)):
        out.append(min(values[idx - period + 1 : idx + 1]))
    return out


def _safe_indicator_value(series: List[Optional[float]], idx: int) -> Optional[float]:
    if idx < 0 or idx >= len(series):
        return None
    value = series[idx]
    if value is None:
        return None
    return float(value)


def evaluate_long_ma50_cross_3_candles(candles: List[Dict[str, float]]) -> Dict[str, object]:
    if len(candles) < 54:
        return {
            "signal": False,
            "reason": "not_enough_candles",
            "needed": 54,
            "current": len(candles),
        }

    closes = [float(c["close"]) for c in candles]
    ma50 = sma(closes, 50)
    ma_aligned = [None] * 49 + ma50

    i1 = len(candles) - 3
    i2 = len(candles) - 2
    i3 = len(candles) - 1
    pre = len(candles) - 4

    c1, c2, c3 = closes[i1], closes[i2], closes[i3]
    m1, m2, m3 = ma_aligned[i1], ma_aligned[i2], ma_aligned[i3]
    mpre = ma_aligned[pre]
    cpre = closes[pre]

    if m1 is None or m2 is None or m3 is None or mpre is None:
        return {
            "signal": False,
            "reason": "ma_unavailable",
        }

    above_three = c1 > m1 and c2 > m2 and c3 > m3
    crossed_before_three = cpre <= mpre

    signal = above_three and crossed_before_three
    return {
        "signal": signal,
        "reason": "long_signal" if signal else "conditions_not_met",
        "close": c3,
        "ma50": m3,
        "pre_close": cpre,
        "pre_ma50": mpre,
        "last_candle_open_time": candles[i3].get("open_time", 0),
        "diagnostics": {
            "c1_gt_ma": c1 > m1,
            "c2_gt_ma": c2 > m2,
            "c3_gt_ma": c3 > m3,
            "pre_le_ma": cpre <= mpre,
        },
    }


def evaluate_long_ema_rsi_15m(
    candles: List[Dict[str, float]],
    ema_fast_len: int = 20,
    ema_slow_len: int = 50,
    rsi_len: int = 14,
    rsi_long_min: float = 50,
    rsi_long_max: float = 70,
) -> Dict[str, object]:
    min_needed = max(ema_slow_len, rsi_len) + 5
    if len(candles) < min_needed:
        return {
            "signal": False,
            "reason": "not_enough_candles",
            "needed": min_needed,
            "current": len(candles),
        }

    closes = [float(c["close"]) for c in candles]
    volumes = [float(c.get("volume", 0.0)) for c in candles]

    ema_fast_values = ema(closes, ema_fast_len)
    ema_slow_values = ema(closes, ema_slow_len)
    rsi_values = rsi(closes, rsi_len)

    ema_fast_aligned = [None] * (ema_fast_len - 1) + ema_fast_values
    ema_slow_aligned = [None] * (ema_slow_len - 1) + ema_slow_values
    rsi_aligned = [None] * rsi_len + rsi_values

    t = len(candles) - 1
    t_prev = t - 1
    ef_prev = ema_fast_aligned[t_prev]
    ef_now = ema_fast_aligned[t]
    es_prev = ema_slow_aligned[t_prev]
    es_now = ema_slow_aligned[t]
    rsi_now = rsi_aligned[t]
    if ef_prev is None or ef_now is None or es_prev is None or es_now is None or rsi_now is None:
        return {"signal": False, "reason": "indicator_unavailable"}

    cross_up = ef_prev <= es_prev and ef_now > es_now
    rsi_band_ok = rsi_long_min <= rsi_now <= rsi_long_max
    volume_ok = volumes[t] > 0
    close_above_slow = closes[t] > es_now

    signal = cross_up and rsi_band_ok and volume_ok and close_above_slow
    passed_filters: List[str] = []
    if cross_up:
        passed_filters.append("CROSS_UP")
    if rsi_band_ok:
        passed_filters.append("RSI_BAND")
    if volume_ok:
        passed_filters.append("VOLUME_GT_0")
    if close_above_slow:
        passed_filters.append("CLOSE_GT_EMA_SLOW")

    return {
        "signal": signal,
        "reason": "long_signal" if signal else "conditions_not_met",
        "close": closes[t],
        "ema_fast": ef_now,
        "ema_slow": es_now,
        "rsi": rsi_now,
        "last_candle_open_time": candles[t].get("open_time", 0),
        "diagnostics": {
            "cross_up": cross_up,
            "rsi_band_ok": rsi_band_ok,
            "volume_ok": volume_ok,
            "close_gt_ema_slow": close_above_slow,
            "passed_filters": passed_filters,
        },
    }


def evaluate_exit_ema_cross_down_15m(
    candles: List[Dict[str, float]],
    ema_fast_len: int = 20,
    ema_slow_len: int = 50,
) -> Dict[str, object]:
    min_needed = ema_slow_len + 3
    if len(candles) < min_needed:
        return {
            "signal": False,
            "reason": "not_enough_candles",
            "needed": min_needed,
            "current": len(candles),
        }

    closes = [float(c["close"]) for c in candles]
    ema_fast_values = ema(closes, ema_fast_len)
    ema_slow_values = ema(closes, ema_slow_len)

    ema_fast_aligned = [None] * (ema_fast_len - 1) + ema_fast_values
    ema_slow_aligned = [None] * (ema_slow_len - 1) + ema_slow_values

    t = len(candles) - 1
    t_prev = t - 1
    ef_prev = ema_fast_aligned[t_prev]
    ef_now = ema_fast_aligned[t]
    es_prev = ema_slow_aligned[t_prev]
    es_now = ema_slow_aligned[t]
    if ef_prev is None or ef_now is None or es_prev is None or es_now is None:
        return {"signal": False, "reason": "indicator_unavailable"}

    cross_down = ef_prev >= es_prev and ef_now < es_now
    return {
        "signal": cross_down,
        "reason": "ema_cross_down" if cross_down else "conditions_not_met",
        "ema_fast": ef_now,
        "ema_slow": es_now,
        "last_candle_open_time": candles[t].get("open_time", 0),
        "diagnostics": {
            "cross_down": cross_down,
            "ef_prev": ef_prev,
            "es_prev": es_prev,
        },
    }


def compute_regime_switch_snapshot(
    candles: List[Dict[str, float]],
    *,
    ema_trend_len: int = 200,
    adx_len: int = 14,
    atr_len: int = 14,
    atr_slope_len: int = 10,
    bb_len: int = 20,
    bb_std_mult: float = 2.0,
    donchian_entry_len: int = 20,
    donchian_exit_len: int = 10,
    adx_trend_threshold: float = 25.0,
    adx_range_threshold: float = 20.0,
) -> Dict[str, Any]:
    min_needed = max(ema_trend_len + 2, (adx_len * 2) + 5, atr_len + atr_slope_len + 5, bb_len + 5, donchian_entry_len + 2)
    if len(candles) < min_needed:
        return {
            "ok": False,
            "reason": "not_enough_candles",
            "needed": min_needed,
            "current": len(candles),
        }

    closes = [float(c.get("close", 0.0)) for c in candles]
    highs = [float(c.get("high", 0.0)) for c in candles]
    lows = [float(c.get("low", 0.0)) for c in candles]

    ema200_raw = ema(closes, ema_trend_len)
    atr_raw = atr(candles, atr_len)
    adx_raw = adx(candles, adx_len)
    rsi_raw = rsi(closes, 14)
    bb_mid_raw = sma(closes, bb_len)
    bb_std_raw = stddev(closes, bb_len)

    ema200 = _align_series(ema200_raw, ema_trend_len - 1)
    atr_series = _align_series(atr_raw, atr_len)
    adx_series = _align_series(adx_raw, adx_len * 2)
    rsi_series = _align_series(rsi_raw, 14)
    bb_mid = _align_series(bb_mid_raw, bb_len - 1)
    bb_std = _align_series(bb_std_raw, bb_len - 1)

    latest_idx = len(candles) - 1
    latest_close = closes[latest_idx]
    latest_high = highs[latest_idx]
    latest_low = lows[latest_idx]

    ema200_now = _safe_indicator_value(ema200, latest_idx)
    atr_now = _safe_indicator_value(atr_series, latest_idx)
    atr_prev = _safe_indicator_value(atr_series, latest_idx - 1)
    adx_now = _safe_indicator_value(adx_series, latest_idx)
    rsi_now = _safe_indicator_value(rsi_series, latest_idx)
    bb_mid_now = _safe_indicator_value(bb_mid, latest_idx)
    bb_std_now = _safe_indicator_value(bb_std, latest_idx)

    if ema200_now is None or atr_now is None or adx_now is None or rsi_now is None or bb_mid_now is None or bb_std_now is None:
        return {"ok": False, "reason": "indicator_unavailable"}
    if atr_prev is None:
        atr_prev = atr_now

    bb_upper_now = bb_mid_now + (bb_std_mult * bb_std_now)
    bb_lower_now = bb_mid_now - (bb_std_mult * bb_std_now)

    if latest_idx < donchian_entry_len or latest_idx < donchian_exit_len:
        return {"ok": False, "reason": "donchian_window_unavailable"}

    entry_high_prev = max(highs[latest_idx - donchian_entry_len : latest_idx])
    entry_low_prev = min(lows[latest_idx - donchian_entry_len : latest_idx])
    exit_high_prev = max(highs[latest_idx - donchian_exit_len : latest_idx])
    exit_low_prev = min(lows[latest_idx - donchian_exit_len : latest_idx])

    atr_window: List[float] = []
    for i in range(max(0, latest_idx - atr_slope_len + 1), latest_idx + 1):
        value = _safe_indicator_value(atr_series, i)
        if value is not None:
            atr_window.append(value)
    atr_slope = linear_regression_slope(atr_window)

    trend_filter = latest_close > ema200_now
    trending = adx_now >= adx_trend_threshold and atr_slope > 0
    ranging = adx_now <= adx_range_threshold and atr_slope <= 0

    if trend_filter and trending:
        regime = "TREND"
    elif ranging:
        regime = "RANGE"
    else:
        regime = "NO_TRADE"

    return {
        "ok": True,
        "regime": regime,
        "close": latest_close,
        "high": latest_high,
        "low": latest_low,
        "ema200": ema200_now,
        "atr14": atr_now,
        "atr14_prev": atr_prev,
        "adx14": adx_now,
        "rsi14": rsi_now,
        "bb_mid": bb_mid_now,
        "bb_upper": bb_upper_now,
        "bb_lower": bb_lower_now,
        "donchian_high_20": entry_high_prev,
        "donchian_low_20": entry_low_prev,
        "donchian_high_10": exit_high_prev,
        "donchian_low_10": exit_low_prev,
        "atr_slope": atr_slope,
        "last_candle_open_time": candles[latest_idx].get("open_time", 0),
        "diagnostics": {
            "trend_filter": trend_filter,
            "trending": trending,
            "ranging": ranging,
        },
    }


def evaluate_regime_switch_entry_long_4h(
    candles: List[Dict[str, float]],
    *,
    adx_trend_threshold: float = 25.0,
    adx_range_threshold: float = 20.0,
    rsi_long_entry: float = 30.0,
) -> Dict[str, Any]:
    snapshot = compute_regime_switch_snapshot(
        candles,
        adx_trend_threshold=adx_trend_threshold,
        adx_range_threshold=adx_range_threshold,
    )
    if not snapshot.get("ok"):
        return {"signal": False, "reason": snapshot.get("reason", "indicator_unavailable"), **snapshot}

    regime = str(snapshot.get("regime", "NO_TRADE"))
    close = float(snapshot.get("close", 0.0) or 0.0)
    atr_now = float(snapshot.get("atr14", 0.0) or 0.0)
    bb_mid = float(snapshot.get("bb_mid", 0.0) or 0.0)
    bb_lower = float(snapshot.get("bb_lower", 0.0) or 0.0)
    donchian_high = float(snapshot.get("donchian_high_20", 0.0) or 0.0)
    rsi14 = float(snapshot.get("rsi14", 0.0) or 0.0)

    if regime == "TREND":
        long_signal = close > donchian_high and atr_now > 0
        return {
            "signal": long_signal,
            "side": "LONG" if long_signal else "NONE",
            "entry_type": "TREND_BREAKOUT",
            "regime": regime,
            "reason": "trend_breakout" if long_signal else "conditions_not_met",
            **snapshot,
        }

    if regime == "RANGE":
        long_signal = close <= bb_lower and rsi14 < rsi_long_entry and atr_now > 0 and bb_mid > 0
        return {
            "signal": long_signal,
            "side": "LONG" if long_signal else "NONE",
            "entry_type": "RANGE_MEAN_REVERSION",
            "regime": regime,
            "reason": "range_mean_reversion" if long_signal else "conditions_not_met",
            **snapshot,
        }

    return {
        "signal": False,
        "side": "NONE",
        "entry_type": "NONE",
        "regime": regime,
        "reason": "no_trade_regime",
        **snapshot,
    }


def evaluate_regime_switch_manage_long_4h(
    candles: List[Dict[str, float]],
    position_state: Dict[str, Any],
    *,
    trend_trail_atr_mult: float = 2.0,
    trend_move_stop_to_be_atr: float = 1.0,
    range_move_sl_to_be_r: float = 1.0,
) -> Dict[str, Any]:
    entry_price = float(position_state.get("entry_price", 0.0) or 0.0)
    stop_price = float(position_state.get("stop_price", 0.0) or 0.0)
    initial_stop = float(position_state.get("initial_stop_price", stop_price) or stop_price)
    trailing_stop = float(position_state.get("trailing_stop_price", 0.0) or 0.0)
    take_profit = float(position_state.get("take_profit_price", 0.0) or 0.0)
    moved_to_be = bool(position_state.get("moved_to_be", False))
    regime_at_entry = str(position_state.get("regime_at_entry", "TREND") or "TREND").upper()

    snapshot = compute_regime_switch_snapshot(candles)
    if not snapshot.get("ok"):
        return {"action": "HOLD", "reason": snapshot.get("reason", "indicator_unavailable"), "state_patch": {}, **snapshot}

    close = float(snapshot.get("close", 0.0) or 0.0)
    low = float(snapshot.get("low", 0.0) or 0.0)
    high = float(snapshot.get("high", 0.0) or 0.0)
    atr_now = float(snapshot.get("atr14", 0.0) or 0.0)

    patch: Dict[str, Any] = {}
    if regime_at_entry == "TREND":
        donchian_low_10 = float(snapshot.get("donchian_low_10", 0.0) or 0.0)
        if close < donchian_low_10 and donchian_low_10 > 0:
            return {
                "action": "EXIT_MARKET",
                "reason": "trend_donchian_exit",
                "exit_price": close,
                "state_patch": patch,
                **snapshot,
            }

        new_trail = close - (trend_trail_atr_mult * atr_now)
        trailing_stop = max(trailing_stop, new_trail)
        patch["trailing_stop_price"] = trailing_stop

        if (not moved_to_be) and close >= (entry_price + (trend_move_stop_to_be_atr * atr_now)):
            moved_to_be = True
            stop_price = max(stop_price, entry_price)
            patch["moved_to_be"] = True
            patch["stop_price"] = stop_price

        effective_stop = max(stop_price, trailing_stop)
        if low <= effective_stop and effective_stop > 0:
            return {
                "action": "EXIT_STOP",
                "reason": "trend_effective_stop",
                "exit_price": effective_stop,
                "state_patch": patch,
                **snapshot,
            }

        return {
            "action": "HOLD",
            "reason": "trend_hold",
            "effective_stop": effective_stop,
            "state_patch": patch,
            **snapshot,
        }

    # RANGE long management
    if take_profit > 0 and high >= take_profit:
        return {
            "action": "EXIT_TP",
            "reason": "range_take_profit",
            "exit_price": take_profit,
            "state_patch": patch,
            **snapshot,
        }

    initial_r = max(entry_price - initial_stop, 0.0)
    if (not moved_to_be) and initial_r > 0 and close >= (entry_price + (initial_r * range_move_sl_to_be_r)):
        moved_to_be = True
        stop_price = max(stop_price, entry_price)
        patch["moved_to_be"] = True
        patch["stop_price"] = stop_price

    if low <= stop_price and stop_price > 0:
        return {
            "action": "EXIT_STOP",
            "reason": "range_stop",
            "exit_price": stop_price,
            "state_patch": patch,
            **snapshot,
        }

    return {
        "action": "HOLD",
        "reason": "range_hold",
        "state_patch": patch,
        **snapshot,
    }


def build_ma50_series(candles: List[Dict[str, float]]) -> List[Dict[str, float]]:
    if len(candles) < 50:
        return []
    closes = [float(c["close"]) for c in candles]
    ma_values = sma(closes, 50)
    out: List[Dict[str, float]] = []
    for idx, value in enumerate(ma_values):
        candle_idx = idx + 49
        open_time_ms = float(candles[candle_idx].get("open_time", 0) or 0)
        out.append(
            {
                "time": int(open_time_ms / 1000),
                "value": float(value),
            }
        )
    return out


def build_ema_series(candles: List[Dict[str, float]], period: int) -> List[Dict[str, float]]:
    if period <= 0 or len(candles) < period:
        return []
    closes = [float(c["close"]) for c in candles]
    ema_values = ema(closes, period)
    out: List[Dict[str, float]] = []
    for idx, value in enumerate(ema_values):
        candle_idx = idx + (period - 1)
        open_time_ms = float(candles[candle_idx].get("open_time", 0) or 0)
        out.append(
            {
                "time": int(open_time_ms / 1000),
                "value": float(value),
            }
        )
    return out


def build_bollinger_series(candles: List[Dict[str, float]], period: int = 20, std_mult: float = 2.0) -> Dict[str, List[Dict[str, float]]]:
    if period <= 0 or len(candles) < period:
        return {"upper": [], "mid": [], "lower": []}
    closes = [float(c["close"]) for c in candles]
    mid_raw = sma(closes, period)
    std_raw = stddev(closes, period)
    upper: List[Dict[str, float]] = []
    mid: List[Dict[str, float]] = []
    lower: List[Dict[str, float]] = []
    for idx, m in enumerate(mid_raw):
        candle_idx = idx + (period - 1)
        t = int(float(candles[candle_idx].get("open_time", 0) or 0) / 1000)
        s = float(std_raw[idx])
        mid.append({"time": t, "value": float(m)})
        upper.append({"time": t, "value": float(m + (std_mult * s))})
        lower.append({"time": t, "value": float(m - (std_mult * s))})
    return {"upper": upper, "mid": mid, "lower": lower}


def build_donchian_series(candles: List[Dict[str, float]], period: int) -> Dict[str, List[Dict[str, float]]]:
    if period <= 0 or len(candles) < period:
        return {"high": [], "low": []}
    highs = [float(c.get("high", 0.0)) for c in candles]
    lows = [float(c.get("low", 0.0)) for c in candles]
    high_raw = _rolling_max(highs, period)
    low_raw = _rolling_min(lows, period)
    out_high: List[Dict[str, float]] = []
    out_low: List[Dict[str, float]] = []
    for idx in range(len(high_raw)):
        candle_idx = idx + (period - 1)
        t = int(float(candles[candle_idx].get("open_time", 0) or 0) / 1000)
        out_high.append({"time": t, "value": float(high_raw[idx])})
        out_low.append({"time": t, "value": float(low_raw[idx])})
    return {"high": out_high, "low": out_low}


def detect_regime_switch_long_markers(candles: List[Dict[str, float]]) -> List[Dict[str, object]]:
    markers: List[Dict[str, object]] = []
    if len(candles) < 240:
        return markers
    for i in range(220, len(candles)):
        window = candles[: i + 1]
        signal = evaluate_regime_switch_entry_long_4h(window)
        if not signal.get("signal"):
            continue
        text = "REGIME TREND LONG" if signal.get("regime") == "TREND" else "REGIME RANGE LONG"
        open_time_ms = float(candles[i].get("open_time", 0) or 0)
        markers.append(
            {
                "time": int(open_time_ms / 1000),
                "price": float(candles[i].get("close", 0.0) or 0.0),
                "text": text,
            }
        )
    return markers


def detect_regime_markers(candles: List[Dict[str, float]]) -> List[Dict[str, object]]:
    markers: List[Dict[str, object]] = []
    if len(candles) < 240:
        return markers
    prev_regime = ""
    for i in range(220, len(candles)):
        snapshot = compute_regime_switch_snapshot(candles[: i + 1])
        if not snapshot.get("ok"):
            continue
        regime = str(snapshot.get("regime", "NO_TRADE"))
        if regime == prev_regime:
            continue
        prev_regime = regime
        open_time_ms = float(candles[i].get("open_time", 0) or 0)
        color = "#6fd3a8" if regime == "TREND" else ("#ffd88f" if regime == "RANGE" else "#b0b9c5")
        markers.append(
            {
                "time": int(open_time_ms / 1000),
                "price": float(candles[i].get("close", 0.0) or 0.0),
                "text": f"REGIME {regime}",
                "color": color,
            }
        )
    return markers


def detect_ema_rsi_long_markers(
    candles: List[Dict[str, float]],
    ema_fast_len: int = 20,
    ema_slow_len: int = 50,
    rsi_len: int = 14,
    rsi_long_min: float = 50,
    rsi_long_max: float = 70,
) -> List[Dict[str, object]]:
    min_needed = max(ema_slow_len, rsi_len) + 5
    if len(candles) < min_needed:
        return []

    closes = [float(c["close"]) for c in candles]
    volumes = [float(c.get("volume", 0.0)) for c in candles]

    ema_fast_values = ema(closes, ema_fast_len)
    ema_slow_values = ema(closes, ema_slow_len)
    rsi_values = rsi(closes, rsi_len)

    ema_fast_aligned = [None] * (ema_fast_len - 1) + ema_fast_values
    ema_slow_aligned = [None] * (ema_slow_len - 1) + ema_slow_values
    rsi_aligned = [None] * rsi_len + rsi_values

    markers: List[Dict[str, object]] = []
    for t in range(1, len(candles)):
        ef_prev = ema_fast_aligned[t - 1]
        ef_now = ema_fast_aligned[t]
        es_prev = ema_slow_aligned[t - 1]
        es_now = ema_slow_aligned[t]
        rsi_now = rsi_aligned[t]
        if ef_prev is None or ef_now is None or es_prev is None or es_now is None or rsi_now is None:
            continue

        cross_up = ef_prev <= es_prev and ef_now > es_now
        rsi_band_ok = rsi_long_min <= rsi_now <= rsi_long_max
        volume_ok = volumes[t] > 0
        close_above_slow = closes[t] > es_now
        if not (cross_up and rsi_band_ok and volume_ok and close_above_slow):
            continue

        open_time_ms = float(candles[t].get("open_time", 0) or 0)
        markers.append(
            {
                "time": int(open_time_ms / 1000),
                "price": closes[t],
                "text": "EMA/RSI LONG",
            }
        )
    return markers


def detect_ma50_crossup_markers(candles: List[Dict[str, float]]) -> List[Dict[str, object]]:
    if len(candles) < 54:
        return []
    closes = [float(c["close"]) for c in candles]
    ma50 = sma(closes, 50)
    ma_aligned = [None] * 49 + ma50

    markers: List[Dict[str, object]] = []
    for i3 in range(53, len(candles)):
        pre = i3 - 3
        i1 = i3 - 2
        i2 = i3 - 1

        m1 = ma_aligned[i1]
        m2 = ma_aligned[i2]
        m3 = ma_aligned[i3]
        mpre = ma_aligned[pre]
        if m1 is None or m2 is None or m3 is None or mpre is None:
            continue

        c1 = closes[i1]
        c2 = closes[i2]
        c3 = closes[i3]
        cpre = closes[pre]

        above_three = c1 > m1 and c2 > m2 and c3 > m3
        crossed_before_three = cpre <= mpre
        if not (above_three and crossed_before_three):
            continue

        open_time_ms = float(candles[i3].get("open_time", 0) or 0)
        markers.append(
            {
                "time": int(open_time_ms / 1000),
                "price": c3,
                "text": "MA50 x3 LONG",
            }
        )

    return markers
