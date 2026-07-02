# 08_SECURITY_SPEC - Security

## 1. Mục tiêu

Bảo vệ token, webhook, admin API và log. Security MVP không cần phức tạp, nhưng phải đủ để chạy VPS public không lộ secret hoặc bị spam endpoint.

## 2. Secret management

- Tất cả token/secret nằm trong env hoặc secret manager.
- Không hardcode Telegram bot token, MT5 password, admin key.
- Không commit `.env`.
- `.env.example` chỉ chứa placeholder.
- Logs không được in full secret, token, password, signed payload header.

## 3. Admin auth

MVP supports two admin access modes:

1. Browser Admin Console session auth.
2. Machine/API Bearer key for scripts and local smoke tests.

Machine/API mode:

```http
Authorization: Bearer {ADMIN_API_KEY}
```

Yêu cầu:

- API key dài tối thiểu 32 ký tự.
- So sánh bằng constant-time compare.
- Missing/invalid key trả 401.
- Không log raw key.

Browser Admin Console mode:

- Login bằng username/password hoặc single admin password từ env trong MVP.
- Password/session secret không hardcode.
- Plain password không lưu trong `.env`; dùng `ADMIN_PASSWORD_HASH`.
- Session cookie `HttpOnly`, `Secure` in production, `SameSite=Lax`.
- CSRF token bắt buộc cho state-changing form/API calls từ browser.
- Session timeout mặc định 8 giờ.
- Logout phải invalidate session.
- Failed login rate limited.
- CORS mặc định deny cross-origin cho admin routes, trừ khi cấu hình explicit allowed origins.
- Admin Console không được expose raw `.env`, bot token, HMAC secret hoặc DB URL.

Future có thể nâng lên JWT user/role, nhưng không cần cho MVP.

## 4. Webhook authentication

Cơ chế auth khác nhau theo nguồn vì TradingView alert **không** set được custom HTTP header động và **không** ký HMAC được. Một alert TradingView chỉ POST một body cố định tới một URL cố định. Vì vậy không dùng `X-Signature`/`X-Timestamp` header cho TradingView.

### 4a. TradingView bar webhook (MVP)

TradingView không ký HMAC được nên dùng kết hợp **URL secret token + body shared secret + IP allowlist**:

- Endpoint nhận token trong path: `POST /api/v1/webhooks/tradingview/bars/{webhook_token}`. `webhook_token` là random ≥32 ký tự. Backend hash token rồi lookup bằng `data_sources.webhook_token_hash`.
- Body bắt buộc có field `secret`; backend hash và so sánh constant-time với `data_sources.body_secret_hash`. Đây là lớp thứ hai phòng khi URL lộ.
- IP allowlist: chỉ chấp nhận từ dải IP TradingView công bố (config `TRADINGVIEW_ALLOWED_IPS`). Bỏ allowlist nếu chạy sau proxy không giữ IP gốc, lúc đó dựa vào token + body secret.
- Reject thứ tự: token không khớp → 401 trước khi parse; body secret sai → 401; IP ngoài allowlist (nếu bật) → 403.
- Replay: TradingView `once per bar close` nên cùng `candle_time` chỉ đến một lần; upsert idempotent theo unique key candle chống ghi trùng. Không dựa vào timestamp drift cho TradingView.

Raw `webhook_token` và `body_secret` không lưu DB. DB chỉ lưu hash hoặc `secret_ref`; Admin Console chỉ hiển thị masked prefix/suffix lúc tạo/rotate và ghi audit cho hành động rotate.

### 4b. MT4/MT5 bridge và signal webhook future (HMAC)

Nguồn tự viết (MT4 EA, MT5 connector, external signal poster) **kiểm soát được header** nên dùng HMAC chuẩn:

Signature input:

```text
{timestamp}.{raw_body}
```

Header:

```text
X-Timestamp: 2026-06-30T10:00:00Z
X-Signature: sha256=<hex_hmac>
X-Source-Id: source_code
```

Validation:

1. Lookup source secret by `X-Source-Id`.
2. Reject nếu timestamp thiếu hoặc lệch quá 5 phút.
3. Tính HMAC SHA256 bằng raw body.
4. Compare constant-time.
5. Parse JSON sau khi signature pass.

## 5. Rate limit

MVP rate limit tối thiểu:

| Endpoint class | Limit |
| --- | --- |
| Admin API | 120 requests/minute per IP |
| Webhook | 300 requests/minute per source id |
| Health live | no strict limit |
| Health full | 60 requests/minute per IP |

Khi vượt limit trả 429 theo error format chuẩn.

## 6. Input validation

Validate tại boundary:

- Admin JSON.
- Webhook JSON.
- Env settings.
- Third-party response từ Telegram.
- Data-source output trước khi lưu DB, gồm TradingView bar webhook MVP và MT5/MT4 future.

Không trust TradingView reason text hoặc Telegram response raw text trong logs/rendering.

## 7. Logging redaction

Redact keys:

```text
token
secret
password
authorization
signature
api_key
bot_token
```

Log payload chỉ nên có metadata:

- source id
- symbol
- timeframe
- strategy
- request id
- status code
- error code

## 8. Network

- Production API chạy sau HTTPS reverse proxy.
- PostgreSQL/Redis không mở public internet.
- Telegram call outbound only.
- VPS firewall chỉ mở cổng cần thiết.
- Windows VPS cho MT5 future phase cũng phải chặn public DB/Redis và chỉ cho phép connector gọi backend qua HTTPS/VPN/internal network.

## 9. Acceptance criteria

- Admin endpoint không auth trả 401.
- TradingView webhook sai `webhook_token` hoặc sai body `secret` trả 401 trước khi xử lý payload.
- MT4/MT5/signal webhook invalid HMAC trả 401 trước khi parse payload.
- Secret không xuất hiện trong application logs.
- Rate limit trả 429 theo standard error shape.
- `.env.example` không chứa secret thật.
- Admin Console state-changing actions require session auth and CSRF protection.
