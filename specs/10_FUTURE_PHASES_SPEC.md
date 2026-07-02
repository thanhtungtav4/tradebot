# 10_FUTURE_PHASES_SPEC - Future Phases and Boundaries

## 1. Mục tiêu

Future features phải mở rộng hệ thống mà không phá core MVP. Data source mới thêm adapter/ingestor, strategy mới thêm plugin, auto-trade thêm engine riêng.

## 2. AI filter

AI filter nằm sau rule strategy và risk pre-check.

Luồng:

```text
SignalCandidate -> Risk pre-check -> AI Filter -> Risk final check -> Router
```

AI không được:

- Tự tạo BUY/SELL.
- Tự bịa entry/SL/TP.
- Sửa giá nếu rule engine không cung cấp.
- Pass signal khi data thiếu.

AI output bắt buộc JSON:

```json
{
  "validSignal": true,
  "confidenceAdjustment": 6,
  "finalConfidence": 82,
  "riskNote": "Setup dep nhung can tranh vao neu gia dong duoi entry zone.",
  "telegramReason": "Sweep day + nen xac nhan + H1 khong bearish."
}
```

## 3. MT5 connector

MT5 connector là phase sau khi có Windows VPS hoặc Windows host.

Luồng:

```text
MT5 Terminal -> Python MT5 Connector -> POST /api/v1/bridge/mt5/candles -> backend DB
```

MT5 connector phải có:

- Windows host/VPS có MT5 terminal local.
- Broker account login.
- Broker symbol mapping.
- Heartbeat.
- Candle/tick payload validation.
- Data feed stale alert.

MT5 không được làm thay đổi Strategy Engine; nó chỉ thêm nguồn candle/tick.

## 4. TradingView confirmation

TradingView có 2 mode future:

- `CONFIRMATION`: chỉ xác nhận signal do rule engine tạo.
- `EXTERNAL_SIGNAL`: tạo signal candidate từ alert TradingView.

Mode được cấu hình theo group/strategy. Mặc định không bật.

TradingView payload không được ghi vào `market_candles`.

## 5. MT4 bridge

MT4 dùng EA MQL4 gửi HTTP POST về API.

Bridge phải có:

- Source secret riêng.
- Account id.
- Broker.
- Symbol mapping.
- Terminal heartbeat.
- Candle/tick payload validation.

MT4 data phải đi qua cùng canonical candle model như MT5.

## 6. Backtest/report

Backtest/report dùng dữ liệu đã lưu:

- Signals.
- Candles.
- Deliveries.
- Manual/auto outcomes.

Phase đầu cho phép admin cập nhật outcome thủ công:

```text
WIN
LOSS
BREAKEVEN
CANCELLED
EXPIRED
```

Sau đó mới tự động scan TP/SL theo candles.

## 7. Auto-trade boundary

Auto-trade không nằm trong MVP.

Khi làm auto-trade:

```text
Signal Engine -> Approved Signal -> Execution Engine -> Broker Adapter -> Order Log
```

Không cho Strategy Engine gọi lệnh trực tiếp. Execution Engine phải có risk cap riêng:

- Max lots.
- Max daily loss.
- Max open positions.
- Per-symbol exposure.
- Kill switch.
- Manual approval mode.

## 8. Strategy expansion

Strategy mới phải:

- Implement `BaseStrategy`.
- Có unit tests BUY/SELL/reject.
- Có default config.
- Seed vào `strategies`.
- Không sửa Router hoặc Telegram Sender.

Candidate sau Liquidity Sweep:

- `ema_pullback`
- `breakout_retest`
- `rsi_divergence`
- `smc_ict`

## 9. Acceptance criteria

- Bật AI filter không yêu cầu sửa Liquidity Sweep.
- Thêm TradingView signal/confirmation mode không sửa Strategy Engine core.
- Thêm MT5 connector không sửa Strategy Engine core.
- Thêm MT4 bridge không sửa Router.
- Auto-trade thêm module riêng, không đổi signal delivery behavior.
- Strategy mới không cần hardcode group-specific logic.
