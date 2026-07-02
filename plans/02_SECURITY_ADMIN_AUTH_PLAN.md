# 02_SECURITY_ADMIN_AUTH_PLAN - Security and Admin Auth

## 1. Mục tiêu

Bảo vệ Admin Console, Admin API, TradingView webhook, secrets và logs. Sau plan này, admin UI/API không thể bị dùng khi chưa auth, webhook không nhận payload giả dễ dàng, và log không rò token.

## 2. Spec nguồn

- `specs/07_API_ADMIN_SPEC.md`
- `specs/08_SECURITY_SPEC.md`
- `specs/12_ADMIN_CONSOLE_SPEC.md`

## 3. Artifacts cần tạo khi implement

- Auth middleware/dependencies.
- Session auth for Admin Console.
- CSRF helpers.
- Bearer API key auth for scripts.
- Webhook auth validator.
- Secret redaction logger/filter.
- Admin login/logout templates.
- Tests for auth, CSRF, rate-limit basics, redaction.

## 4. Work breakdown

### 4.1 Admin Console session auth

- Implement login with `ADMIN_USERNAME` and `ADMIN_PASSWORD_HASH`.
- Use secure session cookie.
- Add logout that invalidates session.
- Enforce auth for all Admin Console routes.
- Session timeout defaults to 8 hours.
- Failed login attempts are rate-limited.

### 4.2 CSRF protection

- Generate CSRF token per session.
- Require CSRF token for all browser state-changing requests.
- Exempt pure JSON webhook endpoints.
- Preserve form input on CSRF/validation errors where possible.

### 4.3 Bearer admin API key

- Support `Authorization: Bearer {ADMIN_API_KEY}` for script/smoke use.
- Compare token with constant-time compare.
- Never log raw API key.
- Return standard error shape for invalid/missing auth.

### 4.4 TradingView webhook auth

MVP decision:

- TradingView alert uses `POST /api/v1/webhooks/tradingview/bars/{webhookToken}` plus `secret` in JSON body because TradingView custom dynamic headers/HMAC are not available.
- HMAC validation remains in code/spec for future custom bridge senders.

Implement:

- Validate path token by hashing and matching `data_sources.webhook_token_hash`.
- Validate body secret by hashing and matching `data_sources.body_secret_hash`.
- Reject missing/invalid secret.
- Redact secret before persisting `raw_payload`.
- Keep source id mapping to `data_sources`.

### 4.5 Secret redaction

Redact keys:

- token
- secret
- password
- authorization
- signature
- api_key
- bot_token

Apply redaction to:

- App logs.
- Request logging.
- Error detail.
- Admin Console rendered data.

## 5. Acceptance criteria

- Admin Console unauthenticated request redirects to login or returns 401.
- Admin API without Bearer key returns 401.
- Browser mutation without CSRF token fails.
- TradingView webhook with wrong path token or body secret fails.
- Logs and rendered HTML never include bot token, admin key, password hash, TradingView token/body secret or Authorization header.

## 6. Risks and notes

- Do not store plain admin password in `.env`; store hash only.
- Admin Console must not expose `.env` values through Settings.
- If later adding multi-user admin, migrate from single admin env credentials to users table/session model.
