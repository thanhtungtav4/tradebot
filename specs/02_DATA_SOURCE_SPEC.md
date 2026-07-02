# 02_DATA_SOURCE_SPEC - Data Sources

## 1. Mục tiêu

Chuẩn hóa mọi nguồn dữ liệu về cùng candle contract để strategy không phụ thuộc nguồn data. MVP dùng TradingView bar webhook để nhận nến đã đóng; MT5 và MT4 giữ làm extension.

## 2. Source priority

| Phase | Source | Role |
| --- | --- | --- |
| MVP | TradingView Bar Webhook | Nguồn candle chính để backend tự phân tích |
| Future | MT5 | Nguồn candle/tick từ broker terminal |
| Future | TradingView Signal Webhook | Alert/confirmation/external signal |
| Future | MT4 EA Bridge | Candle/tick từ terminal MT4 |
| Future | OANDA/other | Adapter mới nếu cần |

## 3. Canonical candle model

Mọi candle lưu và truyền nội bộ theo shape:

```json
{
  "source": "TRADINGVIEW",
  "broker": "TRADINGVIEW",
  "accountId": null,
  "symbol": "XAUUSD",
  "brokerSymbol": "OANDA:XAUUSD",
  "timeframe": "M15",
  "candleTime": "2026-06-30T10:15:00Z",
  "open": "2320.50",
  "high": "2328.10",
  "low": "2318.20",
  "close": "2325.70",
  "volume": "1200",
  "spread": "18",
  "isClosed": true
}
```

Quy tắc:

- `symbol` là canonical symbol dùng trong strategy và routing.
- `brokerSymbol` là symbol thật của data source, ví dụ `OANDA:XAUUSD` trên TradingView hoặc `XAUUSDm` trên MT5.
- `candleTime` là thời điểm mở nến, lưu UTC.
- Strategy chỉ được dùng candle `isClosed=true`.
- Decimal nên dùng string hoặc Decimal trong code, không dùng float cho DB write.

## 4. Data source interfaces

MVP TradingView webhook không phải pull API. Nó là push-based ingestor:

```python
class CandleIngestor:
    source_code: str

    def normalize_bar_payload(self, payload: dict) -> CanonicalCandle:
        raise NotImplementedError
```

Pull-based source future như MT5 dùng adapter:

```python
class MarketDataAdapter:
    source_code: str

    def get_candles(self, symbol: str, timeframe: str, limit: int) -> list[CanonicalCandle]:
        raise NotImplementedError

    def get_tick(self, symbol: str) -> CanonicalTick:
        raise NotImplementedError

    def health_check(self) -> DataSourceHealth:
        raise NotImplementedError
```

Adapter không được trả dữ liệu broker-specific ra ngoài boundary nếu chưa normalize.

## 5. TradingView bar webhook v1

TradingView alert phải chạy `once per bar close` cho từng symbol/timeframe active. Pine Script không quyết định BUY/SELL trong MVP; nó chỉ gửi OHLCV bar để backend Python tự phân tích.

Endpoint (token trong path vì TradingView không ký HMAC được, xem `08 §4a`):

```http
POST /api/v1/webhooks/tradingview/bars/{webhook_token}
```

TradingView alert **không** set custom header được, nên auth dựa vào `webhook_token` trong URL + `secret` trong body + IP allowlist. Không dùng `X-Signature`/`X-Timestamp` cho TradingView.

Payload (Pine Script alert message, JSON):

```json
{
  "source": "TRADINGVIEW",
  "secret": "<body_secret>",
  "symbol": "{{ticker}}",
  "timeframe": "{{interval}}",
  "time": "{{time}}",
  "open": "{{open}}",
  "high": "{{high}}",
  "low": "{{low}}",
  "close": "{{close}}",
  "volume": "{{volume}}",
  "isClosed": true
}
```

`{{interval}}` TradingView trả dạng số (`"15"`, `"60"`) — map sang canonical timeframe qua bảng ở `§7a`. `{{ticker}}` map qua `broker_symbol_mappings` (reverse lookup từ broker symbol).

### Pine Script alert setup

Alert config bắt buộc:

- Condition: `Once Per Bar Close`.
- Webhook URL: `https://<host>/api/v1/webhooks/tradingview/bars/<webhook_token>`.
- Message: JSON ở trên với placeholder TradingView (`{{ticker}}`, `{{interval}}`, `{{time}}`, `{{open}}`...). `secret` điền giá trị `body_secret` thật.
- Một alert riêng cho mỗi symbol × timeframe active (MVP: 3 × 2 = 6 alert).

Validation:

- `source` must be `TRADINGVIEW`.
- `symbol` must map to active canonical symbol.
- `timeframe` must map to active canonical timeframe.
- OHLC must be numeric and valid: `high >= max(open, close)`, `low <= min(open, close)`.
- `isClosed` must be true.
- Timestamp must be UTC or parseable into UTC.

### Spread không có trong TradingView bar webhook

Payload TradingView bar **không cấp spread**. Quy tắc MVP:

- `spread` payload optional. Nếu thiếu, lưu `market_candles.spread = NULL`.
- Spread filter (xem `04_SIGNAL_RISK_SPEC.md §3`) **skip** khi spread không có (null), không reject. MVP TradingView-only chấp nhận không lọc spread.
- Phase MT5/MT4 sẽ cấp spread thật từ tick/rates; lúc đó filter mới active.

Pine Script có thể optionally gửi `spread` nếu chart cung cấp; nếu có, vẫn validate numeric và áp filter.

## 6. MT5 adapter future

Nhiệm vụ:

- Initialize MT5 terminal.
- Kiểm tra terminal connected, account authorized.
- Resolve canonical symbol sang broker symbol.
- Lấy candles theo timeframe.
- Loại bỏ nến đang chạy.
- Lấy spread từ tick hoặc rates nếu có.
- Upsert candles vào DB.
- Log lỗi theo source/broker/symbol/timeframe.

Timeframe mapping:

| Canonical | MT5 constant |
| --- | --- |
| `M5` | `TIMEFRAME_M5` |
| `M15` | `TIMEFRAME_M15` |
| `H1` | `TIMEFRAME_H1` |
| `H4` | `TIMEFRAME_H4` |

Future active timeframes: `M15`, `H1`.

## 7. Symbol mapping

Table `broker_symbol_mappings` là nguồn truth.

Ví dụ:

| broker | canonical_symbol | broker_symbol | enabled |
| --- | --- | --- | --- |
| `TRADINGVIEW` | `XAUUSD` | `OANDA:XAUUSD` | true |
| `TRADINGVIEW` | `EURUSD` | `OANDA:EURUSD` | true |
| `TRADINGVIEW` | `GBPUSD` | `OANDA:GBPUSD` | true |

Nếu mapping không tồn tại hoặc disabled, ingest job phải fail rõ với `SYMBOL_MAPPING_NOT_FOUND`, không tự đoán.

## 7a. Timeframe registry

Canonical timeframe là enum cố định trong code, không lấy từ user input:

| Canonical | Phút | TradingView `{{interval}}` | MT5 constant | MVP active |
| --- | --- | --- | --- | --- |
| `M5` | 5 | `5` | `TIMEFRAME_M5` | no |
| `M15` | 15 | `15` | `TIMEFRAME_M15` | yes |
| `H1` | 60 | `60` | `TIMEFRAME_H1` | yes |
| `H4` | 240 | `240` | `TIMEFRAME_H4` | no |

Quy tắc:

- TradingView gửi `{{interval}}` dạng số (`"15"`, `"60"`), không phải `"M15"`. Ingest phải map số → canonical qua cột này. Số không có trong bảng → reject `TIMEFRAME_NOT_SUPPORTED`.
- `timeframe_minutes` dùng để tính stale threshold (`§9`) và lookback window.
- Active timeframe (MVP: M15, H1) lấy từ config/`symbol_settings`, không hardcode rải rác.

## 8. Closed-candle rule

TradingView alert phải cấu hình `once per bar close`. Backend vẫn validate timestamp và timeframe để tránh payload sai.

Ingest job phải:

- Reject payload `isClosed=false` với code `CANDLE_NOT_CLOSED`.
- Reject candle có `candle_time` ở tương lai quá `FUTURE_CANDLE_BUFFER_SECONDS` (default 120s, chống lệch clock nhẹ) với code `CANDLE_IN_FUTURE`. Buffer này độc lập với timestamp drift của HMAC webhook future (`07`, 300s) vì đo `candle_time` chứ không phải thời điểm gửi.
- Chỉ enqueue strategy khi upsert được candle mới đã đóng và timeframe là trigger timeframe của ít nhất một active strategy. Với Liquidity Sweep v1, `M15` enqueue strategy; `H1` chỉ cập nhật context/feed freshness.

## 9. Backfill and gap handling

TradingView webhook không phải historical data API. Nếu webhook bị mất trong 20 phút, backend không tự lấp được lịch sử từ TradingView. MVP phải:

- Lưu `last_candle_time` theo source/symbol/timeframe.
- Health `DEGRADED` nếu thiếu candle mới quá ngưỡng stale **theo timeframe** (xem dưới).
- Log `data_feed_stale`.

Stale threshold theo timeframe = `timeframe_minutes + STALE_GRACE_MINUTES`. Mặc định `STALE_GRACE_MINUTES = 20`:

| Timeframe | Bar phút | Stale sau |
| --- | --- | --- |
| M15 | 15 | 35 phút |
| H1 | 60 | 80 phút |

Env chính là `STALE_GRACE_MINUTES`. Nếu code cần hỗ trợ legacy alias `DATA_FEED_STALE_AFTER_MINUTES`, alias đó phải được diễn giải như grace minutes, không phải hằng số stale tuyệt đối. Lý do: nến H1 60 phút mới đóng một lần, dùng 20m cố định sẽ báo stale sai.
- Cho phép admin replay fake/test candle trong local test.

Backfill thật sẽ được xử lý ở phase MT5 hoặc data provider khác.

### Cold-start warmup

Bot mới deploy chưa có history. Strategy cần lookback (xem `03_STRATEGY_ENGINE_SPEC.md §3a`). Cho tới khi tích đủ candle:

- Ingest vẫn upsert candle bình thường, không reject vì thiếu history.
- Strategy enqueue vẫn chạy cho trigger timeframe, nhưng context builder tạo signal `REJECTED` với `INSUFFICIENT_HISTORY` nếu chưa đủ lookback (không phải lỗi, là warmup).
- Admin Console Feeds hiển thị warmup state riêng: `WARMUP` thay vì `STALE` khi candle mới về nhưng chưa đủ lookback. `WARMUP` là trạng thái hợp lệ trong `data_source_feeds.status`.

MVP warmup options (chọn 1, mặc định option B):

- Option A: chấp nhận chờ tự tích đủ candle qua webhook (XAUUSD M15 ~ 5h, H1 lookback giảm xuống còn EMA50/EMA20 thay vì EMA200 — xem `03 §5`).
- Option B (default): admin import history một lần qua endpoint local/staging `POST /api/v1/admin/candles/import` (CSV/JSON OHLCV đã đóng). Endpoint này chỉ bật ở `local`/`staging`, ghi qua cùng candle normalizer, không bypass closed-candle rule. Production không mở endpoint này.

Import payload phải validate như webhook candle (OHLC valid, isClosed=true, symbol mapping tồn tại) và đi qua upsert idempotent.

## 10. MT4 bridge future

MT4 không kết nối trực tiếp như MT5. Future phase dùng EA MQL4:

```text
MT4 EA -> POST /api/v1/bridge/mt4/candles -> normalize -> DB
```

Payload phải có HMAC header, account id, broker, broker symbol, timeframe, candle fields và terminal timestamp.

## 11. TradingView signal future

TradingView không là data API chính. Future phase dùng:

- External signal.
- Strategy confirmation.
- Backup alert.

Endpoint tương lai:

```http
POST /api/v1/webhooks/tradingview
```

Payload phải validate `strategyCode`, `symbol`, `timeframe`, `action`, optional price fields. Không cho TradingView ghi trực tiếp vào `market_candles`.

## 12. Acceptance criteria

- TradingView bar webhook normalize thành `CanonicalCandle`.
- Ingest job không lưu nến chưa đóng.
- Missing symbol mapping fail rõ, không fallback lặng lẽ.
- Duplicate candle upsert không tạo bản ghi trùng.
- Strategy test có thể chạy hoàn toàn bằng fake candles.
- Health báo degraded khi data feed stale.
