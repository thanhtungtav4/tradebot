# Đợt 1: Khung metadata cách đánh + trang chọn cách đánh + auto-guide TradingView

Ngày: 2026-07-21
Trạng thái: Design đã duyệt, chờ review spec

## Bối cảnh

Bot hiện chạy kiến trúc server-side: TradingView chỉ gửi nến OHLCV qua webhook,
bot chạy chiến lược (`liquidity_sweep`) phía server, sinh signal, route tới group,
gửi Telegram. Chỉ có 1 chiến lược duy nhất.

User muốn: forex có nhiều "cách đánh"; cần bộ hướng dẫn cấu hình TradingView để
user tự chọn cách đánh từ menu và xem hướng dẫn tương ứng dễ dàng.

Quyết định định hướng (từ brainstorming):
- Hướng A (bot tính server-side) + self-service UI. Không dùng Pine Script.
- Phân rã thành nhiều đợt. **Đợt 1 (spec này)** chỉ làm khung + guide, dùng
  `liquidity_sweep` sẵn có làm ví dụ. Các cách đánh mới (Breakout, EMA
  Trend/Pullback, Scalping) làm ở các đợt sau, mỗi cái 1 spec riêng vì cần
  code detection + backtest cẩn thận (tín hiệu sai = user mất tiền).

## Vấn đề đợt 1 giải quyết

1. `BaseStrategy` không mô tả được "cách đánh này là gì, cần gì trên TradingView".
2. Trang guide hiện render alert từ mọi feed active, không gắn với cách đánh cụ thể.
3. User không có menu tự chọn cách đánh.

## Phạm vi

CHỈ đợt 1:
- Mở rộng metadata cho strategy (khai báo, không đổi logic detect).
- Service gom catalog strategy + alert TradingView cần tạo.
- Trang self-service "Chọn cách đánh" + auto-sinh guide per cách đánh.

NGOÀI phạm vi (đợt sau):
- Code detection cho Breakout / EMA Trend / Scalping.
- Thêm timeframe M1 vào enum (Scalping cần, làm khi code Scalping).
- Cache catalog, filter/search theo style, params tuỳ chỉnh per-user (đã có trong
  `GroupStrategySetting`).

## Kiến trúc — 3 phần

### Phần 1: Strategy metadata

Thêm field khai báo vào `BaseStrategy`, thuần metadata cho UI + guide:

```python
class BaseStrategy:
    code: str
    name: str
    required_timeframes: list[str]
    trigger_timeframes: list[str]
    # MỚI:
    tagline: str                    # 1 câu ngắn: "Quét thanh khoản đỉnh/đáy rồi đảo chiều"
    description: str                # đoạn giải thích dài, tiếng Việt dễ hiểu
    recommended_symbols: list[str]  # ["XAUUSD", "EURUSD"]
    style: str                      # "SWING" | "INTRADAY" | "SCALP"
```

`required_timeframes` đã cho biết cần gửi alert cho khung nào — guide tự suy ra,
không cần thêm field alert riêng.

`liquidity_sweep` điền metadata thật (VN, dễ hiểu). Đây là strategy ví dụ đầu tiên.

### Phần 2: Service `strategy_catalog(db)`

File mới `app/services/strategy_catalog.py`. Một hàm gom mọi strategy trong
registry kèm metadata + danh sách alert TradingView (suy từ
`required_timeframes` × `recommended_symbols`, tái dùng `tradingview_alert_json`
sẵn có trong `admin` service).

```python
def strategy_catalog(db) -> list[dict]:
    body_secret = get_settings().tradingview_body_secret
    out = []
    for strat in all_strategies():                 # từ registry
        alerts = [
            {"symbol": sym, "timeframe": tf,
             "json": tradingview_alert_json(body_secret, source_symbol_for(db, sym), tf)}
            for sym in strat.recommended_symbols
            for tf in strat.required_timeframes
        ]
        out.append({
            "code": strat.code, "name": strat.name, "tagline": strat.tagline,
            "description": strat.description, "style": strat.style,
            "recommended_symbols": strat.recommended_symbols,
            "required_timeframes": strat.required_timeframes,
            "alert_count": len(alerts), "alerts": alerts,
        })
    return out
```

Thay đổi kèm theo:
- `registry.py`: thêm `all_strategies() -> list[BaseStrategy]` (giờ chỉ có `get_strategy`).
- `source_symbol_for(db, canonical)`: map canonical → broker symbol qua
  `BrokerSymbolMapping` (đã có). Nếu không có mapping, fallback = canonical symbol.

### Phần 3: Trang `/admin/strategies-guide`

- Route GET, tái dùng `_render` + `require_session` như các route admin khác.
- Truyền `strategy_catalog(db)` vào template.
- Template mới `strategies_guide.html`:
  - Lưới card, mỗi cách đánh: tên + tagline + badge `style` + symbol khuyến nghị
    + "Cần tạo N cảnh báo".
  - Mỗi card mở chi tiết bằng `<details>` HTML thuần (không JS) → guide alert JSON
    per cách đánh, tái dùng markup nút Chép từ `guide.html`.
  - Link "Cấu hình cho group" → `/admin/strategies`.
- Thêm link menu ở sidebar (`base.html`).

## Kiểm thử

Một test: `strategy_catalog(db)` trả `liquidity_sweep` với metadata đúng và
`alert_count == len(recommended_symbols) * len(required_timeframes)`.

## File đụng tới

- `app/strategy/base.py` — thêm 4 field metadata
- `app/strategy/liquidity_sweep.py` — điền metadata
- `app/strategy/registry.py` — thêm `all_strategies()`
- `app/services/strategy_catalog.py` — mới
- `app/api/admin.py` — route mới
- `app/templates/admin/strategies_guide.html` — mới
- `app/templates/admin/base.html` — link sidebar
- `tests/test_strategy_catalog.py` — mới

## Lộ trình đợt sau (tham khảo, không làm ở đây)

Mỗi cách đánh 1 spec riêng: Breakout (phá vỡ range/hỗ trợ-kháng cự), EMA
Trend/Pullback (theo xu hướng EMA, vào khi hồi), Scalping (M1/M5, nhiều lệnh).
Mỗi cái = code detection + backtest + tune params, rồi chỉ cần điền metadata là
tự xuất hiện trong catalog + guide.
