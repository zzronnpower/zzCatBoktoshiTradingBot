from typing import Dict, List


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
