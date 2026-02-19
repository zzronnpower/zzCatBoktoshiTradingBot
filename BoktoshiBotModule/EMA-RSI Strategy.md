Dưới đây là Implementation Spec (dev-grade) cho bot EMA Cross + RSI filter. Bạn copy nguyên văn gửi Opencode là họ có thể code đúng ngay (scan 15m, chỉ BTC & ETH). Phần risk/position sizing bạn sẽ đưa sau, nên ở đây mình để placeholder.

Implementation Spec — EMA Cross + RSI Filter Bot (15m) for BTC & ETH
0) Scope

Bot scan tín hiệu và (tuỳ cấu hình) gọi hàm execute order.

Symbols: BTCUSDT, ETHUSDT (Binance naming; nếu sàn khác thì mapping tương đương).

Timeframe: 15m.

BẮT BUỘC: chỉ dùng closed candle (nến đã đóng), không dùng nến đang chạy để tránh repaint.

1) Data & Scheduling
1.1 Candle source

Fetch OHLCV 15m cho mỗi symbol.

Lấy tối thiểu: limit >= max(ema_slow_len, rsi_len) + 50 (khuyến nghị 300 candles).

1.2 Closed candle rule (anti-repaint)

Mỗi vòng scan, xác định “nến cuối đã đóng”:

Nếu API trả về candle đang chạy, bỏ candle cuối, dùng candle [-2] là candle close mới nhất.

Hoặc dùng timestamp: chỉ xử lý candle có close_time <= now và is_closed == true (nếu API có cờ).

1.3 Trigger scan

Run loop check mỗi 5–15 giây hoặc 1 phút.

Nhưng chỉ xử lý khi phát hiện có candle 15m mới đóng cho symbol đó (dựa trên last_processed_close_time[symbol]).

2) Config Parameters (để chỉnh được)

Defaults (có thể đổi):

ema_fast_len = 20

ema_slow_len = 50

rsi_len = 14

RSI filters:

Long entry RSI band: rsi_long_min = 50, rsi_long_max = 70

Short entry RSI band (nếu futures): rsi_short_min = 30, rsi_short_max = 50 (hoặc 35–50 nếu muốn an toàn)

Exit mode:

exit_mode = "CROSS" (default)

Options: "CROSS" | "RSI" | "RISK"

"RISK" sẽ dùng SL/TP/trailing theo config risk user đưa sau.

Other:

enable_short = false (default; bật nếu futures)

allow_flip = false (default)

cooldown_bars_after_exit = 1 (default; tránh whipsaw)

one_position_per_symbol = true (default)

3) Indicator Calculation

Trên dataframe candle (đã đảm bảo closed candle):

EMA_fast = EMA(close, ema_fast_len)

EMA_slow = EMA(close, ema_slow_len)

RSI = RSI(close, rsi_len)

Lưu ý:

Tính trên series đầy đủ (không chỉ 2 nến), nhưng tín hiệu dùng ở t và t-1.

4) Signal Definitions (cross phải đúng kiểu t-1 vs t)

Gọi t là index của candle close mới nhất (closed), t-1 là candle trước đó.

4.1 Cross Up

cross_up = (EMA_fast[t-1] <= EMA_slow[t-1]) AND (EMA_fast[t] > EMA_slow[t])

4.2 Cross Down

cross_down = (EMA_fast[t-1] >= EMA_slow[t-1]) AND (EMA_fast[t] < EMA_slow[t])

5) Entry Rules (generate ENTRY signal)
5.1 Long Entry (Spot & Futures)

Generate ENTER_LONG khi ALL true:

cross_up == true

rsi_long_min <= RSI[t] <= rsi_long_max

volume[t] > 0
(Option filter, bật/tắt bằng config nếu muốn):

close[t] > EMA_slow[t] (trend confirmation)

5.2 Short Entry (Futures only)

Generate ENTER_SHORT khi ALL true:

enable_short == true

cross_down == true

rsi_short_min <= RSI[t] <= rsi_short_max

volume[t] > 0
(Option):

close[t] < EMA_slow[t]

6) Exit Rules (generate EXIT signal)
6.1 Exit mode = "CROSS" (default)

Nếu đang LONG: generate EXIT_LONG khi cross_down == true

Nếu đang SHORT: generate EXIT_SHORT khi cross_up == true

6.2 Exit mode = "RSI"

LONG: EXIT_LONG khi RSI[t] >= rsi_exit_long (default 70)

SHORT: EXIT_SHORT khi RSI[t] <= rsi_exit_short (default 30)

6.3 Exit mode = "RISK"

Exit theo SL/TP/trailing (user sẽ cung cấp % / rules sau)

Tối thiểu cần hooks: should_stoploss(), should_takeprofit(), should_trailing_exit()

7) State Management (anti-spam, one position per symbol)

Maintain per symbol:

position_state[symbol] = NONE | LONG | SHORT

last_signal_close_time[symbol] (để tránh phát lại tín hiệu cùng nến)

last_exit_bar_index_or_time[symbol] (cooldown)

Rules:

Nếu position_state == NONE:

Có thể ENTER nếu không trong cooldown.

Nếu position_state == LONG:

Không ENTER_LONG thêm (one position).

Nếu có EXIT_LONG thì exit.

Nếu có ENTER_SHORT:

Nếu allow_flip == true: exit long rồi enter short (cùng candle close) theo thứ tự.

Nếu allow_flip == false: bỏ qua enter short, chỉ exit theo rule.

Tương tự cho SHORT.

Cooldown:

Sau khi exit, không cho entry trong cooldown_bars_after_exit nến 15m tiếp theo.

8) Execution / Output Interface

Bot phải xuất ra mỗi lần xử lý candle mới (per symbol) một object signal:

{
  "timestamp_close": "<candle_close_time>",
  "symbol": "BTCUSDT",
  "timeframe": "15m",
  "signal": "ENTER_LONG | ENTER_SHORT | EXIT_LONG | EXIT_SHORT | HOLD",
  "reason": {
    "cross": "UP|DOWN|NONE",
    "rsi": 56.2,
    "ema_fast": 12345.6,
    "ema_slow": 12340.1,
    "passed_filters": ["RSI_BAND", "CROSS_UP", "CLOSE_GT_EMA_SLOW"]
  }
}


Execution hooks (stub):

on_signal(signal_obj):

If scan-only: log/alert.

If auto-trade: call execute_order(...) (risk config injected later).

9) Logging Requirements

Log mỗi candle mới: symbol, close_time, EMA_fast, EMA_slow, RSI.

Khi có signal: log rõ điều kiện nào đúng/sai (để debug).

Không spam: chỉ 1 lần/1 candle close.

10) Minimum Acceptance Tests (để Opencode tự check)

Với dữ liệu lịch sử, cross_up chỉ xảy ra đúng tại điểm EMA fast chuyển từ <= sang > EMA slow (không phải chỉ vì EMA_fast > EMA_slow).

Khi chạy live, bot chỉ phát tín hiệu sau khi candle 15m đóng.

Không phát lại cùng tín hiệu nhiều lần trên cùng 1 candle close.

BTC và ETH chạy độc lập state.

Nếu bạn muốn “đóng gói” thêm cho Opencode dễ làm hơn, bạn có thể gửi kèm 2 dòng yêu cầu kỹ thuật:

“Implement in Python, pandas, ta-lib/ta; exchange via ccxt; structure: DataFetcher + IndicatorEngine + SignalEngine + StateManager + Executor stub.”

“Mặc định chạy scan-only, in tín hiệu ra console + optional webhook.”

Bạn cứ đưa spec này cho Opencode, phần risk config (2%/trade, SL 5%, leverage, max concurrent trades…) bạn gửi sau là họ nối vào execute_order() được ngay.