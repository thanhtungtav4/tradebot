# 06_ADMIN_CONSOLE_PLAN - Admin Console v1

## 1. Mục tiêu

Build Admin Console trực quan để operator mới nhìn trong 5 phút hiểu bot đang OK hay lỗi ở đâu. Admin Console là MVP, không phải future dashboard.

## 2. Spec nguồn

- `specs/12_ADMIN_CONSOLE_SPEC.md`
- `specs/07_API_ADMIN_SPEC.md`
- `specs/11_PRODUCT_OPS_SPEC.md`
- `specs/06_DATABASE_SPEC.md`

## 3. Artifacts cần tạo khi implement

- Server-rendered pages/templates.
- Shared layout/nav/status components.
- Admin auth screens.
- Overview, Feeds, Groups, Strategies, Signals, Deliveries, Settings.
- Static CSS/JS, preferably minimal.
- Admin form handlers and API endpoints.
- Admin tests.

## 4. Work breakdown

### 4.0 Early skeleton slice

Implement this during Milestone B, before full Admin Console:

- Login page.
- Authenticated shell layout.
- Navigation placeholders.
- Overview placeholder reading `component_health` and `data_source_feeds`.
- Empty states for no signals and no deliveries.

This prevents backend data contracts from drifting away from the operator cockpit requirement.

### 4.1 Layout and navigation

Global layout:

- environment badge.
- global status.
- last refresh time.
- manual refresh.
- nav: Overview, Feeds, Groups, Strategies, Signals, Deliveries, Settings.
- contextual alert area.

Accessibility:

- keyboard navigation.
- visible focus.
- semantic buttons/forms/tables.
- no status conveyed by color only.

### 4.2 Overview

Show:

- status tiles: Data Feed, Strategy Worker, Telegram, Redis Queue, Database.
- feed freshness matrix: 3 symbols x 2 timeframes.
- feed matrix supports `UNKNOWN`, `WARMUP`, `OK`, `STALE`, `ERROR`, `PAUSED`.
- latest 10 signals.
- delivery queue summary.
- operator next action panel.

Acceptance:

- operator can identify stale feed and next action without logs.

### 4.3 Feeds

Show:

- active feeds list.
- source symbol/canonical symbol/timeframe.
- last candle time, age, status, last error.
- copy webhook URL/payload template.
- local/staging test payload action.
- pause/resume feed.

### 4.4 Groups wizard

Steps:

1. Group identity.
2. Telegram connection/test message.
3. Strategy settings.
4. Review and enable.

Rules:

- New group defaults inactive/demo.
- Live enable requires explicit confirmation.
- Test message result is visible.
- Runtime-changing actions write `admin_activity_logs`.

### 4.5 Strategies

Show:

- registered strategies.
- active/inactive state.
- default config.
- group strategy settings.

Must explain:

- group-level settings affect routing/eligibility, not strategy detection.

### 4.6 Signals

List filters:

- date, symbol, timeframe, strategy, action, status, confidence.

Detail shows:

- candidate summary.
- risk result.
- duplicate result.
- routing result per group.
- delivery result per group.
- signal event timeline.

### 4.7 Deliveries

Tabs:

- Pending.
- Failed retryable.
- Failed permanent.
- Sent.

Actions:

- Retry now.
- Mark skipped with reason.
- Open group/signal detail.

Bulk retry requires confirmation.

### 4.8 Settings and runbooks

Settings:

- TradingView webhook setup.
- active symbols/timeframes.
- Telegram bot test.
- stale thresholds.
- admin security summary.

Runbooks:

- stale feed.
- Telegram bot kicked.
- Redis down.
- DB down/full.
- delivery stuck.
- VPS restart.

## 5. Acceptance criteria

- Admin Console reachable after login.
- Overview is first page after login.
- Feed matrix shows all 6 MVP feeds.
- Group wizard can create demo group and send test message.
- Signal detail shows event timeline.
- Delivery screen can retry retryable failure.
- Runtime-changing action writes `admin_activity_logs`.
- Five-minute usability checklist passes.
- Early skeleton is available by Milestone B.

## 6. Risks and notes

- Keep UI dense but clear; this is an operator cockpit, not marketing.
- Avoid making every DB table a menu item. Navigation follows user tasks.
- Server-rendered Jinja2 + HTMX is default to avoid frontend stack sprawl.
