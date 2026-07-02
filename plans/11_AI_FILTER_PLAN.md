# 11_AI_FILTER_PLAN - AI Filter (Phase Future D)

> **Status**: Future phase. Tài liệu này là khuyến nghị (recommendations) cho phase sau khi MVP đã chạy ổn định với rule-based strategy (Liquidity Sweep) và pipeline Telegram đã green. Không implement trong MVP.

## 1. Mục tiêu

Bổ sung một lớp AI filter chạy **giữa** risk pre-check và risk final check để:

- Đánh giá lại tính hợp lý của một `SignalCandidate` đã pass risk pre-check.
- Điều chỉnh `confidence` cuối cùng (tăng/giảm trong một khoảng cho phép).
- Thêm `riskNote` (ghi chú quản lý vốn) và `telegramReason` (lý do ngắn gọn để hiển thị cho user) bằng ngôn ngữ tự nhiên tiếng Việt.
- **Tuyệt đối không** tự tạo BUY/SELL, không sửa giá entry/SL/TP, không tạo TP mới.

AI filter phải là **additive**: nếu AI bị lỗi, fail, timeout, hoặc bị admin tắt, pipeline phải chạy tiếp như cũ. Đây là khuyến nghị cứng từ spec `10_FUTURE_PHASES_SPEC §2`.

## 2. Spec nguồn

- `specs/10_FUTURE_PHASES_SPEC.md` (§2 AI filter, §9 acceptance criteria)
- `specs/04_SIGNAL_RISK_SPEC.md` (để hiểu risk pre-check và risk final check)
- `plans/04_STRATEGY_RISK_PLAN.md` (để thấy risk manager + duplicate guard hiện tại)
- `plans/05_ROUTER_TELEGRAM_PLAN.md` (để biết router lấy field nào để format)
- `specs/09_MONITORING_TEST_SPEC.md` (event schema cho log/audit)

## 3. Vị trí trong pipeline

Pipeline hiện tại (Milestone C + D):

```text
candles -> LiquiditySweepStrategy.detect
        -> SignalCandidate
        -> check_risk (pre-check)
        -> build_signal_uid
        -> insert signals row (APPROVED | REJECTED)
        -> route_signal -> outbox -> send_telegram
```

Pipeline đề xuất khi có AI filter (chèn giữa pre-check và final check):

```text
candles -> LiquiditySweepStrategy.detect
        -> SignalCandidate
        -> check_risk (pre-check)
        -> AI filter (opt-in theo group/strategy)        <-- MỚI
        -> Risk final check (chỉ kiểm tra cap confidence) <-- TINH CHỈNH
        -> build_signal_uid (giữ nguyên hoặc thêm suffix)
        -> insert signals row (APPROVED | REJECTED)
        -> route_signal -> outbox -> send_telegram
```

Lưu ý: `signal_uid` phải **không phụ thuộc** vào AI output, nếu không duplicate guard sẽ sai khi AI tăng/giảm confidence. Bucket entry giữ nguyên công thức hiện tại.

## 4. Nguyên tắc bất biến (invariants)

1. AI filter **chỉ chạy** khi admin đã bật tường minh theo `(group_strategy_setting_id)` hoặc theo strategy code. Mặc định **tắt**.
2. AI output **chỉ được phép**:
   - `validSignal: true | false` (false -> reject với `reject_code=AI_REJECTED`)
   - `confidenceAdjustment: -20..+20` (int, clamp; spec cho phép điều chỉnh, không bắt buộc trần cứng — khuyến nghị ±20 để tránh AI lật đảo rule)
   - `finalConfidence: 0..100` (int; nếu thiếu, server tự tính `min(100, max(0, base + adjustment))`)
   - `riskNote: str` (≤ 280 ký tự, tiếng Việt, không chứa ký tự điều khiển)
   - `telegramReason: str` (≤ 200 ký tự, tiếng Việt, có thể dùng trong BASIC/FULL message)
3. AI **không được**:
   - Đặt `action`, `entry`, `sl`, `tp[]`, `risk_reward`, `invalid_if`, `reason[]` (rule engine là authoritative).
   - Trả `validSignal=true` khi thiếu data (vd thiếu context H1).
   - Trả `confidenceAdjustment` có magnitude > `abs(preFilterConfidence - 100)` hoặc > 20, tùy theo giá trị nào nhỏ hơn.
4. Khi AI lỗi / timeout / trả payload sai schema:

## 5. Artifacts cần tạo khi implement

### 5.1 Code mới

- `app/services/ai_filter.py`:
  - `interface AIReviewer` (Protocol) với method `review(candidate, ctx) -> AIReviewResult`.
  - `AIReviewResult` dataclass (khớp JSON schema spec §2: `validSignal`, `confidenceAdjustment`, `finalConfidence`, `riskNote`, `telegramReason`).
  - `LLMReviewer` (default impl): gọi LLM HTTP API (vd OpenAI-compatible), parse JSON, validate schema bằng pydantic model `AISignalReview`.
  - `LocalHeuristicReviewer` (fallback, không cần external API): chỉ tinh chỉnh confidence dựa trên session/volatility; useful cho dev và offline.
  - `PassthroughReviewer` (khi bị tắt): trả về `validSignal=True`, adjustment=0, note/reason=None.
  - `safe_review(candidate, ctx, timeout)` wrapper: catch exception, clamp values, emit log event.
- `app/schemas/ai_filter.py`:
  - `AISignalReview` (pydantic BaseModel) với validators:
    - `confidenceAdjustment: conint(ge=-20, le=20)`
    - `finalConfidence: conint(ge=0, le=100)`
    - `riskNote: constr(max_length=280)`
    - `telegramReason: constr(max_length=200)`
- `app/services/strategy_runner.py` chỉnh sửa nhỏ:
  - Sau khi `check_risk(...)` trả None, gọi `ai_filter.safe_review(...)` nếu setting có `ai_filter_enabled=True`.
  - Lưu AI output vào `signals.metadata` (JSONB) hoặc bảng mới `signal_ai_reviews` (khuyến nghị bảng mới — xem 5.3).
- `app/workers.py`:
  - Không cần thêm job mới; AI filter chạy inline trong `run_strategy` (latency budget quan trọng — xem §6).
  - Có thể tách thành job riêng nếu latency quá cao (khuyến nghị phase 2).

### 5.2 Settings

- `app/config/settings.py` thêm:
  - `ai_filter_enabled: bool = False` (global kill-switch).

### 5.3 Database (khuyến nghị bảng mới)

Mở rộng `plans/01_FOUNDATION_DATABASE_PLAN.md` với bảng `signal_ai_reviews`:

```text
signal_ai_reviews
  id                BIGINT PK
  signal_id         BIGINT FK signals(id) ON DELETE CASCADE
  provider          TEXT  (off | passthrough | llm | heuristic)
  model             TEXT  NULL
  raw_input_hash    TEXT  (sha256 của prompt, để trace; không log full prompt)
  raw_output        JSONB
  valid_signal      BOOLEAN
  confidence_adjustment INT
  final_confidence  INT
  risk_note         TEXT NULL
  telegram_reason   TEXT NULL
  latency_ms        INT
  error_code        TEXT NULL  (TIMEOUT | SCHEMA_INVALID | PROVIDER_DOWN | ...)
  created_at        TIMESTAMPTZ
  request_id        TEXT
```

- Index: `(signal_id)`, `(provider, created_at DESC)`.
- Không lưu `raw_output` nếu chứa giá user/PII; chỉ lưu JSON review (đã strip).
- Audit-friendly: mỗi lần review 1 lần, nếu muốn A/B nhiều model thì tạo nhiều row.

### 5.4 Migrations & seed

- `migrations/versions/xxxx_add_signal_ai_reviews.py`:

## 7. Logging & metrics

Mở rộng `specs/09_MONITORING_TEST_SPEC §2/§3` với:

- Event: `ai_review_requested`, `ai_review_completed`, `ai_review_failed`, `ai_review_skipped_off`, `ai_review_skipped_passthrough`.
- Log fields: `signalId`, `provider`, `model`, `latencyMs`, `confidenceBefore`, `confidenceAfter`, `delta`, `requestId`.
- Counters:
  - `ai_review_total{provider,outcome}`
  - `ai_review_latency_seconds` (histogram sau, MVP log per-signal value).
  - `ai_review_confidence_delta` (lưu distribution để phát hiện AI lệch).
- Audit: `signal_events.event_type='AI_REVIEWED'` với `details={provider, finalConfidence, delta, riskNote, telegramReason}`.

## 8. Tests (khuyến nghị khi implement)

### 8.1 Unit tests (`tests/test_ai_filter.py`)

- Schema validate: input JSON sai (vd `confidenceAdjustment=100`) -> ValidationError.
- `LLMReviewer.review` với httpx mock trả payload hợp lệ -> parse đúng.
- `LLMReviewer.review` với timeout -> trả `PassthroughReviewer`-equivalent, log error.
- `LLMReviewer.review` với provider 5xx -> passthrough, log error.
- `safe_review` clamp: `finalConfidence=150` -> về 100; `-30` -> 0.
- `safe_review` clamp delta: `confidenceAdjustment=50` -> về 20.
- `PassthroughReviewer` không gọi network.
- `LocalHeuristicReviewer` deterministic (cùng input -> cùng output).

### 8.2 Integration tests (`tests/test_ai_filter_integration.py`, marker `integration`)


## 9. Acceptance criteria (gate trước khi release phase D)

- Bật `ai_filter_enabled=True` ở 1 group, chạy 48h, **không** xuất hiện regression: số signal APPROVED, duplicate rate, latency, error rate Telegram không tệ hơn baseline > 5%.
- `ai_review_failed` rate < 1% trong 48h (nếu > 1%, tự động fallback off và cảnh báo).
- Bảng `signal_ai_reviews` không phình quá 1GB trong 7 ngày (có retention script trong `plans/07_HEALTH_MONITORING_OPS_PLAN.md` — khuyến nghị thêm maintenance job `prune_ai_reviews`).
- Mỗi signal có event `AI_REVIEWED` (khi bật) hoặc `AI_REVIEW_SKIPPED` (khi tắt). Không có signal APPROVED nào "im lặng" qua AI.
- Có runbook: "AI filter tăng false reject", "AI filter tăng confidence quá mức", "AI provider down".

## 10. Roll-out plan đề xuất

1. **Stage 0 (dev)**: triển khai code, chạy unit + integration, smoke off. Không expose cho group nào.
2. **Stage 1 (canary internal)**: bật `ai_filter_enabled=True` ở `INTERNAL` group (nếu có), `provider=passthrough` trước (chỉ để test wiring).
3. **Stage 2 (canary heuristic)**: đổi sang `provider=heuristic` ở 1 group VIP. So sánh distribution confidence trước/sau.
4. **Stage 3 (canary llm)**: đổi sang `provider=llm` ở 1 group VIP. Theo dõi 7 ngày, review log `ai_review_failed` và confidence delta.
5. **Stage 4 (rollout)**: bật cho các group còn lại. Vẫn giữ kill-switch global (`ai_filter_enabled=False`) để tắt trong vài giây nếu cần.

- Setup: group strategy setting `ai_filter_enabled=True`, provider=`passthrough` -> end-to-end pipeline (webhook -> signal -> outbox) không thay đổi gì so với MVP không có AI.

## 11. Risks & notes

- **AI non-determinism**: cùng input, output khác nhau -> audit phải lưu raw output để debug, nhưng tránh log ra stdout để không leak PII. Có `raw_input_hash` để trace.
- **Latency creep**: LLM thường 300-1500ms, có thể spike 5s+ khi provider chậm. Luôn cap timeout, luôn fallback passthrough.
- **Cost**: LLM cost per signal có thể tăng nhanh với M15 cadence (3 symbols x ~250 bars/ngày x group). Khuyến nghị: gate AI filter chỉ cho 1-2 group ở stage 3, đo cost trước khi rollout.
- **Prompt injection từ data**: nếu cho LLM thấy raw payload, kẻ tấn công kiểm soát TradingView alert có thể inject text vào `reason`/`invalid_if` rồi qua AI. Khuyến nghị: AI input chỉ gồm numeric candles + rule decision, không cho raw text fields.
- **Hallucinated prices**: enforce schema nghiêm; reject nếu AI cố trả field không thuộc schema. Mọi field ngoài schema -> passthrough + log.
- **Failure mode phải fail-safe**: mọi lỗi -> passthrough. Không bao giờ `validSignal=false` mặc định khi timeout; mặc định = tin rule engine.
- **Không chạm LiquiditySweepStrategy**: AI filter là wrapper ngoài, không phải strategy mới. Đảm bảo `BaseStrategy` interface nguyên vẹn.
- **Không sửa Router**: AI output đi vào `signals.metadata` + `signal_ai_reviews`, router vẫn đọc `signals.confidence` đã final.

## 12. Open questions cần user/PM quyết trước khi code

- `confidenceAdjustment` cap nên là ±20 (đề xuất) hay ±10 (bảo thủ hơn)?
- Có cần AI cho `FREE` group không, hay chỉ VIP/SMC?
- Có cần A/B test 2 model cùng lúc không? Nếu có, schema `signal_ai_reviews` cần `experiment_tag`.
- LLM provider chính thức là gì? (OpenAI, Anthropic, self-host, local Ollama?) Quyết định này ảnh hưởng `ai_filter_api_url`, prompt format, cost.
- Retention: giữ `signal_ai_reviews` bao lâu? Đề xuất 30 ngày, prune job chạy daily.

## 13. Cross-references

- Update `00_MASTER_PLAN.md` mục "Plan con" thêm dòng 11.
- Update `09_FUTURE_PHASES_PLAN.md` mục "Phase Future D" tham chiếu file này và ngược lại (single source of truth).
- Update `08_TEST_RELEASE_PLAN.md` mục "MVP acceptance checklist" thêm dòng kiểm tra `ai_filter` ở chế độ off mặc định (chỉ smoke, không gate release).

- Setup: provider=`llm` với mock httpx trả `validSignal=false` -> signal status=`REJECTED`, reject_code=`AI_REJECTED`, có `signal_event` `AI_REVIEWED`.
- Setup: provider=`llm` trả delta +10 -> `signals.confidence` = base+10 (clamp nếu cần); `signal_ai_reviews` có 1 row.
- Setup: provider lỗi 100% -> signal vẫn APPROVED, có event `AI_REVIEW_FAILED`, không outbox bị mất.

### 8.3 Smoke test (`scripts/smoke.py`)

- Thêm bước "AI filter off" (default) vào happy path, đảm bảo smoke vẫn pass không cần API key.
- Nếu env có `AI_FILTER_API_KEY`, smoke có thể bật ở chế độ `--with-ai` (chỉ log, không assert AI quyết định đúng — output LLM không deterministic).

  - Tạo bảng, indexes, FK.
- `app/seed.py`:
  - Không seed AI provider mặc định (vì mặc định `provider="off"`). Phase sau có thể thêm 1 row vào bảng config mới nếu cần.
  - Group strategy setting thêm cột `ai_filter_enabled BOOLEAN NOT NULL DEFAULT FALSE`.

### 5.5 Admin Console (phase 2)

- Overview: thêm tile "AI filter" với status (OK nếu passthrough, DEGRADED nếu provider lỗi >5% trong 1h, OFF nếu disabled).
- Signals detail: hiển thị `riskNote` và `telegramReason` (nếu có).
- Settings: bật/tắt AI filter per group strategy, đổi provider, đổi model (an toàn vì chỉ tác động lần review sau).
- Runbook: thêm scenario "AI filter down" trong `operator_runbook` của `app/services/admin.py`.

## 6. Latency budget & placement

KPI MVP: `<30s` từ `tradingview_bar_received` đến enqueue Telegram (`specs/11 §4`, `specs/09 §3`).

Khuyến nghị:

- AI filter gọi **inline trong `run_strategy`**, không tạo job mới (giữ đơn giản, không phải track job state mới).
- Timeout `1500ms` là mặc định; nếu timeout, passthrough (giữ rule result).
- Nếu trong tương lai LLM latency > 1.5s, tách thành job `run_ai_review` chạy trên queue `signal` (giữa pre-check và route) — cần thêm `signals.status='AI_PENDING'` tạm thời, đảm bảo worker claim tương tự outbox.
- Luôn log `ai_filter_latency_ms` để sau này quyết định inline vs async.

  - `ai_filter_provider: Literal["off", "passthrough", "llm", "heuristic"] = "off"`.
  - `ai_filter_timeout_ms: int = 1500` (khuyến nghị 1.5s, không vượt latency budget 30s).
  - `ai_filter_max_confidence_delta: int = 20` (cap để AI không lật đảo rule).
  - `ai_filter_api_url: str | None = None` (vd `https://api.openai.com/v1/chat/completions`).
  - `ai_filter_api_key_ref: str = "AI_FILTER_API_KEY"` (chỉ lưu ref, secret đọc từ env, không log).
  - `ai_filter_model: str = "gpt-4o-mini"` (hoặc model tương đương; phải support JSON mode / structured output).
- Validate: nếu `ai_filter_provider="llm"` mà thiếu `ai_filter_api_url` hoặc `ai_filter_api_key_ref` không có env -> fail startup (giống pattern settings khác của dự án).

   - Log `ai_filter_failed` với reason.
   - Bỏ qua output, dùng rule engine result làm final.
   - Không retry vô hạn — tối đa 1 lần fallback.
