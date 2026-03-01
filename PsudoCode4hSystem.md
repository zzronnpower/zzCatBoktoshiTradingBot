✅ 0) THIẾT LẬP & THAM SỐ

SYSTEM_NAME = "4H_REGIME_SWITCH_V1"

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
TIMEFRAME = "4h"
DATA_LOOKBACK_BARS = 600         # đủ cho EMA200 + back windows

# --- Exchange / execution assumptions (để backtest & live nhất quán)
FEE_RATE = 0.0004                # ví dụ 0.04%/side (tuỳ sàn)
SLIPPAGE_BPS = 5                 # 5 bps = 0.05% giả lập

# --- Risk / portfolio rules
ACCOUNT_EQUITY = dynamic         # lấy theo thời gian thực
RISK_PER_TRADE = 0.01            # 1% equity/trade
MAX_OPEN_POSITIONS_TOTAL = 3     # tối đa 3 lệnh mở (mỗi pair tối đa 1 lệnh)
MAX_OPEN_POSITIONS_PER_SYMBOL = 1
MAX_DAILY_DRAWDOWN = 0.03        # -3%/day => stop trading trong ngày
COOLDOWN_BARS_AFTER_EXIT = 3     # sau khi đóng lệnh, nghỉ 3 nến 4H

# --- Regime detection
EMA_TREND_LEN = 200              # EMA200 trên 4H
ADX_LEN = 14
ATR_LEN = 14
ADX_TREND_THRESHOLD = 25         # >25: trending
ADX_RANGE_THRESHOLD = 20         # <20: ranging (có thể dùng hysteresis)
ATR_SLOPE_LEN = 10               # để check ATR tăng/giảm

# --- TREND module (Breakout)
DONCHIAN_ENTRY_LEN = 20          # phá đỉnh 20 nến
DONCHIAN_EXIT_LEN = 10           # phá đáy 10 nến để thoát
TREND_STOP_ATR_MULT = 1.5        # stop = 1.5 * ATR
TREND_TRAIL_ATR_MULT = 2.0       # trailing stop theo ATR
MOVE_STOP_TO_BE_ATR = 1.0        # khi lời >= 1.0 ATR => dời SL về BE (không lỗ)

# --- RANGE module (Mean reversion)
RSI_LEN = 14
RSI_LONG_ENTRY = 30              # RSI < 30 -> long
RSI_SHORT_ENTRY = 70             # RSI > 70 -> short (optional)
BB_LEN = 20
BB_STD = 2.0
RANGE_STOP_ATR_MULT = 1.2        # stop = 1.2*ATR
RANGE_TP_TARGET = "BB_MID"       # chốt lời về mid-band
RANGE_MOVE_SL_TO_BE_R = 1.0      # khi lời đạt 1R -> dời SL về BE
ALLOW_SHORTS = false             # nếu bạn chỉ muốn spot long-only => false

✅ 1) CẤU TRÚC DỮ LIỆU & TRẠNG THÁI

For each symbol:
    MarketData:
        candles: list of OHLCV 4H
        indicators:
            ema200, adx14, atr14, rsi14
            bb_upper, bb_mid, bb_lower
            donchian_high_20, donchian_low_20
            donchian_low_10, donchian_high_10
            atr_slope = slope(atr14 over ATR_SLOPE_LEN)

    State:
        position: None or Position object
        cooldown_remaining_bars: integer

Position:
    symbol
    side: "LONG" or "SHORT"
    entry_price
    size_qty
    stop_price
    take_profit_price (optional)
    trailing_stop_price (optional)
    regime_at_entry: "TREND" or "RANGE"
    entry_time
    risk_R = abs(entry_price - stop_price) * size_qty   # tiền rủi ro ban đầu
    moved_to_BE: bool

    ✅ 2) HÀM TÍNH INDICATORS

    function compute_indicators(candles):
    ema200 = EMA(close, 200)
    atr14 = ATR(high, low, close, 14)
    adx14 = ADX(high, low, close, 14)
    rsi14 = RSI(close, 14)

    bb_mid = SMA(close, 20)
    bb_std = STD(close, 20)
    bb_upper = bb_mid + 2.0 * bb_std
    bb_lower = bb_mid - 2.0 * bb_std

    donchian_high_20 = MAX(high, last 20 bars)
    donchian_low_20  = MIN(low,  last 20 bars)
    donchian_high_10 = MAX(high, last 10 bars)
    donchian_low_10  = MIN(low,  last 10 bars)

    atr_slope = linear_regression_slope(atr14 over last 10 bars)

    return all

    ✅ 3) HÀM XÁC ĐỊNH REGIME (TREND vs RANGE)
    function detect_regime(latest_indicators, latest_close):
    trend_filter = (latest_close > ema200)          # long bias (spot-friendly)
    trending = (adx14 >= ADX_TREND_THRESHOLD) and (atr_slope > 0)

    ranging = (adx14 <= ADX_RANGE_THRESHOLD) and (atr_slope <= 0)

    # ưu tiên TREND nếu rõ ràng
    if trend_filter and trending:
        return "TREND"
    else if ranging:
        return "RANGE"
    else:
        return "NO_TRADE"   # vùng xám => đứng ngoài để giảm whipsaw
        Gợi ý: có thể dùng hysteresis (25 để vào trend, 22 để ra) để ổn định hơn, nhưng pseudo-code này đã đủ rõ cho Opencode.

        ✅ 4) QUẢN TRỊ RỦI RO & SIZE
        function can_open_new_position(global_state):
    if global_state.open_positions_total >= MAX_OPEN_POSITIONS_TOTAL:
        return false
    if global_state.daily_drawdown <= -MAX_DAILY_DRAWDOWN:
        return false
    return true

function position_size_qty(entry_price, stop_price, equity):
    risk_dollars = equity * RISK_PER_TRADE
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        return 0
    qty = risk_dollars / stop_distance
    return qty

function apply_slippage(price, side, action):
    # action: "ENTRY" or "EXIT"
    # side: LONG/SHORT
    # đơn giản: trượt giá bất lợi
    slip = price * (SLIPPAGE_BPS / 10000)
    if action == "ENTRY":
        if side == "LONG":  return price + slip
        if side == "SHORT": return price - slip
    if action == "EXIT":
        if side == "LONG":  return price - slip
        if side == "SHORT": return price + slip

        ✅ 5) LUẬT VÀO LỆNH
5.1 TREND MODULE ENTRY (Donchian Breakout + EMA200 + ADX)
function trend_entry_signal(symbol, data):
    # điều kiện:
    # 1) regime == TREND
    # 2) close phá lên donchian_high_20 (breakout xác nhận bằng close)
    if close > donchian_high_20:
        return "LONG"
    else:
        return None

        Stop TREND:

        trend_stop = entry_price - TREND_STOP_ATR_MULT * atr14

        5.2 RANGE MODULE ENTRY (RSI + Bollinger)

        function range_entry_signal(symbol, data):
    # Long mean reversion:
    if (close <= bb_lower) and (rsi14 < RSI_LONG_ENTRY):
        return "LONG"

    # Short mean reversion (optional):
    if ALLOW_SHORTS:
        if (close >= bb_upper) and (rsi14 > RSI_SHORT_ENTRY):
            return "SHORT"

    return None

    Stop RANGE:
    if LONG:  range_stop = entry_price - RANGE_STOP_ATR_MULT * atr14
if SHORT: range_stop = entry_price + RANGE_STOP_ATR_MULT * atr14

Take profit RANGE:
tp = bb_mid

✅ 6) LUẬT QUẢN LÝ LỆNH & THOÁT LỆNH
6.1 TREND POSITION MANAGEMENT

function manage_trend_position(pos, data):
    # 1) Donchian exit: nếu giá phá xuống donchian_low_10 => exit
    if close < donchian_low_10:
        return "EXIT_MARKET"

    # 2) Trailing stop ATR:
    # trailing_stop = max(existing_trail, close - TREND_TRAIL_ATR_MULT*ATR)
    new_trail = close - TREND_TRAIL_ATR_MULT * atr14
    pos.trailing_stop_price = max(pos.trailing_stop_price, new_trail)

    # 3) Move stop to break-even when profit >= 1 ATR:
    if not pos.moved_to_BE:
        if close >= pos.entry_price + MOVE_STOP_TO_BE_ATR * atr14:
            pos.stop_price = pos.entry_price     # BE
            pos.moved_to_BE = true

    # 4) Effective stop is max(stop_price, trailing_stop)
    effective_stop = max(pos.stop_price, pos.trailing_stop_price)

    if low <= effective_stop:
        return ("EXIT_STOP", effective_stop)

    return "HOLD"

    6.2 RANGE POSITION MANAGEMENT

    function manage_range_position(pos, data):
    # TP tại BB mid
    if pos.side == "LONG":
        if high >= pos.take_profit_price:
            return ("EXIT_TP", pos.take_profit_price)

    if pos.side == "SHORT":
        if low <= pos.take_profit_price:
            return ("EXIT_TP", pos.take_profit_price)

    # move SL to BE khi đạt 1R
    # R = abs(entry - initial_stop)
    if not pos.moved_to_BE:
        if pos.side == "LONG":
            if close >= pos.entry_price + (pos.entry_price - pos.initial_stop_price) * RANGE_MOVE_SL_TO_BE_R:
                pos.stop_price = pos.entry_price
                pos.moved_to_BE = true
        if pos.side == "SHORT":
            if close <= pos.entry_price - (pos.initial_stop_price - pos.entry_price) * RANGE_MOVE_SL_TO_BE_R:
                pos.stop_price = pos.entry_price
                pos.moved_to_BE = true

    # stop hit?
    if pos.side == "LONG":
        if low <= pos.stop_price:
            return ("EXIT_STOP", pos.stop_price)

    if pos.side == "SHORT":
        if high >= pos.stop_price:
            return ("EXIT_STOP", pos.stop_price)

    # range invalidation: nếu chuyển regime -> TREND ngược hướng, có thể exit sớm (optional)
    return "HOLD"

    ✅ 7) MAIN LOOP (CHẠY MỖI KHI ĐÓNG NẾN 4H)

    GLOBAL_STATE:
    equity
    open_positions_total
    daily_pnl
    daily_drawdown
    current_day

function on_new_4h_candle_close(timestamp):
    if date(timestamp) != GLOBAL_STATE.current_day:
        reset daily_pnl, daily_drawdown, current_day

    update equity from exchange / backtest engine

    For each symbol in SYMBOLS:
        # 1) load latest candles
        candles = fetch_ohlcv(symbol, timeframe=4h, limit=DATA_LOOKBACK_BARS)

        # 2) compute indicators
        ind = compute_indicators(candles)
        close = candles[-1].close
        high  = candles[-1].high
        low   = candles[-1].low

        # 3) cooldown handling
        if State[symbol].cooldown_remaining_bars > 0:
            State[symbol].cooldown_remaining_bars -= 1
            continue

        # 4) manage open position if exists
        if State[symbol].position is not None:
            pos = State[symbol].position

            if pos.regime_at_entry == "TREND":
                action = manage_trend_position(pos, ind)
            else if pos.regime_at_entry == "RANGE":
                action = manage_range_position(pos, ind)

            if action startswith "EXIT":
                exit_price = determine_exit_price_from_action(action)
                exit_price = apply_slippage(exit_price, pos.side, "EXIT")
                execute_close_position(symbol, pos.size_qty, exit_price)
                pnl = calculate_pnl(pos, exit_price, FEE_RATE)
                update GLOBAL_STATE daily_pnl/drawdown/equity/open_positions_total
                State[symbol].position = None
                State[symbol].cooldown_remaining_bars = COOLDOWN_BARS_AFTER_EXIT
            continue

        # 5) if no open position => evaluate entry
        if not can_open_new_position(GLOBAL_STATE):
            continue

        regime = detect_regime(ind, close)
        if regime == "NO_TRADE":
            continue

        # LONG-only bias for spot:
        # enforce close > EMA200 for both regimes (optional)
        # if close <= ema200: skip

        if regime == "TREND":
            signal = trend_entry_signal(symbol, ind)
            if signal == "LONG":
                entry_price = close
                entry_price = apply_slippage(entry_price, "LONG", "ENTRY")

                stop_price = entry_price - TREND_STOP_ATR_MULT * ind.atr14
                qty = position_size_qty(entry_price, stop_price, GLOBAL_STATE.equity)

                if qty > 0:
                    execute_open_position(symbol, "LONG", qty, entry_price)
                    create Position object with:
                        side="LONG"
                        entry=entry_price
                        stop=stop_price
                        trailing_stop_price = entry_price - TREND_TRAIL_ATR_MULT * ind.atr14
                        regime_at_entry="TREND"
                        moved_to_BE=false
                    State[symbol].position = pos
                    GLOBAL_STATE.open_positions_total += 1

        if regime == "RANGE":
            signal = range_entry_signal(symbol, ind)

            if signal == "LONG":
                entry_price = close
                entry_price = apply_slippage(entry_price, "LONG", "ENTRY")

                stop_price = entry_price - RANGE_STOP_ATR_MULT * ind.atr14
                tp_price = ind.bb_mid
                qty = position_size_qty(entry_price, stop_price, GLOBAL_STATE.equity)

                if qty > 0:
                    execute_open_position(symbol, "LONG", qty, entry_price)
                    create Position with:
                        side="LONG"
                        entry=entry_price
                        stop=stop_price
                        initial_stop_price=stop_price
                        take_profit_price=tp_price
                        regime_at_entry="RANGE"
                        moved_to_BE=false
                    State[symbol].position = pos
                    GLOBAL_STATE.open_positions_total += 1

            if signal == "SHORT" and ALLOW_SHORTS:
                ... (mirror logic)

                ✅ 8) QUY TẮC BỔ SUNG (RẤT NÊN CÓ)

                # Correlation / concentration control (BTC-ETH-SOL thường cùng hướng)
- Nếu đã có LONG BTC, giảm size ETH/SOL xuống 50% (optional)
- Hoặc chỉ cho phép tối đa 2 lệnh cùng hướng cùng lúc

# News / extreme volatility protection
- Nếu ATR tăng > X% trong 1 nến (volatility shock) => không vào lệnh mới 1-2 nến

# Data quality
- Nếu thiếu nến hoặc indicator NaN => skip
✅ Output cho Opencode (bạn copy nguyên khối)

Bạn có thể gửi Opencode yêu cầu:

Viết Python bot theo pseudo-code này

Dùng CCXT

Chạy ở chế độ backtest + live (paper)

Lưu trạng thái position vào file JSON/SQLite

Mỗi 4H candle close mới quyết định (không vào giữa nến)