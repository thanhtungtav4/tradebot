# 07_API_ADMIN_SPEC - API and Admin Contract

## 1. Mục tiêu

FastAPI cung cấp health, admin config, signal log, TradingView bar webhook và API cho Admin Console. API v1 phải có contract ổn định, validation rõ và response lỗi thống nhất.

## 2. API conventions

- Base path: `/api/v1`.
- Request/response JSON dùng camelCase.
- DB field snake_case chỉ nằm trong internal model.
- List endpoint luôn có pagination.
- Partial update dùng `PATCH`.
- Boundary validation bằng Pydantic.
- Mọi request có `requestId`: middleware đọc header `X-Request-Id` hoặc sinh mới, echo lại trong response header `X-Request-Id` và đính vào log (xem `09 §2 Correlation id`).

## 3. Error format

Mọi lỗi trả cùng shape:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request payload",
    "details": {}
  }
}
```

HTTP mapping:

| Status | Meaning |
| --- | --- |
| 400 | Bad request hoặc malformed JSON |
| 401 | Missing/invalid auth |
| 403 | Authenticated but forbidden |
| 404 | Resource not found |
| 409 | Conflict/duplicate |
| 422 | Validation failed |
| 429 | Rate limited |
| 500 | Internal error |
| 503 | Dependency down |

## 4. Pagination contract

Request:

```http
GET /api/v1/admin/signals?page=1&pageSize=20&sortBy=createdAt&sortOrder=desc
```

Response:

```json
{
  "data": [],
  "pagination": {
    "page": 1,
    "pageSize": 20,
    "totalItems": 0,
    "totalPages": 0
  }
}
```

Max `pageSize` là 100.

## 5. Auth

Admin endpoints bắt buộc:

```http
Authorization: Bearer {ADMIN_API_KEY}
```

TradingView webhook MVP dùng path token + body secret, không dùng admin key. MT4/MT5 bridge và custom webhook future dùng HMAC headers.

Admin Console browser UI dùng session auth theo `08_SECURITY_SPEC.md`. Machine/API usage vẫn có thể dùng Bearer admin API key.

## 6. Health endpoints

```http
GET /api/v1/health
GET /api/v1/health/live
GET /api/v1/health/ready
```

- `live`: process còn sống.
- `ready`: DB/Redis sẵn sàng.
- `health`: full component check.

## 7. Admin endpoints MVP

```text
GET    /api/v1/admin/groups
POST   /api/v1/admin/groups
GET    /api/v1/admin/groups/{groupId}
PATCH  /api/v1/admin/groups/{groupId}

GET    /api/v1/admin/strategies
GET    /api/v1/admin/group-strategy-settings
POST   /api/v1/admin/group-strategy-settings
PATCH  /api/v1/admin/group-strategy-settings/{settingId}

GET    /api/v1/admin/signals
GET    /api/v1/admin/signals/{signalId}
GET    /api/v1/admin/signals/{signalId}/events

GET    /api/v1/admin/deliveries
POST   /api/v1/admin/telegram/test-message

GET    /api/v1/admin/overview
GET    /api/v1/admin/feeds/status
POST   /api/v1/admin/candles/import
GET    /api/v1/admin/outbox
POST   /api/v1/admin/outbox/{deliveryUid}/retry
GET    /api/v1/admin/activity-logs
```

## 8. Webhook endpoints MVP

```text
POST /api/v1/webhooks/tradingview/bars/{webhookToken}
```

TradingView không ký HMAC được. Auth = `webhookToken` trong path + `secret` trong body + IP allowlist (xem `08 §4a`). Không dùng `X-Signature`/`X-Timestamp` cho TradingView.

MT4/MT5 bridge và signal webhook future dùng HMAC header (`08 §4b`).

## 8a. Local/staging candle import

```text
POST /api/v1/admin/candles/import
```

Purpose:

- Warm up strategy lookback in local/staging before demo.
- Import closed OHLCV candles from CSV/JSON through the same candle normalizer/upsert path.

Rules:

- Enabled only when `APP_ENV in (local, staging)`.
- Requires admin auth.
- Production returns 404 or 403.
- Does not bypass closed-candle, OHLC, symbol mapping or timeframe validation.
- Enqueues strategy only for trigger timeframe rows, same as TradingView ingest.

## 9. Group schemas

Create group request:

```json
{
  "name": "VIP XAUUSD",
  "telegramChatId": "-100123456789",
  "type": "VIP",
  "isActive": true
}
```

Group response:

```json
{
  "id": 1,
  "name": "VIP XAUUSD",
  "telegramChatId": "-100123456789",
  "type": "VIP",
  "isActive": true,
  "createdAt": "2026-06-30T10:00:00Z",
  "updatedAt": "2026-06-30T10:00:00Z"
}
```

## 10. Group strategy setting schema

Request:

```json
{
  "groupId": 1,
  "strategyCode": "liquidity_sweep",
  "symbols": ["XAUUSD"],
  "timeframes": ["M15"],
  "minConfidence": 80,
  "riskLevel": "MEDIUM",
  "isActive": true,
  "config": {
    "min_rr": 1.5,
    "max_spread": 30,
    "cooldown_minutes": 30,
    "duplicate_window_minutes": 30,
    "send_mode": "FULL",
    "ai_filter_enabled": false
  }
}
```

Response (GET list/detail):

```json
{
  "id": 10,
  "groupId": 1,
  "strategyCode": "liquidity_sweep",
  "symbols": ["XAUUSD"],
  "timeframes": ["M15"],
  "minConfidence": 80,
  "riskLevel": "MEDIUM",
  "isActive": true,
  "config": {
    "min_rr": 1.5,
    "max_spread": 30,
    "cooldown_minutes": 30,
    "duplicate_window_minutes": 30,
    "send_mode": "FULL",
    "ai_filter_enabled": false
  },
  "createdAt": "2026-06-30T10:00:00Z",
  "updatedAt": "2026-06-30T10:00:00Z"
}
```

`strategyCode` resolve từ `strategy_id` (join `strategies`) khi trả ra; request dùng `strategyCode`, internal map sang `strategy_id`.

`symbols` and `timeframes` remain arrays in API for Admin Console ergonomics, but service layer stores them in normalized tables `group_strategy_symbols` and `group_strategy_timeframes` in the same transaction as `group_strategy_settings`.

Validation:

- `strategyCode` must exist and active.
- `symbols` must be non-empty and active.
- `timeframes` must be allowed values.
- `minConfidence` range: 0-100.

## 11. Webhook endpoints future

```text
POST /api/v1/webhooks/tradingview/signals
POST /api/v1/bridge/mt4/candles
POST /api/v1/bridge/mt4/ticks
POST /api/v1/bridge/mt5/candles
```

Headers:

```text
X-Signature: sha256=<hex>
X-Timestamp: 2026-06-30T10:00:00Z
X-Source-Id: tradingview_main
```

## 12. Acceptance criteria

- All admin endpoints require auth.
- List endpoints return pagination shape.
- Validation errors use standard error shape.
- Duplicate group chat id returns 409.
- Test Telegram endpoint logs delivery result but does not create trading signal.
- OpenAPI docs expose request/response schemas.
- Admin Console endpoints expose enough data for the Overview, Feeds, Groups, Signals, Deliveries and Settings screens defined in `12_ADMIN_CONSOLE_SPEC.md`.
