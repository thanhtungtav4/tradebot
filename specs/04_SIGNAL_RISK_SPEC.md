# 04_SIGNAL_RISK_SPEC - Signal, Risk, Duplicate Guard

## 1. Mục tiêu

Spec này định nghĩa vòng đời signal và các lớp bảo vệ trước khi gửi Telegram. Không tín hiệu nào được gửi nếu thiếu quản trị rủi ro tối thiểu.

## 2. Signal lifecycle

Enum `signal_status`:

```text
CREATED
REJECTED
APPROVED
ROUTED
QUEUED
SENT
PARTIAL_SENT
PARTIAL_FAILED
FAILED
SKIPPED_DUPLICATE
```

Luồng chuẩn:

```text
SignalCandidate
  -> Global Risk Manager
  -> Duplicate Guard
  -> signals row
  -> Router + Group Eligibility
  -> telegram_outbox rows
  -> Telegram Worker
  -> signal_deliveries rows
```

Mọi transition quan trọng ghi vào `signal_events`.

`signal_status` mapping với pipeline:

| Status | Khi nào set |
| --- | --- |
| `CREATED` | Signal candidate vừa lưu vào `signals` |
| `REJECTED` | Global risk reject (kèm `reject_code`) |
| `APPROVED` | Pass global risk + duplicate guard |
| `ROUTED` | Router đã chọn ≥1 group đủ điều kiện |
| `QUEUED` | Đã tạo xong toàn bộ `telegram_outbox` row (PENDING) cho các group routed |
| `SENT` | Tất cả routed deliveries đã gửi thành công |
| `PARTIAL_SENT` | Ít nhất một delivery thành công, vẫn còn delivery pending/retryable |
| `PARTIAL_FAILED` | Ít nhất một delivery thành công và ít nhất một delivery fail permanent |
| `FAILED` | Mọi delivery của signal đều fail permanent |
| `SKIPPED_DUPLICATE` | Duplicate guard chặn, không tạo outbox |

`signals.status` là trạng thái tổng của signal; trạng thái hiện tại per-group nằm ở `telegram_outbox`, còn `signal_deliveries` lưu lịch sử từng attempt. Admin Console không được chỉ nhìn `signals.status`; màn signal detail phải hiển thị breakdown theo outbox group để tránh che lỗi partial delivery.

## 3. Risk requirements

Mỗi signal gửi được phải có:

- `entry`
- `sl`
- ít nhất một `tp`
- `riskReward`
- `invalidIf`
- `confidence`
- `reason`
- `sourceCandleTime`

Global risk reject nếu:

- Thiếu entry, SL, TP hoặc invalid condition.
- `riskReward < min_rr`.
- Spread hiện tại lớn hơn `max_spread` **khi spread có giá trị**. Spread null (TradingView bar webhook không cấp spread, xem `02 §5`) thì **skip** filter này, không reject.
- Data thiếu hoặc stale.
- Signal duplicate trong duplicate window.

Group eligibility skip nếu:

- Confidence nhỏ hơn group `min_confidence`.
- Group đang cooldown cho cùng symbol/strategy/action/timeframe.

## 4. Risk config defaults

Global risk config lấy từ `strategies.default_config` và `symbol_settings`. Group-specific config lấy từ `group_strategy_settings.config` trong Router/Group Eligibility.

```json
{
  "min_rr": 1.5,
  "max_spread": 30,
  "cooldown_minutes": 30,
  "duplicate_window_minutes": 30,
  "entry_tolerance_points": 20,
  "ai_filter_enabled": false,
  "send_mode": "FULL",
  "session_filter": null
}
```

## 4a. Reject codes

`signals.reject_code` và strategy reject dùng enum cố định. Admin Console map sang copy tiếng Việt:

| Code | Tầng | Ý nghĩa | Copy UI |
| --- | --- | --- | --- |
| `INSUFFICIENT_HISTORY` | Strategy | Chưa đủ lookback (warmup) | "Đang chờ đủ dữ liệu lịch sử" |
| `INSUFFICIENT_TREND_DATA` | Strategy | Đủ candle nhưng EMA không tính được | "Thiếu dữ liệu tính xu hướng" |
| `MISSING_PRICE_FIELDS` | Risk | Thiếu entry/SL/TP/invalidIf | "Tín hiệu thiếu giá vào lệnh/SL/TP" |
| `RR_TOO_LOW` | Risk | `riskReward < min_rr` | "Tỷ lệ R:R thấp hơn ngưỡng" |
| `SPREAD_TOO_HIGH` | Risk | Spread vượt `max_spread` | "Spread quá cao" |
| `DATA_STALE` | Risk | Candle dùng đã stale | "Dữ liệu nến đã cũ" |
| `DUPLICATE` | Duplicate guard | Trùng trong duplicate window | "Tín hiệu trùng, đã bỏ qua" |
| `INVALID_RR_MATH` | Risk | `risk<=0`/`reward<=0`/không tính được | "Không tính được R:R" |

Group eligibility skip (không phải reject signal, chỉ skip group) dùng: `BELOW_MIN_CONFIDENCE`, `GROUP_COOLDOWN_ACTIVE`, `SYMBOL_NOT_ALLOWED`, `TIMEFRAME_NOT_ALLOWED`, `STRATEGY_MISMATCH`, `GROUP_INACTIVE`.

Ingest-tầng (trước strategy): `SYMBOL_MAPPING_NOT_FOUND`, `TIMEFRAME_NOT_SUPPORTED`, `CANDLE_NOT_CLOSED`, `CANDLE_IN_FUTURE` (xem `02`).

Code mới phải thêm vào registry này, không tự chế chuỗi tự do.

## 5. Risk reward formula

BUY:

```text
risk = entry - sl
reward = tp2 - entry
rr = reward / risk
```

SELL:

```text
risk = sl - entry
reward = entry - tp2
rr = reward / risk
```

Reject nếu `risk <= 0`, `reward <= 0` hoặc `rr` không tính được.

## 6. Signal UID

`signal_uid` phải deterministic:

```text
{strategyCode}:{symbol}:{timeframe}:{action}:{sourceCandleTime}:{entryBucket}
```

`sourceCandleTime` là `candle_time` của confirmation candle (xem `03 §4`), serialize UTC ISO-8601 dạng cố định (vd `2026-06-30T10:15:00Z`) để cùng setup luôn ra cùng chuỗi.

`entryBucket` làm tròn theo `entry_tolerance_points` để chống trùng gần giá. Công thức: `round(entry / point_size / entry_tolerance_points)` (integer), với `point_size` từ `symbol_settings`. Cùng `point_size` cho mỗi symbol nên bucket deterministic.

DB constraint:

```text
UNIQUE(signal_uid)
```

Nếu insert conflict, mark là duplicate, không tạo delivery mới.

## 7. Duplicate guard

Duplicate nếu cùng:

- `symbol`
- `strategyCode`
- `action`
- `timeframe`
- trong `duplicate_window_minutes`
- entry nằm trong tolerance

Guard dùng cả:

- Redis lock để chặn race condition giữa workers. Lock key = `signal_uid`, set với TTL `DUPLICATE_LOCK_TTL_SECONDS` (default 60s) bằng `SET key value NX EX 60`. TTL đảm bảo worker crash khi giữ lock không gây deadlock cho signal đó. Lock chỉ để serialize ghi trong cửa sổ ngắn, không phải nguồn chống trùng cuối.
- DB unique key `signal_uid` để bảo vệ cuối cùng. Insert conflict → mark duplicate, không tạo delivery. Đây là lớp chống trùng authoritative; Redis lock chỉ giảm contention.

## 8. Cooldown

Cooldown áp dụng theo group:

```text
groupId + symbol + strategyCode + action + timeframe
```

Nếu group A đang cooldown thì chỉ skip group A, không skip group khác.

## 9. Acceptance criteria

- Signal thiếu SL/TP bị reject và có event rõ.
- RR BUY/SELL tính đúng.
- Spread vượt ngưỡng bị reject khi spread có giá trị; spread null thì skip filter, không reject.
- Insert duplicate không tạo delivery mới.
- Cooldown theo group không ảnh hưởng group khác.
- Restart worker không phá duplicate guard vì DB unique vẫn giữ.
