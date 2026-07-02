"""Release readiness gate for moving from demo groups to real Telegram groups.

This script checks only evidence the application can verify from env + DB.
Human evidence such as the 48h demo run is tracked in docs/ops/release_checklist.md.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config.settings import Settings, get_settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import ComponentHealth, DataSource, DataSourceFeed, TelegramGroup, TelegramOutbox  # noqa: E402


@dataclass(frozen=True)
class CheckResult:
    code: str
    ok: bool
    summary: str
    details: str = ""


PLACEHOLDER_PREFIXES = ("PLACEHOLDER", "CHANGE_ME")
REQUIRED_COMPONENTS = {
    "api",
    "db",
    "redis",
    "data_feed",
    "market_worker",
    "signal_worker",
    "telegram_worker",
    "scheduler",
    "telegram_api",
}


def _is_placeholder_chat_id(chat_id: str) -> bool:
    return chat_id.upper().startswith(PLACEHOLDER_PREFIXES)


def check_settings(settings: Settings) -> CheckResult:
    return CheckResult(
        "settings_loaded",
        True,
        f"Settings loaded for APP_ENV={settings.app_env}",
        "Production placeholder secrets are rejected during Settings validation.",
    )


def check_component_health(db: Session) -> CheckResult:
    rows = db.scalars(select(ComponentHealth)).all()
    by_code = {row.component_code: row for row in rows}
    missing = sorted(REQUIRED_COMPONENTS - set(by_code))
    bad = sorted(
        f"{row.component_code}={row.status}"
        for row in rows
        if row.component_code in REQUIRED_COMPONENTS and row.status != "OK"
    )
    ok = not missing and not bad
    details = []
    if missing:
        details.append(f"missing: {', '.join(missing)}")
    if bad:
        details.append(f"not OK: {', '.join(bad)}")
    return CheckResult(
        "component_health_ok",
        ok,
        "All required component_health rows are OK" if ok else "Component health is not release-ready",
        "; ".join(details),
    )


def check_active_feeds(db: Session) -> CheckResult:
    rows = db.scalars(select(DataSourceFeed).where(DataSourceFeed.is_active.is_(True))).all()
    bad = sorted(
        f"{feed.canonical_symbol} {feed.timeframe}={feed.status}"
        for feed in rows
        if feed.status != "OK"
    )
    ok = bool(rows) and not bad
    details = "" if ok else (f"not OK: {', '.join(bad)}" if bad else "no active feeds")
    return CheckResult(
        "active_feeds_ok",
        ok,
        "All active feeds are OK" if ok else "Active feeds are not release-ready",
        details,
    )


def check_data_sources(db: Session) -> CheckResult:
    rows = db.scalars(select(DataSource).where(DataSource.is_active.is_(True))).all()
    bad = sorted(f"{src.code}={src.status}" for src in rows if src.status not in ("OK", "UNKNOWN"))
    ok = bool(rows) and not bad
    details = "" if ok else (f"bad sources: {', '.join(bad)}" if bad else "no active data sources")
    return CheckResult(
        "data_sources_usable",
        ok,
        "Active data sources are usable" if ok else "Active data sources need attention",
        details,
    )


def check_group_placeholders(db: Session) -> CheckResult:
    groups = db.scalars(select(TelegramGroup)).all()
    bad = [
        f"{group.name}({group.telegram_chat_id})"
        for group in groups
        if _is_placeholder_chat_id(group.telegram_chat_id) and (group.is_active or group.mode == "LIVE")
    ]
    ok = not bad
    return CheckResult(
        "no_live_placeholder_groups",
        ok,
        "No active/live group uses placeholder chat id"
        if ok
        else "Placeholder Telegram groups must stay inactive/demo",
        ", ".join(sorted(bad)),
    )


def check_live_group_tests(db: Session) -> CheckResult:
    live_groups = db.scalars(
        select(TelegramGroup).where(
            TelegramGroup.mode == "LIVE",
            TelegramGroup.is_active.is_(True),
        )
    ).all()
    bad = [
        group.name
        for group in live_groups
        if group.last_test_message_at is None or group.last_delivery_status != "SENT"
    ]
    ok = not bad
    return CheckResult(
        "live_groups_tested",
        ok,
        "Every active LIVE group has a successful test message"
        if ok
        else "Active LIVE groups must pass a Telegram test message first",
        ", ".join(sorted(bad)),
    )


def check_outbox_clean(db: Session) -> CheckResult:
    counts = dict(
        db.execute(select(TelegramOutbox.status, func.count()).group_by(TelegramOutbox.status)).all()
    )
    bad_statuses = ("FAILED_RETRYABLE", "FAILED_PERMANENT", "SENDING")
    bad = {status: counts.get(status, 0) for status in bad_statuses if counts.get(status, 0)}
    ok = not bad
    details = ", ".join(f"{status}={count}" for status, count in sorted(bad.items()))
    return CheckResult(
        "telegram_outbox_clean",
        ok,
        "Telegram outbox has no unresolved failed/sending rows"
        if ok
        else "Telegram outbox still has unresolved rows",
        details,
    )


def run_checks(db: Session, settings: Settings) -> list[CheckResult]:
    return [
        check_settings(settings),
        check_component_health(db),
        check_active_feeds(db),
        check_data_sources(db),
        check_group_placeholders(db),
        check_live_group_tests(db),
        check_outbox_clean(db),
    ]


def print_results(results: list[CheckResult]) -> None:
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        line = f"[{marker}] {result.code}: {result.summary}"
        if result.details:
            line += f" ({result.details})"
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check MVP release readiness gates.")
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Print failures but exit 0. Useful for local/demo environments.",
    )
    args = parser.parse_args()

    settings = get_settings()
    with SessionLocal() as db:
        results = run_checks(db, settings)
    print_results(results)
    failures = [result for result in results if not result.ok]
    if failures and not args.warn_only:
        print(f"release-check: blocked by {len(failures)} failing gate(s)")
        return 1
    if failures:
        print(f"release-check: warn-only mode, {len(failures)} gate(s) still failing")
    else:
        print("release-check: all automated gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
