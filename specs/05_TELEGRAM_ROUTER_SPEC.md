# 05_TELEGRAM_ROUTER_SPEC - Telegram Router and Delivery

## 1. Mục tiêu

Router quyết định signal nào gửi tới group nào dựa trên config. Telegram sender chỉ xử lý format và gửi message, không tự chọn group.

## 2. Group config

Source of truth:

- `telegram_groups`
- `group_strategy_settings`
- `group_strategy_symbols`
- `group_strategy_timeframes`

Config example:

```json
{
  "groupId": 1,
  "name": "VIP XAUUSD SMC",
  "telegramChatId": "-100123456789",
  "type": "VIP",
  "isActive": true,
  "strategyCode": "liquidity_sweep",
  "symbols": ["XAUUSD"],
  "timeframes": ["M15"],
  "minConfidence": 80,
  "riskLevel": "MEDIUM",
  "config": {
    "send_mode": "FULL",
    "cooldown_minutes": 30,
    "max_spread": 30,
    "min_rr": 1.5
  }
}
```

## 3. Routing rules

Không gửi nếu:

- Group inactive.
- Group setting inactive.
- Symbol không có trong `group_strategy_symbols`.
- Timeframe không có trong `group_strategy_timeframes`.
- Strategy không khớp.
- Confidence dưới `minConfidence`.
- Risk manager reject.
- Cooldown đang active cho group.
- Delivery duplicate đã tồn tại.

Nếu pass, router tạo `telegram_outbox` row với status `PENDING`.

## 4. Delivery UID

`delivery_uid` deterministic:

```text
{signal_uid}:{group_id}
```

DB constraint:

```text
UNIQUE(delivery_uid)
```

Retry chỉ update cùng `telegram_outbox` row và append một row mới vào `signal_deliveries` cho từng attempt. Không tạo outbox row mới.

## 5. Message modes

Enum:

```text
BASIC
FULL
SUMMARY
```

Mapping mặc định:

| Group type | Default send mode |
| --- | --- |
| `FREE` | `BASIC` |
| `VIP` | `FULL` |
| `SMC` | `FULL` |

## 6. Message templates

### BASIC

```text
FOREX SIGNAL

Pair: XAUUSD
Action: BUY
Zone: 2325.00 - 2327.00
Timeframe: M15

Reason:
Liquidity sweep detected.

Quan ly von can than.
```

### FULL

```text
VIP FOREX SIGNAL

Pair: XAUUSD
Action: BUY
Entry: 2325.50
SL: 2318.00
TP1: 2332.00
TP2: 2340.00
RR: 1.8
Timeframe: M15
Strategy: Liquidity Sweep
Confidence: 82%

Reason:
- Swept previous low
- M15 bullish confirmation
- H1 trend not bearish

Invalid if:
M15 closes below 2318.00

Khong phai loi khuyen tai chinh.
```

Templates trong code phải escape Markdown/HTML nếu dùng parse mode. MVP có thể gửi plain text để giảm lỗi.

## 7. Telegram API behavior

Endpoint:

```http
POST https://api.telegram.org/bot{TOKEN}/sendMessage
```

Retry:

- Retry tối đa 3 lần.
- Backoff: 30s, 2m, 5m. Worker set `next_attempt_at = NOW() + backoff` và status `FAILED_RETRYABLE`.
- HTTP 429: dùng `retry_after` nếu Telegram trả về (override backoff).
- HTTP 400 chat not found hoặc bot blocked: mark `FAILED_PERMANENT`.

Trigger retry:

- Scheduler (`01 §3`) scan outbox mỗi `RETRY_SCAN_INTERVAL_SECONDS` (default 20s), enqueue lại job cho:
  - row `FAILED_RETRYABLE`/`PENDING` có `next_attempt_at <= NOW()` và không có lock active.
  - row `SENDING` có `locked_until < NOW()` để worker reclaim stale lock.
- Scan interval (20s) phải nhỏ hơn backoff nhỏ nhất (30s) để không trượt lịch retry.
- Sau 3 lần fail retryable, mark `FAILED_PERMANENT`, dừng scan.

## 8. Outbox statuses

```text
PENDING
SENDING
SENT
FAILED_RETRYABLE
FAILED_PERMANENT
SKIPPED
```

Worker phải lock outbox row trước khi gửi để tránh 2 worker gửi cùng message.

### Lock claim và stale lock recovery

Worker claim row atomic, không pick row đang bị worker khác giữ. Schema dùng `locked_until` + `lock_token` như định nghĩa trong `06_DATABASE_SPEC.md`.

```sql
UPDATE telegram_outbox
SET status = 'SENDING',
    locked_by = :worker_id,
    lock_token = :lock_token,
    locked_until = NOW() + INTERVAL '2 minutes',
    updated_at = NOW()
WHERE id = (
  SELECT id FROM telegram_outbox
  WHERE (
      status IN ('PENDING', 'FAILED_RETRYABLE')
      AND next_attempt_at <= NOW()
      AND (locked_until IS NULL OR locked_until < NOW())
    )
    OR (
      status = 'SENDING'
      AND locked_until < NOW()
    )
  ORDER BY next_attempt_at
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING *;
```

Quy tắc:

- Lock được coi là stale nếu `locked_until < NOW()`. Worker crash giữa `SENDING` thì row được claim lại sau khi lock hết hạn, không kẹt vĩnh viễn.
- `FOR UPDATE SKIP LOCKED` chống 2 worker claim cùng row trong cùng thời điểm.
- Trước khi reclaim một row `SENDING` stale, worker append event/log `outbox_stale_lock_reclaimed` và kiểm tra attempt log gần nhất. Nếu attempt gần nhất đã có `telegram_message_id` hoặc status `SENT`, mark outbox `SENT` thay vì gửi lại. Nếu không xác định được, vẫn retry (Telegram có thể nhận trùng — chấp nhận rủi ro hiếm này, log rõ).
- `SENT` không bao giờ bị reclaim.

## 8a. Outbox vs deliveries

Hai bảng tách vai trò:

- `telegram_outbox`: current state + work queue. Router tạo row `PENDING`, worker cập nhật status qua các attempt (`SENDING`/`FAILED_RETRYABLE`/`SENT`/`FAILED_PERMANENT`). Có `attempt_count`, `next_attempt_at`, `locked_until`, `lock_token`, `telegram_message_id`.
- `signal_deliveries`: immutable attempt log. Mỗi lần worker gọi Telegram tạo một attempt row mới với `attempt_no`, status, HTTP status, Telegram response/error. Không unique theo `delivery_uid`; unique theo `(outbox_id, attempt_no)`.

Outbox là nguồn truth cho retry và trạng thái hiện tại; deliveries là nguồn truth cho audit/report lịch sử attempt. Chỉ `telegram_outbox.delivery_uid` unique theo `signal_uid + group_id`.

## 9. Acceptance criteria

- Signal hợp lệ route đúng group.
- Group inactive không nhận message.
- Free group nhận BASIC, VIP nhận FULL.
- Retry lỗi temporary không tạo duplicate message row.
- Delivery duplicate theo `signal_uid + group_id` bị chặn.
- Telegram token không xuất hiện trong logs.
