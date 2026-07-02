# 12_ADMIN_CONSOLE_SPEC - Visual Admin Console

## 1. Mục tiêu

Admin Console v1 là giao diện vận hành trực quan cho bot tín hiệu Telegram. Một operator mới nhìn vào trong 5 phút phải trả lời được:

1. Bot đang chạy bình thường không?
2. Data feed nào đang stale hoặc lỗi?
3. Group Telegram nào đang active, group nào lỗi gửi tin?
4. Signal mới nhất là gì, bị reject/route/send ra sao?
5. Nếu có lỗi, bước xử lý tiếp theo là gì?

Admin Console là một phần của MVP. Không được chỉ có API/config/seed.

## 2. Product principles

- Operational first: màn hình đầu tiên là cockpit vận hành, không phải landing page.
- Plain language: UI dùng tiếng Việt rõ ràng cho operator, technical code chỉ để phụ.
- Five-minute clarity: ưu tiên status, nguyên nhân và hành động tiếp theo hơn biểu đồ trang trí.
- Progressive disclosure: overview chỉ hiện điều cần biết; chi tiết mở bằng drill-down.
- Safe operations: thao tác làm dừng gửi tín hiệu, retry, rotate secret phải có confirm rõ hậu quả.
- Audit everything: mọi thao tác admin ảnh hưởng runtime phải ghi `admin_activity_logs`.

## 3. Recommended implementation

MVP nên dùng một trong hai hướng, ưu tiên hướng đơn giản:

1. FastAPI server-rendered Admin Console bằng Jinja2 + HTMX + CSS nội bộ.
2. React/Vite Admin Console nếu team muốn UI phức tạp hơn.

Default decision cho MVP: FastAPI + Jinja2 + HTMX để tránh thêm stack frontend lớn khi repo còn mới. UI vẫn phải đạt đủ layout, states và interaction trong spec này.

## 4. Information architecture

Primary navigation tối đa 7 mục:

1. Overview
2. Feeds
3. Groups
4. Strategies
5. Signals
6. Deliveries
7. Settings

Runbook không là nav chính riêng trong MVP; nó là contextual side panel/link xuất hiện trên mọi alert/degraded state.

Desktop dùng left sidebar hoặc top navigation cố định. Mobile dùng bottom navigation cho 4 mục chính: Overview, Feeds, Groups, Deliveries; các mục còn lại nằm trong More/Settings.

## 5. Global layout

Mọi màn hình admin có:

- Header: environment badge (`LOCAL`, `STAGING`, `PRODUCTION`), global status, last refresh time, manual refresh button.
- Primary nav: current section highlighted.
- Main content: page title rõ ràng, one-line summary, primary actions.
- Alert area: chỉ hiện khi có degraded/down state hoặc required action.
- Contextual runbook link: "Cách xử lý" cho từng lỗi.

Global status labels:

| Status | Meaning | UI copy |
| --- | --- | --- |
| `OK` | All critical components healthy | "Hệ thống đang chạy bình thường" |
| `DEGRADED` | Bot còn chạy nhưng có rủi ro | "Cần kiểm tra: một phần hệ thống đang chậm hoặc thiếu dữ liệu" |
| `DOWN` | Critical component down | "Bot đang lỗi: cần xử lý ngay" |
| `PAUSED` | Sending or group/source paused by admin | "Đang tạm dừng theo cấu hình admin" |

Không dùng màu là tín hiệu duy nhất. Mỗi status phải có icon/label/text.

## 6. Screen: Overview

Overview là màn hình mặc định sau login.

### Top summary

Hiển thị 5 status tiles:

1. Data Feed
2. Strategy Worker
3. Telegram
4. Redis Queue
5. Database

Mỗi tile có:

- Status label: OK/DEGRADED/DOWN/PAUSED.
- Last checked time.
- One-line explanation.
- Primary action nếu lỗi.

Ví dụ copy:

- OK: "TradingView feed đang nhận nến mới."
- DEGRADED: "XAUUSD M15 chưa có candle mới trong 40 phút (ngưỡng stale 35 phút)."
- DOWN: "Redis không phản hồi. Worker có thể không nhận job."
- PAUSED: "Group VIP XAUUSD đang bị tắt bởi admin."

### Feed freshness matrix

Hiển thị ma trận:

| Symbol | M15 | H1 |
| --- | --- | --- |
| XAUUSD | OK, last 2m ago | OK, last 12m ago |
| EURUSD | STALE, last 40m ago | OK, last 12m ago |
| GBPUSD | OK, last 2m ago | OK, last 12m ago |

Stale tính theo timeframe (M15 stale sau 35m, H1 sau 80m — xem `02 §9`), không phải hằng số. Cell M15 40m > 35m nên STALE; H1 12m < 80m nên OK.

Mỗi cell mở được detail:

- Source: TradingView.
- Broker symbol: `OANDA:XAUUSD`.
- Last candle time.
- Age.
- Last payload received at.
- Last error.
- Webhook source id.
- Suggested action.

Warmup cell copy:

```text
Feed đang nhận candle mới nhưng chưa đủ lịch sử cho strategy. Có thể chờ thêm hoặc import history trong local/staging.
```

### Latest signal stream

Hiển thị 10 signal gần nhất:

- Time.
- Symbol/timeframe.
- Strategy.
- Action.
- Confidence.
- Status.
- Routed groups count.
- Sent/failed delivery count.

Click signal mở detail timeline.

### Delivery queue summary

Hiển thị:

- Pending outbox count.
- Retryable failures.
- Permanent failures.
- Last Telegram success.
- Groups with failures.

Primary action:

- "Xem delivery lỗi"
- "Gửi test Telegram"

### Operator next action panel

Nếu mọi thứ OK:

```text
Không có việc cần xử lý. Hệ thống đang nhận data, chạy strategy và gửi Telegram bình thường.
```

Nếu có lỗi:

```text
Cần xử lý: EURUSD M15 bị stale 40 phút (ngưỡng 35 phút).
Bước tiếp theo: kiểm tra TradingView alert cho EURUSD M15 hoặc tạm tắt group dùng EURUSD M15.
```

## 7. Screen: Feeds

Mục tiêu: quản lý và debug data feed.

### Feed list

Columns:

- Source.
- Canonical symbol.
- Source symbol.
- Timeframe.
- Active.
- Last candle time.
- Age.
- Status.
- Last error.
- Actions.

Actions:

- View detail.
- Copy webhook payload template.
- Copy webhook URL.
- Send local test payload, chỉ trong local/staging.
- Pause/resume feed.

### Feed detail

Sections:

- Identity: source id, source symbol, canonical symbol, timeframe.
- Webhook setup: URL, headers, example JSON payload.
- Health: latest candle, stale threshold, last 20 ingest attempts.
- Troubleshooting: runbook for stale feed.

Important copy:

```text
TradingView không tự backfill lịch sử. Nếu alert bị tắt, bot sẽ thiếu candle cho khoảng thời gian đó.
```

## 8. Screen: Groups

Mục tiêu: admin thêm/sửa/tắt group Telegram mà không cần đọc API docs.

### Group list

Columns:

- Name.
- Type: FREE/VIP/SMC/INTERNAL.
- Active.
- Chat id.
- Strategies.
- Last sent at.
- Last delivery status.
- Actions.

Actions:

- View.
- Edit.
- Test message.
- Pause/Resume.

### Add group wizard

4 steps:

1. Group identity.
2. Telegram connection.
3. Strategy settings.
4. Review and enable.

#### Step 1 - Group identity

Fields:

- Group name.
- Type: FREE/VIP/SMC/INTERNAL.
- Mode: Demo/Internal/Live.
- Active toggle default false.

Validation:

- Name required, 3-100 chars.
- Type required.

#### Step 2 - Telegram connection

Fields:

- Telegram chat id.
- Bot status check.

Actions:

- Copy instruction: "Add bot vào group, gửi một tin bất kỳ, sau đó nhập chat id."
- Test message.

Success state:

```text
Test message đã gửi thành công. Group sẵn sàng nhận tín hiệu.
```

Error state:

```text
Không gửi được test message. Kiểm tra bot đã được add vào group và có quyền gửi tin.
```

#### Step 3 - Strategy settings

Fields:

- Strategy.
- Symbols.
- Timeframes.
- Minimum confidence.
- Cooldown minutes.
- Send mode: BASIC/FULL/SUMMARY.
- Max spread.
- Min RR.

Inline explanation:

```text
Cooldown giúp tránh spam cùng một tín hiệu trong một khoảng thời gian.
```

#### Step 4 - Review and enable

Show summary:

- Group name/type/mode.
- Telegram test status.
- Strategy settings.
- Risk/router settings.

Primary actions:

- Save as inactive.
- Save and enable demo.

Live enable requires confirm:

```text
Bật live cho "VIP XAUUSD"? Group này sẽ nhận tín hiệu thật khi strategy pass filter.
```

Buttons:

- "Bật live"
- "Giữ demo"

## 9. Screen: Strategies

Mục tiêu: xem strategy đang hoạt động ra sao và setting nào áp dụng cho group.

Sections:

- Strategy registry: code, name, active, default config.
- Group strategy settings: group, symbols, timeframes, min confidence, cooldown, send mode.
- Detection note: group-level config không ảnh hưởng logic detect global, chỉ ảnh hưởng routing/eligibility.

Actions:

- Activate/deactivate strategy.
- Edit default config, nếu allowed.
- Edit group setting.

Safety:

- Deactivating a strategy requires confirm and shows affected groups.

## 10. Screen: Signals

Mục tiêu: audit tín hiệu.

List filters:

- Date range.
- Symbol.
- Timeframe.
- Strategy.
- Action.
- Status.
- Confidence range.

Columns:

- Created at.
- Symbol/timeframe.
- Strategy.
- Action.
- Entry/SL/TP.
- RR.
- Confidence.
- Status.
- Routed groups.

Signal detail:

- Signal summary.
- Reason.
- Invalid condition.
- Raw candidate.
- Risk check result.
- Duplicate check result.
- Routing result per group.
- Delivery result per group.
- Event timeline.

Empty state:

```text
Chưa có tín hiệu nào. Khi TradingView gửi đủ candle và strategy phát hiện setup, tín hiệu sẽ xuất hiện ở đây.
```

## 11. Screen: Deliveries

Mục tiêu: theo dõi và xử lý gửi Telegram.

Tabs:

- Pending.
- Failed retryable.
- Failed permanent.
- Sent.

Columns:

- Created at.
- Group.
- Signal.
- Status.
- Attempts.
- Next retry.
- Last error.
- Actions.

Actions:

- Retry now, only for retryable/permitted statuses.
- Mark skipped, with reason.
- Open group detail.
- Open signal detail.

Bulk retry phải có confirm:

```text
Retry 12 delivery lỗi? Telegram có thể nhận lại các tin chưa gửi thành công. Delivery đã SENT sẽ không gửi lại.
```

## 12. Screen: Settings

Sections:

- TradingView webhook setup.
- Active symbols/timeframes.
- Telegram bot test.
- Stale thresholds.
- Admin security.
- Backup status.

TradingView webhook setup must show:

- Webhook URL.
- Source id.
- Required headers.
- Example JSON payload.
- TradingView auth note: path token + body secret. HMAC note chỉ dành cho MT4/MT5/custom webhook future.

Secret display:

- Never show full secret after initial creation.
- Show masked value: `tv_********abcd`.
- Rotation requires confirmation.

## 13. Contextual runbooks

Every degraded/down state links to a runbook panel.

Required runbooks:

- Data feed stale.
- Telegram bot kicked/lost permission.
- Redis down.
- Database down/full.
- Delivery retry stuck.
- VPS restart.
- MT5 connector stale, future phase.

Runbook panel format:

1. What happened.
2. Why it matters.
3. What to check.
4. Safe actions.
5. When to pause affected groups.

## 14. UI states

Every screen must define:

- Loading state.
- Empty state.
- Success state.
- Validation error state.
- Permission error state.
- Dependency down state.

Required examples:

- No webhook received yet.
- Data feed warmup.
- Data feed stale.
- Telegram bot cannot send.
- Redis down.
- DB down.
- No signals yet.
- No failed deliveries.

## 15. Accessibility requirements

Minimum WCAG AA:

- Text contrast 4.5:1.
- Touch targets at least 44x44 CSS px.
- Keyboard navigation for all controls.
- Visible focus state.
- Form inputs have visible labels.
- Errors are text, not color only.
- Tables have headers and accessible names.
- Status uses icon + label + text, not color only.
- Supports 200% zoom without content loss.

## 16. Interaction and safety

Destructive or operationally risky actions require confirmation:

- Disable group.
- Enable live mode.
- Disable strategy.
- Pause data feed.
- Rotate TradingView token/body secret or future HMAC secret.
- Bulk retry deliveries.

Confirm dialogs use asymmetric labels:

- "Tắt group" / "Giữ group đang bật"
- "Bật live" / "Giữ demo"
- "Rotate secret" / "Giữ secret hiện tại"

Forms must preserve valid input on errors.

## 17. Admin API data needs

Admin Console needs these API shapes:

```text
GET /api/v1/admin/overview
GET /api/v1/admin/feeds/status
GET /api/v1/admin/groups
GET /api/v1/admin/groups/{groupId}
POST /api/v1/admin/groups
PATCH /api/v1/admin/groups/{groupId}
POST /api/v1/admin/telegram/test-message
GET /api/v1/admin/signals
GET /api/v1/admin/signals/{signalId}
GET /api/v1/admin/signals/{signalId}/events
GET /api/v1/admin/deliveries
POST /api/v1/admin/outbox/{deliveryUid}/retry
GET /api/v1/admin/activity-logs
```

Overview response must include:

- Component status summary.
- Feed matrix.
- Latest signals.
- Delivery summary.
- Active groups summary.
- Operator next action.

## 18. Five-minute usability checklist

Before release, ask a person who did not build the system to open Admin Console and answer within 5 minutes:

1. Bot đang OK, degraded hay down?
2. Nếu lỗi, lỗi nằm ở data feed, Telegram, Redis, DB hay worker?
3. Có symbol/timeframe nào stale không?
4. Có group nào đang fail delivery không?
5. Signal mới nhất là gì và đã gửi tới group nào?
6. Nếu cần xử lý lỗi, UI đề xuất bước tiếp theo là gì?

Pass criteria:

- At least 5/6 questions answered correctly.
- No log/terminal/API docs needed.
- Operator can send a test Telegram message from UI.
- Operator can find runbook for a degraded state from the same screen.

## 19. MVP acceptance criteria

- Admin Console is reachable after login.
- Overview is the first screen.
- Overview shows DB, Redis, data feed, Telegram and worker status.
- Feed matrix shows all 6 MVP feeds: 3 symbols x 2 timeframes.
- Group wizard can create a demo group and send a test message.
- Signals screen shows event timeline for a signal.
- Deliveries screen shows pending/retryable/permanent/sent statuses.
- Failed delivery has clear copy explaining what happened and how to fix it.
- Admin actions are written to `admin_activity_logs`.
- Five-minute usability checklist passes.
