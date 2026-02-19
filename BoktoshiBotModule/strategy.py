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
