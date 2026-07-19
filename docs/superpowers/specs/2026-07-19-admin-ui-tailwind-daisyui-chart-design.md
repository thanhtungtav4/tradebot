# Admin Console UI Refactor — Tailwind + DaisyUI + TradingView Chart

Date: 2026-07-19

## Goal

Refactor the Admin Console UI (10 Jinja2 templates) from raw inline CSS to a
component-based system (Tailwind CSS + DaisyUI), and embed the TradingView
Advanced Chart widget into Signal detail and Feed views.

## Spec deviation (recorded)

Spec `12_ADMIN_CONSOLE_SPEC.md` §3 deliberately chose Jinja2 + HTMX + internal
CSS to avoid a large frontend stack. This refactor intentionally deviates:

- Adds Tailwind CSS + DaisyUI (via Tailwind **standalone CLI**, no npm/Node).
- Adds TradingView Advanced Chart **widget** (iframe) — a feature not in the
  original UI spec (spec had no chart screen).

Both approved by the product owner. Spec 12 gets a "UI stack revision" note so
future work does not drift back.

## Architecture

### 1. CSS build (Tailwind standalone CLI + DaisyUI)

- `scripts/tailwind.sh` downloads the standalone `tailwindcss` binary per OS
  (uname) into `.bin/` (gitignored). No npm, no node_modules.
- Input: `app/static/src/input.css` (`@import "tailwindcss"; @plugin "daisyui";`).
- Output: `app/static/css/app.css` — **committed to git** (deploy runs with no
  build step).
- Makefile: `make css` (build once), `make css-watch` (dev).
- Tailwind scans `app/templates/**/*.html` → purge, small output.

### 2. Static mount

- `main.py`: `app.mount("/static", StaticFiles(directory="app/static"))`.
- `base.html`: remove inline `<style>`, add
  `<link rel="stylesheet" href="/static/css/app.css">`.

### 3. Refactor 10 templates → DaisyUI

- `base.html`: DaisyUI `navbar`, `badge` for env + global status, nav `menu`.
- Status colors map to DaisyUI badges: OK→success, DEGRADED/STALE/WARMUP→warning,
  DOWN/ERROR/FAILED→error, PAUSED/UNKNOWN/PENDING→neutral. **Keep icon + label +
  text** (spec §15 a11y — status never color-only).
- Tables→`table`, tiles→`card`/`stats`, alerts→`alert`, runbook→`card`.
- All Jinja logic, HTMX, CSRF, forms unchanged — markup/class only.

### 4. TradingView chart

- Partial `admin/_tv_chart.html(symbol, interval)` — Advanced Chart widget.
- Symbol = `source_symbol` (already `OANDA:XAUUSD`, matches widget format).
- Timeframe→interval: M15→15, H1→60.
- Signal detail: one chart for the signal's symbol/TF.
- Feeds list: per-feed collapsible `<details>` with a chart (no new route).

## A11y (hard constraint, spec §15)

Contrast 4.5:1, 44px touch targets, visible focus, status = icon+label+text,
labels on inputs, table headers. Verify during refactor.

## Skipped (YAGNI)

- Dark mode toggle — DaisyUI supports it; not required. Add on request.
- Lightweight Charts (draw DB candles + entry/SL/TP overlay) — add when the
  team wants the bot's own candles instead of TradingView's live data.
- Mobile bottom nav (spec §4) — out of this scope. Add for mobile pass.

## Risks

- Standalone CLI binary ~30MB, downloaded once per OS via script.
- CSS committed → keep `make css` run before committing template changes.
