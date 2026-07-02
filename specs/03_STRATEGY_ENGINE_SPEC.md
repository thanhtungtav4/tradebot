# 03_STRATEGY_ENGINE_SPEC - Strategy Engine

## 1. Mục tiêu

Strategy engine chạy các plugin strategy độc lập, nhận context đã chuẩn hóa và trả về signal candidate. Strategy không biết Telegram group, không gửi message và không tự ghi delivery.

## 2. Strategy plugin interface

```python
class BaseStrategy:
    code: str
    name: str
    required_timeframes: list[str]
    trigger_timeframes: list[str]

    def detect(self, context: StrategyContext) -> list[SignalCandidate]:
        raise NotImplementedError
```

Quy tắc:

- `code` là unique, ví dụ `liquidity_sweep`.
- Strategy có thể trả 0 hoặc nhiều candidate.
- Strategy không được dùng candle `isClosed=false`.
- Strategy không gọi AI, Telegram, DB write trực tiếp.
- Strategy chỉ được enqueue từ `trigger_timeframes`. Với Liquidity Sweep v1, `M15` là trigger timeframe; `H1` chỉ là context feed.

## 3. Strategy context

```json
{
  "symbol": "XAUUSD",
  "triggerTimeframe": "M15",
  "timeframes": {
    "M15": [],
    "H1": []
  },
  "latestClosedCandleTime": "2026-06-30T10:15:00Z",
  "session": "LONDON",
  "spread": "18",
  "strategyConfig": {},
  "symbolConfig": {},
  "marketContext": {}
}
```

Context builder chịu trách nhiệm:

- Load đủ lookback candles.
- Tính session nếu bật (xem bảng session dưới).
- Tính spread hiện tại.
- Inject `strategyConfig` từ `strategies.default_config`.
- Reject sớm nếu thiếu timeframe bắt buộc.

## 3a. Lookback requirement và cold-start

Mỗi strategy khai báo lookback tối thiểu mỗi timeframe. Liquidity Sweep v1:

- M15: `swingLookback + confirmationCandles + 1` = 22 nến đã đóng.
- H1: `trendEmaSlow + 1` nến đã đóng (xem `§5 H1 trend filter`).

Context builder:

- Đếm candle `isClosed=true` đã có cho từng required timeframe.
- Nếu bất kỳ timeframe nào thiếu lookback, tạo một `signals` row trạng thái `REJECTED` với `reject_code=INSUFFICIENT_HISTORY`, `source_candle_time` là trigger candle, và ghi event `WARMUP_SKIPPED`. Đây không phải lỗi vận hành; nó là warmup có thể nhìn thấy trong Admin Console.
- `INSUFFICIENT_TREND_DATA` chỉ dùng khi đủ candle nhưng EMA không tính được vì lý do khác (gap data).

Warmup không backfill production; nguồn history xem `02_DATA_SOURCE_SPEC.md §9 Cold-start warmup`.

Group-level config không được ảnh hưởng bước detect signal. Các ngưỡng theo group như `minConfidence`, `cooldown`, `sendMode` và group-specific risk filter chỉ dùng ở Router/Group Eligibility.

### Session windows

`session` tính từ `candleTime` (UTC) theo bảng cố định, không cần table riêng trong MVP:

| Session | UTC window |
| --- | --- |
| `SYDNEY` | 21:00–06:00 |
| `TOKYO` | 00:00–09:00 |
| `LONDON` | 07:00–16:00 |
| `NEWYORK` | 12:00–21:00 |

Windows có thể chồng lấp (London/NY overlap). Khi nhiều session match, ưu tiên theo thứ tự `LONDON > NEWYORK > TOKYO > SYDNEY` để trả một label chính. MVP chỉ dùng session làm metadata/context; session filter (`session_filter` trong risk config) mặc định null nên không lọc. DST không tính trong MVP (windows cố định UTC).

## 4. Signal candidate contract

```json
{
  "strategyCode": "liquidity_sweep",
  "symbol": "XAUUSD",
  "timeframe": "M15",
  "action": "BUY",
  "entry": "2325.50",
  "sl": "2318.00",
  "tp": ["2332.00", "2340.00"],
  "riskReward": "1.80",
  "confidence": 76,
  "reason": [
    "Swept previous low",
    "Closed back above swing low",
    "M15 bullish confirmation",
    "H1 trend not bearish"
  ],
  "invalidIf": "M15 closes below 2318.00",
  "sourceCandleTime": "2026-06-30T10:15:00Z",
  "metadata": {}
}
```

Strategy phải tạo đủ `entry`, `sl`, `tp`, `riskReward`, `invalidIf`. Risk manager có thể reject nhưng không tự bịa giá còn thiếu.

`sourceCandleTime` phải là `candle_time` của **confirmation candle** (nến quyết định entry), không phải sweep candle. Đây là candle xác định signal nên dùng nó để build `signal_uid` deterministic (xem `04 §6`). Hai job chạy lại cùng setup phải ra cùng `sourceCandleTime` → cùng uid → duplicate guard giữ vững.

## 5. Liquidity Sweep v1

### Defaults

| Setting | Default |
| --- | --- |
| `triggerTimeframe` | `M15` |
| `triggerTimeframes` | `["M15"]` |
| `contextTimeframe` | `H1` |
| `swingLookback` | `20` |
| `confirmationCandles` | `1` |
| `minRiskReward` | `1.5` |
| `tp1R` | `1.0` |
| `tp2R` | `2.0` |
| `slBufferPoints` | from `symbol_settings` |

### BUY rules

1. H1 trend không bearish mạnh.
2. M15 candle quét xuống dưới swing low của `swingLookback`.
3. Sweep candle đóng lại trên swing low đã bị quét.
4. Candle xác nhận sau đó là bullish candle.
5. Entry là close của confirmation candle.
6. SL nằm dưới sweep low + symbol buffer.
7. TP1 = 1R, TP2 = 2R.
8. Reject nếu RR tới TP2 nhỏ hơn `minRiskReward`.

### SELL rules

1. H1 trend không bullish mạnh.
2. M15 candle quét lên trên swing high của `swingLookback`.
3. Sweep candle đóng lại dưới swing high đã bị quét.
4. Candle xác nhận sau đó là bearish candle.
5. Entry là close của confirmation candle.
6. SL nằm trên sweep high + symbol buffer.
7. TP1 = 1R, TP2 = 2R.
8. Reject nếu RR tới TP2 nhỏ hơn `minRiskReward`.

### H1 trend filter

MVP dùng EMA đơn giản. Để giảm warmup cho cold-start, MVP dùng EMA nhanh thay vì EMA200:

| Setting | Default |
| --- | --- |
| `trendEmaFast` | `20` |
| `trendEmaSlow` | `50` |

- Không BUY nếu `EMA20(H1) < EMA50(H1)`.
- Không SELL nếu `EMA20(H1) > EMA50(H1)`.
- Cần tối thiểu `trendEmaSlow + 1` = 51 nến H1 đã đóng. Thiếu candle để tính EMA reject với `INSUFFICIENT_HISTORY` (warmup); EMA tính được nhưng lỗi data khác reject `INSUFFICIENT_TREND_DATA`.

`trendEmaFast`/`trendEmaSlow` để trong `strategies.default_config`, nâng lên EMA50/EMA200 ở phase sau khi đã đủ history.

### Confidence scoring v1

`confidence` (0-100) phải deterministic, tính từ rule-based score, không random. MVP dùng base + bonus, clamp 0-100:

| Thành phần | Điểm |
| --- | --- |
| Base (setup hợp lệ pass mọi rule) | `60` |
| H1 trend cùng hướng (EMA fast lệch slow ≥ `trendGapPoints`) | `+10` |
| Sweep mạnh: wick vượt swing ≥ `sweepDepthPoints` | `+10` |
| RR tới TP2 ≥ `2.0` | `+10` |
| Confirmation candle body ≥ `confirmBodyRatio` × range | `+10` |

```text
confidence = clamp(60 + sum(bonus áp dụng), 0, 100)
```

Defaults trong `strategies.default_config`:

| Setting | Default |
| --- | --- |
| `trendGapPoints` | `5` |
| `sweepDepthPoints` | `10` |
| `confirmBodyRatio` | `0.5` |

Confidence là thuộc tính global của signal, group lọc bằng `minConfidence` ở Router (`03 §3`). Không tính lại confidence theo group. AI filter phase sau có thể điều chỉnh confidence (xem `10 §2`), MVP không.

## 6. Strategy registry

Strategy registry map `strategyCode` tới class plugin:

```text
liquidity_sweep -> LiquiditySweepStrategy
```

Không import động từ user input. Strategy mới phải được đăng ký trong code và seed vào bảng `strategies`.

## 7. Acceptance criteria

- Fake candle test tạo được BUY liquidity sweep hợp lệ.
- Fake candle test tạo được SELL liquidity sweep hợp lệ.
- Reject khi dùng candle chưa đóng.
- Reject `INSUFFICIENT_HISTORY` khi chưa đủ lookback (warmup), tạo signal row `REJECTED` và event `WARMUP_SKIPPED`.
- Reject khi thiếu H1 candles để tính trend.
- Reject khi RR thấp hơn config.
- Strategy không phụ thuộc Telegram group hoặc delivery.
