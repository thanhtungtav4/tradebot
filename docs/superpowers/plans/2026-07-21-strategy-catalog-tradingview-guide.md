# Strategy Catalog + Auto-Guide TradingView — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho user tự chọn "cách đánh" từ menu và xem hướng dẫn cấu hình TradingView tương ứng, dựa trên metadata khai báo trên mỗi strategy.

**Architecture:** Mở rộng `BaseStrategy` với 4 field metadata (khai báo, không đổi logic detect). Service `strategy_catalog` gom mọi strategy trong registry + suy ra danh sách alert TradingView cần tạo (required_timeframes × recommended_symbols). Trang admin mới render catalog thành card + chi tiết guide bằng HTML thuần.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Jinja2, Tailwind/daisyUI, pytest, Postgres test DB (fixture `db`).

---

## File Structure

- `app/strategy/base.py` — thêm 4 field metadata vào `BaseStrategy`
- `app/strategy/liquidity_sweep.py` — điền metadata cho strategy ví dụ
- `app/strategy/registry.py` — thêm `all_strategies()`
- `app/services/strategy_catalog.py` — MỚI: hàm `strategy_catalog(db)` + `source_symbol_for(db, canonical)`
- `app/api/admin.py` — MỚI: route GET `/admin/strategies-guide`
- `app/templates/admin/strategies_guide.html` — MỚI: trang menu + guide
- `app/templates/admin/base.html` — thêm link sidebar
- `tests/test_strategy_catalog.py` — MỚI: test catalog

---

## Task 1: Metadata field trên BaseStrategy + liquidity_sweep

**Files:**
- Modify: `app/strategy/base.py`
- Modify: `app/strategy/liquidity_sweep.py:30-35`

- [ ] **Step 1: Thêm field metadata vào BaseStrategy**

`app/strategy/base.py` — thêm 4 annotation sau `trigger_timeframes`:

```python
"""Strategy plugin interface (03 §2)."""

from app.strategy.types import SignalCandidate, StrategyContext


class BaseStrategy:
    code: str
    name: str
    required_timeframes: list[str]
    trigger_timeframes: list[str]
    # Metadata cho UI catalog + auto-guide TradingView (đợt 1).
    tagline: str
    description: str
    recommended_symbols: list[str]
    style: str  # "SWING" | "INTRADAY" | "SCALP"

    def detect(self, context: StrategyContext) -> list[SignalCandidate]:
        raise NotImplementedError

    def lookback(self, timeframe: str) -> int:
        """Minimum closed candles required for the given timeframe."""
        raise NotImplementedError
```

- [ ] **Step 2: Điền metadata cho LiquiditySweepStrategy**

`app/strategy/liquidity_sweep.py` — thêm 4 class attribute ngay sau `trigger_timeframes = ["M15"]`:

```python
class LiquiditySweepStrategy(BaseStrategy):
    code = "liquidity_sweep"
    name = "Liquidity Sweep"
    required_timeframes = ["M15", "H1"]
    trigger_timeframes = ["M15"]
    tagline = "Quét thanh khoản đỉnh/đáy rồi vào lệnh đảo chiều"
    description = (
        "Chiến lược này chờ giá quét qua đỉnh hoặc đáy gần nhất (nơi tập trung "
        "lệnh chờ), rồi đóng nến ngược lại. Khi có nến xác nhận, bot vào lệnh "
        "theo hướng đảo chiều với điểm dừng lỗ ngay sau vùng quét. Hợp với vàng "
        "và các cặp chính, khung M15 (bot đọc thêm H1 để xác định xu hướng)."
    )
    recommended_symbols = ["XAUUSD", "EURUSD"]
    style = "INTRADAY"
```

- [ ] **Step 3: Chạy test hiện có để chắc không vỡ**

Run: `.venv/bin/python -m pytest tests/test_strategy.py tests/test_strategy_persistence.py -q`
Expected: PASS (metadata thuần khai báo, không đổi detect).

- [ ] **Step 4: Commit**

```bash
git add app/strategy/base.py app/strategy/liquidity_sweep.py
git commit -m "feat(strategy): thêm metadata catalog (tagline/description/symbols/style)"
```

---

## Task 2: registry.all_strategies()

**Files:**
- Modify: `app/strategy/registry.py`
- Test: `tests/test_strategy_catalog.py`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_strategy_catalog.py`:

```python
from app.strategy.registry import all_strategies, get_strategy


def test_all_strategies_returns_registry_instances():
    strats = all_strategies()
    assert len(strats) >= 1
    codes = {s.code for s in strats}
    assert "liquidity_sweep" in codes
    # cùng instance như get_strategy
    assert get_strategy("liquidity_sweep") in strats
```

- [ ] **Step 2: Chạy test cho thất bại**

Run: `.venv/bin/python -m pytest tests/test_strategy_catalog.py::test_all_strategies_returns_registry_instances -v`
Expected: FAIL — `ImportError: cannot import name 'all_strategies'`

- [ ] **Step 3: Thêm all_strategies vào registry**

`app/strategy/registry.py`:

```python
"""Static strategy registry (03 §6). No dynamic import from user input."""

from app.strategy.base import BaseStrategy
from app.strategy.liquidity_sweep import LiquiditySweepStrategy

_REGISTRY: dict[str, BaseStrategy] = {
    LiquiditySweepStrategy.code: LiquiditySweepStrategy(),
}


def get_strategy(code: str) -> BaseStrategy | None:
    return _REGISTRY.get(code)


def all_strategies() -> list[BaseStrategy]:
    """Every registered strategy instance (order stable by insertion)."""
    return list(_REGISTRY.values())
```

- [ ] **Step 4: Chạy test cho pass**

Run: `.venv/bin/python -m pytest tests/test_strategy_catalog.py::test_all_strategies_returns_registry_instances -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/strategy/registry.py tests/test_strategy_catalog.py
git commit -m "feat(strategy): registry.all_strategies()"
```

---

## Task 3: Service strategy_catalog + source_symbol_for

**Files:**
- Create: `app/services/strategy_catalog.py`
- Test: `tests/test_strategy_catalog.py`

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_strategy_catalog.py`:

```python
from app.seed import seed
from app.services.strategy_catalog import source_symbol_for, strategy_catalog


def test_source_symbol_for_falls_back_to_canonical(db):
    seed(db)
    db.flush()
    # XAUUSD có mapping trong seed; symbol lạ fallback = chính nó
    assert source_symbol_for(db, "NOSUCHSYM") == "NOSUCHSYM"


def test_strategy_catalog_shape(db):
    seed(db)
    db.flush()
    cat = strategy_catalog(db)
    ls = next(c for c in cat if c["code"] == "liquidity_sweep")
    assert ls["name"] == "Liquidity Sweep"
    assert ls["style"] == "INTRADAY"
    assert ls["recommended_symbols"] == ["XAUUSD", "EURUSD"]
    assert ls["required_timeframes"] == ["M15", "H1"]
    # alert = symbols × timeframes
    assert ls["alert_count"] == 2 * 2
    assert len(ls["alerts"]) == 4
    a = ls["alerts"][0]
    assert set(a) == {"symbol", "timeframe", "json"}
    assert '"secret"' in a["json"]
```

- [ ] **Step 2: Chạy test cho thất bại**

Run: `.venv/bin/python -m pytest tests/test_strategy_catalog.py -k catalog_shape -v`
Expected: FAIL — `ModuleNotFoundError: app.services.strategy_catalog`

- [ ] **Step 3: Viết service**

Tạo `app/services/strategy_catalog.py`:

```python
"""Catalog cách đánh cho UI + auto-guide TradingView (đợt 1).

Gom mọi strategy trong registry kèm metadata + danh sách alert TradingView cần
tạo (required_timeframes × recommended_symbols). Tái dùng tradingview_alert_json.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.models import BrokerSymbolMapping
from app.services.admin import tradingview_alert_json
from app.strategy.registry import all_strategies


def source_symbol_for(db: Session, canonical: str) -> str:
    """Broker symbol cho một canonical symbol; fallback = chính canonical."""
    row = db.scalar(
        select(BrokerSymbolMapping.broker_symbol).where(
            BrokerSymbolMapping.canonical_symbol == canonical,
            BrokerSymbolMapping.is_active.is_(True),
        )
    )
    return row or canonical


def strategy_catalog(db: Session) -> list[dict]:
    """Mọi cách đánh + metadata + alert TradingView cần tạo."""
    body_secret = get_settings().tradingview_body_secret
    out: list[dict] = []
    for strat in all_strategies():
        alerts = [
            {
                "symbol": sym,
                "timeframe": tf,
                "json": tradingview_alert_json(
                    body_secret, source_symbol_for(db, sym), tf
                ),
            }
            for sym in strat.recommended_symbols
            for tf in strat.required_timeframes
        ]
        out.append(
            {
                "code": strat.code,
                "name": strat.name,
                "tagline": strat.tagline,
                "description": strat.description,
                "style": strat.style,
                "recommended_symbols": strat.recommended_symbols,
                "required_timeframes": strat.required_timeframes,
                "alert_count": len(alerts),
                "alerts": alerts,
            }
        )
    return out
```

- [ ] **Step 4: Chạy test cho pass**

Run: `.venv/bin/python -m pytest tests/test_strategy_catalog.py -q`
Expected: PASS (cả 3 test).

Lưu ý: nếu `test_strategy_catalog_shape` fail ở `recommended_symbols`, kiểm tra seed có canonical mapping cho XAUUSD/EURUSD — test này chỉ đọc metadata strategy nên không phụ thuộc mapping; `alerts[0].json` dùng source_symbol (mapping hoặc fallback), không assert giá trị mapping cụ thể.

- [ ] **Step 5: Commit**

```bash
git add app/services/strategy_catalog.py tests/test_strategy_catalog.py
git commit -m "feat(catalog): strategy_catalog + source_symbol_for"
```

---

## Task 4: Route + template trang strategies-guide

**Files:**
- Modify: `app/api/admin.py` (thêm route sau route `strategies`, quanh dòng 278)
- Create: `app/templates/admin/strategies_guide.html`
- Modify: `app/templates/admin/base.html:52-59` (thêm mục sidebar)

- [ ] **Step 1: Thêm route GET /admin/strategies-guide**

`app/api/admin.py` — thêm ngay TRƯỚC `@router.get("/strategies", ...)` (dòng ~191):

```python
@router.get("/strategies-guide", response_class=HTMLResponse)
def strategies_guide(request: Request, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    from app.services.strategy_catalog import strategy_catalog
    return _render(request, db, session, "admin/strategies_guide.html", "StrategiesGuide",
                   {"catalog": strategy_catalog(db)})
```

- [ ] **Step 2: Tạo template**

Tạo `app/templates/admin/strategies_guide.html`:

```html
{% extends "admin/base.html" %}
{% block title %}Chọn cách đánh{% endblock %}
{% block content %}

<div class="max-w-4xl mx-auto">
  <h1 class="text-2xl font-bold tracking-tight mb-1">Chọn cách đánh</h1>
  <p class="text-base-content/60 mb-6">Mỗi cách đánh có hướng dẫn cấu hình TradingView riêng. Mở một thẻ để xem cần tạo cảnh báo nào.</p>

  <div class="space-y-4">
  {% for s in catalog %}
    <details class="rounded-xl border border-base-300 bg-base-100 overflow-hidden">
      <summary class="cursor-pointer list-none p-4 flex flex-wrap items-center gap-3">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2">
            <span class="font-semibold text-lg">{{ s.name }}</span>
            <span class="badge badge-sm badge-outline">{{ s.style }}</span>
          </div>
          <p class="text-sm text-base-content/60">{{ s.tagline }}</p>
        </div>
        <div class="text-xs text-base-content/50 text-right">
          <div>Cặp: {{ s.recommended_symbols|join(", ") }}</div>
          <div>Cần {{ s.alert_count }} cảnh báo</div>
        </div>
      </summary>

      <div class="border-t border-base-300 p-4 space-y-4">
        <p class="text-sm text-base-content/80">{{ s.description }}</p>

        <div>
          <p class="text-sm font-medium mb-2">Tạo {{ s.alert_count }} cảnh báo trên TradingView (mỗi thẻ = một cảnh báo):</p>
          <div class="grid gap-3 sm:grid-cols-2">
          {% for a in s.alerts %}
            <div class="rounded-lg border border-base-300 bg-base-200/40 p-3">
              <div class="flex items-center justify-between gap-2 mb-2">
                <span class="font-semibold text-sm">{{ a.symbol }} · {{ a.timeframe }}</span>
                <button type="button" class="btn btn-xs btn-primary"
                        onclick="navigator.clipboard.writeText(this.nextElementSibling.textContent); this.textContent='Đã chép ✓'; setTimeout(()=>this.textContent='Chép',1500);">Chép</button>
                <pre class="hidden">{{ a.json }}</pre>
              </div>
              <pre class="bg-base-200 rounded-lg p-3 text-[11px] leading-relaxed overflow-x-auto">{{ a.json }}</pre>
            </div>
          {% endfor %}
          </div>
        </div>

        <div class="flex flex-wrap gap-2 pt-1">
          <a href="/admin/guide" class="btn btn-sm btn-ghost">Xem hướng dẫn kết nối chung</a>
          <a href="/admin/strategies" class="btn btn-sm btn-primary">Cấu hình cho nhóm</a>
        </div>
      </div>
    </details>
  {% endfor %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Thêm mục sidebar**

`app/templates/admin/base.html` — trong list `sections` (dòng ~52), thêm dòng sau mục `/admin/strategies`:

```html
            ("/admin/strategies","Chiến lược","target","Strategies"),
            ("/admin/strategies-guide","Chọn cách đánh","book","StrategiesGuide"),
```

- [ ] **Step 4: Test route trả 200 + có tên strategy**

Thêm vào `tests/test_strategy_catalog.py`:

```python
def test_strategies_guide_page_renders(logged_in_client):
    r = logged_in_client.get("/admin/strategies-guide")
    assert r.status_code == 200
    assert "Chọn cách đánh" in r.text
    assert "Liquidity Sweep" in r.text
```

- [ ] **Step 5: Chạy test route**

Run: `.venv/bin/python -m pytest tests/test_strategy_catalog.py::test_strategies_guide_page_renders -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/api/admin.py app/templates/admin/strategies_guide.html app/templates/admin/base.html tests/test_strategy_catalog.py
git commit -m "feat(admin): trang Chọn cách đánh + auto-guide TradingView per strategy"
```

---

## Task 5: Full suite + lint gate

- [ ] **Step 1: Lint**

Run: `.venv/bin/ruff check app tests scripts`
Expected: `All checks passed!`

- [ ] **Step 2: Full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: tất cả pass (bao gồm test mới).

- [ ] **Step 3: Nếu lint/test fail**

Sửa inline, chạy lại. Không commit khi còn đỏ.

---

## Self-Review notes

- Spec Phần 1 (metadata) → Task 1. Phần 2 (service) → Task 2+3. Phần 3 (trang) → Task 4. Test → Task 3+4. ✓ đủ coverage.
- Section key `"StrategiesGuide"` khớp giữa route (`_render(... "StrategiesGuide" ...)`) và sidebar tuple. ✓
- `all_strategies()` định nghĩa Task 2, dùng Task 3. `source_symbol_for` định nghĩa + dùng Task 3. `strategy_catalog` định nghĩa Task 3, dùng Task 4. ✓ không tham chiếu hàm chưa định nghĩa.
- Không đụng DB schema → không cần migration. ✓
