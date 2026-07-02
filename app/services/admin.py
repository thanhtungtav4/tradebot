"""Admin Console data + audit helpers (12 spec). Read queries + activity logging."""

from datetime import datetime, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    AdminActivityLog,
    ComponentHealth,
    DataSourceFeed,
    GroupStrategySetting,
    GroupStrategySymbol,
    GroupStrategyTimeframe,
    Signal,
    SignalDelivery,
    SignalEvent,
    SymbolSetting,
    TelegramGroup,
    TelegramOutbox,
)

# Global status precedence: DOWN worst, then DEGRADED, PAUSED, OK.
_STATUS_RANK = {"DOWN": 3, "DEGRADED": 2, "PAUSED": 1, "OK": 0, "UNKNOWN": 0}
_PLACEHOLDER_CHAT_PREFIXES = ("PLACEHOLDER", "CHANGE_ME")


def is_placeholder_chat_id(chat_id: str) -> bool:
    return chat_id.upper().startswith(_PLACEHOLDER_CHAT_PREFIXES)


def live_activation_error(group) -> str | None:
    """Return the reason a group cannot be activated as LIVE, or None when safe."""
    if is_placeholder_chat_id(group.telegram_chat_id):
        return "Không thể bật LIVE khi Telegram chat id còn là placeholder."
    if group.last_test_message_at is None or group.last_delivery_status != "SENT":
        return "Cần gửi test message thành công trước khi bật LIVE."
    return None


def _age_minutes(ts: datetime | None) -> float | None:
    if ts is None:
        return None
    return (datetime.now(timezone.utc) - ts).total_seconds() / 60


def feed_matrix(db: Session) -> list[dict]:
    """Active feeds with computed staleness (M15 stale after 35m, H1 after 80m)."""
    feeds = db.scalars(
        select(DataSourceFeed)
        .where(DataSourceFeed.is_active.is_(True))
        .order_by(DataSourceFeed.canonical_symbol, DataSourceFeed.timeframe)
    ).all()
    out = []
    for f in feeds:
        age = _age_minutes(f.last_candle_time)
        status = f.status
        if status == "OK" and age is not None and age > f.stale_after_minutes:
            status = "STALE"
        out.append({
            "symbol": f.canonical_symbol, "timeframe": f.timeframe, "status": status,
            "last_candle_time": f.last_candle_time, "age_minutes": round(age, 1) if age else None,
            "stale_after_minutes": f.stale_after_minutes, "last_error": f.last_error_message,
            "source_symbol": f.source_symbol,
        })
    return out


def component_statuses(db: Session) -> list[ComponentHealth]:
    return db.scalars(select(ComponentHealth).order_by(ComponentHealth.component_code)).all()


def global_status(components: list[ComponentHealth], feeds: list[dict]) -> str:
    worst = 0
    for c in components:
        worst = max(worst, _STATUS_RANK.get(c.status, 0))
    if any(f["status"] in ("STALE", "ERROR") for f in feeds):
        worst = max(worst, _STATUS_RANK["DEGRADED"])
    return {3: "DOWN", 2: "DEGRADED", 1: "PAUSED", 0: "OK"}[worst]


def latest_signals(db: Session, limit: int = 10) -> list[Signal]:
    return db.scalars(select(Signal).order_by(desc(Signal.created_at)).limit(limit)).all()


def _pagination(page: int, per_page: int, total: int) -> dict:
    page = max(page, 1)
    per_page = min(max(per_page, 10), 100)
    pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, pages)
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev_page": page - 1 if page > 1 else 1,
        "next_page": page + 1 if page < pages else pages,
        "offset": (page - 1) * per_page,
    }


def signals_page(db: Session, *, page: int = 1, per_page: int = 50) -> dict:
    total = db.scalar(select(func.count()).select_from(Signal)) or 0
    pagination = _pagination(page, per_page, total)
    rows = db.scalars(
        select(Signal)
        .order_by(desc(Signal.created_at))
        .limit(pagination["per_page"])
        .offset(pagination["offset"])
    ).all()
    return {"rows": rows, "pagination": pagination}


def group_strategy_settings(db: Session) -> list[dict]:
    rows = db.scalars(select(GroupStrategySetting).order_by(GroupStrategySetting.id)).all()
    out = []
    for row in rows:
        group = db.get(TelegramGroup, row.group_id)
        symbols = db.scalars(
            select(GroupStrategySymbol.symbol)
            .where(GroupStrategySymbol.setting_id == row.id)
            .order_by(GroupStrategySymbol.symbol)
        ).all()
        timeframes = db.scalars(
            select(GroupStrategyTimeframe.timeframe)
            .where(GroupStrategyTimeframe.setting_id == row.id)
            .order_by(GroupStrategyTimeframe.timeframe)
        ).all()
        out.append({
            "setting": row,
            "group_name": group.name if group else f"#{row.group_id}",
            "symbols": symbols,
            "timeframes": timeframes,
        })
    return out


def available_symbols(db: Session) -> list[str]:
    return db.scalars(select(SymbolSetting.symbol).order_by(SymbolSetting.symbol)).all()


def delivery_summary(db: Session) -> dict:
    counts = dict(
        db.execute(
            select(TelegramOutbox.status, func.count()).group_by(TelegramOutbox.status)
        ).all()
    )
    last_sent = db.scalar(
        select(func.max(TelegramOutbox.sent_at)).where(TelegramOutbox.status == "SENT")
    )
    return {
        "pending": counts.get("PENDING", 0),
        "retryable": counts.get("FAILED_RETRYABLE", 0),
        "permanent": counts.get("FAILED_PERMANENT", 0),
        "sent": counts.get("SENT", 0),
        "last_sent_at": last_sent,
    }


def operator_next_action(status: str, feeds: list[dict], summary: dict) -> str:
    if status == "OK":
        return "Không có việc cần xử lý. Hệ thống đang nhận data, chạy strategy và gửi Telegram bình thường."
    stale = [f for f in feeds if f["status"] in ("STALE", "ERROR")]
    if stale:
        f = stale[0]
        return (
            f"Cần xử lý: {f['symbol']} {f['timeframe']} bị {f['status'].lower()} "
            f"(ngưỡng {f['stale_after_minutes']} phút). "
            f"Bước tiếp theo: kiểm tra TradingView alert cho {f['symbol']} {f['timeframe']} "
            f"hoặc tạm tắt group dùng feed này."
        )
    if summary["permanent"] or summary["retryable"]:
        return "Cần xử lý: có delivery Telegram đang lỗi. Mở màn Deliveries để retry hoặc kiểm tra group."
    return "Cần kiểm tra: một phần hệ thống đang chậm hoặc thiếu dữ liệu."


def operator_runbook(
    status: str,
    feeds: list[dict],
    summary: dict,
    components: list[ComponentHealth],
) -> list[dict]:
    """Contextual runbook cards for the Admin Overview degraded state."""
    if status == "OK":
        return []

    cards: list[dict] = []
    stale = [f for f in feeds if f["status"] in ("STALE", "ERROR")]
    if stale:
        first = stale[0]
        affected = ", ".join(f"{f['symbol']} {f['timeframe']}" for f in stale[:4])
        if len(stale) > 4:
            affected += f", +{len(stale) - 4}"
        cards.append({
            "title": "Feed TradingView stale/error",
            "severity": "DEGRADED",
            "summary": f"Feed bị ảnh hưởng: {affected}. Feed đầu tiên: {first['symbol']} {first['timeframe']}.",
            "steps": [
                "Mở TradingView alert tương ứng và kiểm tra alert còn enabled, đúng symbol/timeframe, đúng webhook URL.",
                "Gửi lại một bar test qua webhook hoặc màn import local/staging để xác nhận backend nhận candle.",
                "Nếu feed vẫn lỗi, tạm pause group phụ thuộc feed này trước khi gửi tín hiệu thật.",
            ],
            "link": "/admin/feeds",
            "link_label": "Mở Feeds",
        })

    if summary["permanent"] or summary["retryable"]:
        cards.append({
            "title": "Telegram delivery lỗi",
            "severity": "DOWN" if summary["permanent"] else "DEGRADED",
            "summary": (
                f"Retryable: {summary['retryable']}, permanent: {summary['permanent']}. "
                "Tín hiệu có thể đã tạo nhưng chưa tới đúng group."
            ),
            "steps": [
                "Mở Deliveries để xem lỗi HTTP/Telegram gần nhất và retry các dòng retryable.",
                "Nếu permanent, kiểm tra bot còn trong group, chat_id đúng, bot có quyền gửi tin.",
                "Sau khi test message thành công, retry delivery hoặc chờ scheduler quét lại.",
            ],
            "link": "/admin/deliveries",
            "link_label": "Mở Deliveries",
        })

    unhealthy_components = [
        c for c in components
        if c.status in ("DOWN", "DEGRADED", "UNKNOWN") and c.component_code not in {"data_feed", "telegram_api"}
    ]
    if unhealthy_components:
        codes = ", ".join(c.component_code for c in unhealthy_components[:5])
        cards.append({
            "title": "Component health không ổn định",
            "severity": "DOWN" if any(c.status == "DOWN" for c in unhealthy_components) else "DEGRADED",
            "summary": f"Component cần kiểm tra: {codes}.",
            "steps": [
                "Kiểm tra process API, worker, scheduler; restart process bị chết trước, rồi đọc log theo request_id.",
                "Nếu Redis/DB lỗi, ưu tiên khôi phục hạ tầng trước khi bật group thật.",
                "Chạy smoke script sau khi recovery để xác nhận webhook, signal, outbox và health cùng hoạt động.",
            ],
            "link": "/admin",
            "link_label": "Xem component tiles",
        })

    if not cards:
        cards.append({
            "title": "Trạng thái degraded chưa phân loại",
            "severity": "DEGRADED",
            "summary": "Hệ thống báo không OK nhưng chưa map được nguyên nhân cụ thể.",
            "steps": [
                "Đọc component tiles để xác định component có status khác OK.",
                "Kiểm tra log API/worker theo thời điểm checked_at gần nhất.",
                "Nếu đang demo, giữ group inactive cho tới khi health trở lại OK.",
            ],
            "link": "/admin",
            "link_label": "Mở Overview",
        })
    return cards


def overview(db: Session) -> dict:
    components = component_statuses(db)
    feeds = feed_matrix(db)
    summary = delivery_summary(db)
    status = global_status(components, feeds)
    return {
        "global_status": status,
        "components": components,
        "feeds": feeds,
        "signals": latest_signals(db),
        "delivery_summary": summary,
        "next_action": operator_next_action(status, feeds, summary),
        "runbook": operator_runbook(status, feeds, summary, components),
    }


def signal_detail(db: Session, signal_id: int) -> dict | None:
    sig = db.get(Signal, signal_id)
    if sig is None:
        return None
    events = db.scalars(
        select(SignalEvent).where(SignalEvent.signal_id == signal_id).order_by(SignalEvent.created_at)
    ).all()
    outboxes = db.scalars(
        select(TelegramOutbox).where(TelegramOutbox.signal_id == signal_id)
    ).all()
    deliveries = db.scalars(
        select(SignalDelivery).where(SignalDelivery.signal_id == signal_id).order_by(SignalDelivery.attempt_no)
    ).all()
    return {"signal": sig, "events": events, "outboxes": outboxes, "deliveries": deliveries}


def deliveries_by_status(
    db: Session, status: str, *, page: int = 1, per_page: int = 50
) -> dict:
    total = db.scalar(
        select(func.count()).select_from(TelegramOutbox).where(TelegramOutbox.status == status)
    ) or 0
    pagination = _pagination(page, per_page, total)
    rows = db.scalars(
        select(TelegramOutbox)
        .where(TelegramOutbox.status == status)
        .order_by(desc(TelegramOutbox.created_at))
        .limit(pagination["per_page"])
        .offset(pagination["offset"])
    ).all()
    return {"rows": rows, "pagination": pagination}


def log_action(
    db: Session, *, action: str, resource_type: str, resource_id: str | None = None,
    before: dict | None = None, after: dict | None = None, actor: str = "admin",
    ip: str | None = None, user_agent: str | None = None,
) -> None:
    """Write an admin_activity_logs row for any runtime-changing action (12 §2)."""
    db.add(AdminActivityLog(
        actor_type="ADMIN", actor_id=actor, action=action,
        resource_type=resource_type, resource_id=resource_id,
        before_state=before, after_state=after, ip_address=ip, user_agent=user_agent,
    ))


def update_signal_outcome(
    db: Session, signal_id: int, outcome_status: str, outcome_reason: str, actor: str = "admin"
) -> Signal | None:
    sig = db.get(Signal, signal_id)
    if sig is None:
        return None
    
    before = sig.metadata_.copy()
    
    outcome = {
        "status": outcome_status,
        "reason": outcome_reason,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    metadata = sig.metadata_.copy()
    metadata["outcome"] = outcome
    sig.metadata_ = metadata
    
    db.add(SignalEvent(
        signal_id=sig.id,
        event_type="SIGNAL_STATUS_UPDATED",
        message=f"Outcome updated manually to {outcome_status}: {outcome_reason}",
        details=outcome
    ))
    
    log_action(
        db,
        action="UPDATE_OUTCOME",
        resource_type="SIGNAL",
        resource_id=str(sig.id),
        before=before,
        after=metadata,
        actor=actor
    )
    
    db.flush()
    return sig
