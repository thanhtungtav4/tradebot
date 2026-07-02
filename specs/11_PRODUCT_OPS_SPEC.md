# 11_PRODUCT_OPS_SPEC - Product, PM, Operations

## 1. Problem statement

Bot gửi tín hiệu giao dịch vào nhiều nhóm Telegram cho user. Có ít nhất hai loại nhóm:

- Free group: nhận tín hiệu cơ bản, ít chi tiết hơn.
- VIP group: nhận tín hiệu đầy đủ gồm entry, SL, TP, RR, confidence, reason và invalid condition.

Hệ thống cần giúp admin cấu hình nhóm và strategy mà không sửa code, đồng thời giúp operator biết tín hiệu có được tạo, bị reject, route tới nhóm nào và gửi Telegram thành công hay thất bại.

## 2. Personas

### Admin tín hiệu

Nhu cầu:

- Thêm/sửa/tắt Telegram group.
- Gán strategy, symbol, timeframe cho từng group.
- Cấu hình free/VIP message mode.
- Test gửi message trước khi chạy group thật.
- Xem log signal và delivery.
- Nhìn dashboard trong 5 phút biết hệ thống đang chạy tốt hay lỗi ở đâu.

### User nhóm free

Nhu cầu:

- Nhận tín hiệu dễ hiểu.
- Không bị spam duplicate.
- Có cảnh báo quản lý vốn.

### User nhóm VIP

Nhu cầu:

- Nhận tín hiệu chi tiết hơn free group.
- Có entry, SL, TP, RR, lý do và điều kiện invalid.
- Tín hiệu gửi đúng thời điểm, không quá trễ sau bar close.

### Operator vận hành

Nhu cầu:

- Biết data feed có stale không.
- Biết Telegram bot còn gửi được không.
- Biết Redis/DB có lỗi không.
- Có playbook xử lý sự cố nhanh.

## 3. Non-goals

MVP không làm các việc sau:

- Không cam kết lợi nhuận.
- Không phải lời khuyên tài chính.
- Không auto-trade.
- Không đặt lệnh thật.
- Không quản lý position.
- Không dashboard admin hoàn chỉnh.
- Không AI/news/backtest production.

## 4. MVP KPIs

| KPI | Target MVP |
| --- | --- |
| Delivery latency | Dưới 30 giây từ lúc nhận bar close webhook đến lúc enqueue Telegram trong điều kiện bình thường |
| Duplicate rate | 0 duplicate message trong cùng cooldown window |
| Data feed stale detection | Health `DEGRADED` nếu thiếu candle mới quá ngưỡng stale theo timeframe (`timeframe + STALE_GRACE_MINUTES`) |
| Telegram delivery log coverage | 100% outbox row có status cuối hoặc retry state |
| Admin smoke test | Gửi được test message tới từng group demo |
| Signal auditability | Mỗi signal có event cho created/rejected/approved/routed/delivery |
| Admin comprehension | Operator mới dùng Admin Console trong 5 phút trả lời được bot OK hay lỗi ở đâu và bước xử lý tiếp theo |

## 5. Release criteria

Chỉ chuyển từ demo group sang group thật khi chạy ổn định.

Definition of "ổn định" cho MVP:

- Chạy tối thiểu 48 giờ trên môi trường staging/demo group.
- Không có duplicate message trong cooldown.
- Health không báo DB/Redis down.
- Data feed không stale ngoài sự cố TradingView/config đã biết.
- Telegram test và delivery thật đều có log rõ.
- Operator đã chạy qua playbook restart và recovery cơ bản.
- Operator đã pass checklist Admin Console 5 phút trong `12_ADMIN_CONSOLE_SPEC.md`.

## 6. Standard admin workflow

1. Mở Admin Console > Overview để xác nhận DB/Redis/data feed/Telegram đều OK hoặc biết lỗi nào cần xử lý.
2. Vào Groups > Add group để tạo Telegram group.
3. Add bot vào group và copy chat id vào form.
4. Bấm Test message trong UI và xác nhận group nhận được tin.
5. Vào group detail > Strategy settings để gán strategy, symbols, timeframes, confidence, cooldown và send mode.
6. Bật group ở chế độ demo/internal trước.
7. Theo dõi Overview, Signals và Deliveries trong ít nhất một phiên thị trường.
8. Khi ổn định theo release criteria, chuyển group sang live.

## 7. Ops playbook

### Data feed stale

Triệu chứng:

- `/api/v1/health` báo `dataFeed: DEGRADED`.
- Không có candle mới cho symbol/timeframe active.

Kiểm tra:

- TradingView alert còn active không.
- Webhook URL đúng không.
- TradingView webhook token/body secret có đổi không.
- Logs có `tradingview_bar_received` gần đây không.

Xử lý:

- Gửi lại test webhook nếu có tool local.
- Tạm tắt group nếu data thiếu kéo dài.
- Không tự tạo candle giả trong production.

### Telegram bot bị kick hoặc mất quyền

Triệu chứng:

- Telegram send trả 400/403.
- Delivery status `FAILED_PERMANENT`.

Xử lý:

- Add bot lại vào group.
- Kiểm tra bot có quyền gửi message.
- Gọi test message endpoint.
- Nếu chat id đổi, update `telegram_groups.telegram_chat_id`.

### Redis down

Triệu chứng:

- Worker không nhận job.
- Health `redis: DOWN`.

Xử lý:

- Restart Redis.
- Restart workers sau khi Redis ổn.
- Kiểm tra pending outbox và queue depth.

### DB full hoặc DB down

Triệu chứng:

- API/worker lỗi insert/update.
- Health `db: DOWN`.

Xử lý:

- Kiểm tra disk.
- Dọn log/export cũ nếu cần.
- Restore service DB.
- Không gửi Telegram nếu signal không lưu được audit.

### VPS restart

Xử lý:

- Start DB/Redis.
- Start API.
- Start workers.
- Verify `/api/v1/health`.
- Gửi test Telegram.
- Kiểm tra outbox pending/retry.

### MT5 mất kết nối future

Áp dụng khi thêm MT5 connector:

- Kiểm tra Windows VPS còn online.
- Kiểm tra MT5 terminal đang mở và đã login.
- Kiểm tra broker server connected.
- Kiểm tra symbol mapping.
- Nếu MT5 stale nhưng TradingView còn hoạt động, có thể tiếp tục chạy TradingView-only theo config.

## 8. Acceptance criteria

- Spec mô tả rõ bot phục vụ free/VIP Telegram users.
- Non-goals xuất hiện trong master spec và product ops spec.
- KPI MVP có threshold cụ thể.
- Release criteria định nghĩa "chạy ổn định" trước khi vào group thật.
- Có playbook cho data feed stale, Telegram bot issue, Redis down, DB down, VPS restart và MT5 future.
- Có Admin Console đủ trực quan để operator mới hiểu trạng thái vận hành trong 5 phút.
