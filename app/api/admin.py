"""Admin Console: session auth + operator cockpit screens (12 spec)."""

import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.db.session import get_db
from app.models import (
    DataSource,
    DataSourceFeed,
    GroupStrategySetting,
    GroupStrategySymbol,
    GroupStrategyTimeframe,
    Strategy,
    TelegramGroup,
    TelegramOutbox,
)
from app.api.errors import error_response
from app.schemas.tradingview import CandleImportPayload
from app.security.auth import require_api_key
from app.security import rate_limit
from app.security.secrets import constant_time_equals, verify_password
from app.security.session import COOKIE_NAME, issue_session, read_session
from app.services.health import redis_connection
from app.security.session_dep import require_session
from app.services import admin as admin_svc
from app.services import delivery
from app.services import ingestion
from app.services.queue import enqueue_run_strategy
from app.telegram.client import send_message

router = APIRouter(prefix="/admin")
api_router = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(require_api_key)])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_CSRF_COOKIE = "admin_csrf"


def _secure_cookies(settings: Settings) -> bool:
    return settings.app_env == "production"


def _render(request: Request, db: Session, session: dict, template: str, section: str, ctx: dict):
    """Render a screen with the shared header context (env, status, csrf, nav)."""
    settings = get_settings()
    global_status = admin_svc.global_status(
        admin_svc.component_statuses(db), admin_svc.feed_matrix(db)
    )
    base = {
        "env": settings.app_env.upper(),
        "global_status": global_status,
        "csrf_token": session["csrf"],
        "username": session["u"],
        "section": section,
    }
    return templates.TemplateResponse(request, template, {**base, **ctx})


def _check_csrf(request: Request, csrf_token: str) -> bool:
    session = read_session(request.cookies.get(COOKIE_NAME))
    return session is not None and constant_time_equals(csrf_token, session.get("csrf", ""))


def _client_ip(request: Request) -> str | None:
    """Real client IP behind nginx: first X-Forwarded-For hop, else socket peer."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def _audit_meta(request: Request) -> dict:
    return {"ip": _client_ip(request),
            "user_agent": request.headers.get("user-agent")}


# --- auth ---

@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, settings: Settings = Depends(get_settings)):
    csrf = secrets.token_urlsafe(32)
    resp = templates.TemplateResponse(
        request, "admin/login.html", {"csrf_token": csrf, "error": None}
    )
    resp.set_cookie(_CSRF_COOKIE, csrf, httponly=True, samesite="lax",
                    secure=_secure_cookies(settings), max_age=600)
    return resp


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    settings: Settings = Depends(get_settings),
):
    ip = _client_ip(request) or "unknown"
    if not rate_limit.check(
        redis_connection(settings), f"login:{ip}",
        limit=settings.login_rate_limit, window_seconds=settings.login_rate_window_seconds,
    ):
        return _login_error(request, "Too many attempts. Try again later.", status_code=429)

    cookie_csrf = request.cookies.get(_CSRF_COOKIE, "")
    if not cookie_csrf or not constant_time_equals(csrf_token, cookie_csrf):
        return _login_error(request, "Invalid CSRF token")
    ok_user = constant_time_equals(username, settings.admin_username)
    ok_pass = verify_password(settings.admin_password_hash, password)
    if not (ok_user and ok_pass):
        return _login_error(request, "Invalid credentials")
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(COOKIE_NAME, issue_session(username), httponly=True, samesite="lax",
                    secure=_secure_cookies(settings), max_age=settings.admin_session_ttl_hours * 3600)
    resp.delete_cookie(_CSRF_COOKIE)
    return resp


def _login_error(request: Request, message: str, status_code: int = 401) -> HTMLResponse:
    csrf = secrets.token_urlsafe(32)
    resp = templates.TemplateResponse(
        request, "admin/login.html", {"csrf_token": csrf, "error": message}, status_code=status_code
    )
    resp.set_cookie(_CSRF_COOKIE, csrf, httponly=True, samesite="lax", max_age=600)
    return resp


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    if not _check_csrf(request, csrf_token):
        return RedirectResponse("/admin/login", status_code=303)
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# --- screens ---

@router.get("", response_class=HTMLResponse)
def overview(request: Request, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    return _render(request, db, session, "admin/overview.html", "Overview",
                   {"data": admin_svc.overview(db)})


@router.get("/guide", response_class=HTMLResponse)
def guide(request: Request, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    """Step-by-step TradingView setup wizard with per-feed copy-paste JSON."""
    settings = get_settings()
    token = settings.tradingview_webhook_token
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    webhook_url = f"{scheme}://{host}/api/v1/webhooks/tradingview/bars/{token}"

    feeds_list = db.scalars(
        select(DataSourceFeed).where(DataSourceFeed.is_active.is_(True))
        .order_by(DataSourceFeed.canonical_symbol, DataSourceFeed.timeframe)
    ).all()
    alerts = [
        {
            "symbol": f.canonical_symbol,
            "timeframe": f.timeframe,
            "source_symbol": f.source_symbol,
            "json": admin_svc.tradingview_alert_json(settings.tradingview_body_secret, f.source_symbol, f.timeframe),
        }
        for f in feeds_list
    ]
    return _render(request, db, session, "admin/guide.html", "Guide", {
        "webhook_url": webhook_url,
        "body_secret": settings.tradingview_body_secret,
        "alerts": alerts,
    })


@router.get("/feeds", response_class=HTMLResponse)
def feeds(request: Request, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    settings = get_settings()
    webhook_url = "/api/v1/webhooks/tradingview/bars/{token}"
    return _render(request, db, session, "admin/feeds.html", "Feeds",
                   {"feeds": admin_svc.feed_matrix(db), "webhook_url": webhook_url,
                    "is_local": settings.app_env in ("local", "staging")})


@router.get("/strategies", response_class=HTMLResponse)
def strategies(request: Request, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    strats = db.scalars(select(Strategy).order_by(Strategy.code)).all()
    return _render(request, db, session, "admin/strategies.html", "Strategies",
                   {
                       "strategies": strats,
                       "settings": admin_svc.group_strategy_settings(db),
                       "symbols": admin_svc.available_symbols(db),
                       "timeframes": ["M15", "H1"],
                       "send_modes": ["BASIC", "FULL", "SUMMARY"],
                   })


@router.post("/strategies/settings/{setting_id}")
def update_group_strategy_setting(
    request: Request,
    setting_id: int,
    min_confidence: int = Form(...),
    send_mode: str = Form(...),
    cooldown_minutes: int = Form(...),
    min_rr: float = Form(...),
    is_active: str | None = Form(None),
    symbols: list[str] = Form(default=[]),
    timeframes: list[str] = Form(default=[]),
    csrf_token: str = Form(...),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    if not _check_csrf(request, csrf_token):
        return RedirectResponse("/admin/strategies", status_code=303)
    setting = db.get(GroupStrategySetting, setting_id)
    if setting is None:
        return RedirectResponse("/admin/strategies", status_code=303)

    allowed_symbols = set(admin_svc.available_symbols(db))
    allowed_timeframes = {"M15", "H1"}
    clean_symbols = sorted(set(symbols) & allowed_symbols)
    clean_timeframes = sorted(set(timeframes) & allowed_timeframes)
    if not clean_symbols or not clean_timeframes:
        return RedirectResponse("/admin/strategies", status_code=303)
    if send_mode not in {"BASIC", "FULL", "SUMMARY"}:
        return RedirectResponse("/admin/strategies", status_code=303)
    if not (0 <= min_confidence <= 100 and cooldown_minutes >= 0 and min_rr > 0):
        return RedirectResponse("/admin/strategies", status_code=303)

    before = {
        "min_confidence": setting.min_confidence,
        "send_mode": setting.send_mode,
        "cooldown_minutes": setting.cooldown_minutes,
        "min_rr": str(setting.min_rr),
        "is_active": setting.is_active,
    }
    setting.min_confidence = min_confidence
    setting.send_mode = send_mode
    setting.cooldown_minutes = cooldown_minutes
    setting.min_rr = min_rr
    setting.is_active = is_active == "on"

    db.execute(delete(GroupStrategySymbol).where(GroupStrategySymbol.setting_id == setting.id))
    db.execute(delete(GroupStrategyTimeframe).where(GroupStrategyTimeframe.setting_id == setting.id))
    for symbol in clean_symbols:
        db.add(GroupStrategySymbol(setting_id=setting.id, symbol=symbol))
    for timeframe in clean_timeframes:
        db.add(GroupStrategyTimeframe(setting_id=setting.id, timeframe=timeframe))

    admin_svc.log_action(
        db,
        action="update_group_strategy_setting",
        resource_type="group_strategy_setting",
        resource_id=str(setting.id),
        before=before,
        after={
            "min_confidence": setting.min_confidence,
            "send_mode": setting.send_mode,
            "cooldown_minutes": setting.cooldown_minutes,
            "min_rr": str(setting.min_rr),
            "is_active": setting.is_active,
            "symbols": clean_symbols,
            "timeframes": clean_timeframes,
        },
        actor=session["u"],
        **_audit_meta(request),
    )
    db.commit()
    return RedirectResponse("/admin/strategies", status_code=303)


@router.get("/groups", response_class=HTMLResponse)
def groups(request: Request, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    rows = db.scalars(select(TelegramGroup).order_by(TelegramGroup.id)).all()
    strats = db.scalars(select(Strategy).order_by(Strategy.code)).all()
    return _render(request, db, session, "admin/groups.html", "Groups",
                   {"groups": rows, "strategies": strats})


@router.post("/groups")
def create_group(
    request: Request,
    name: str = Form(...),
    type: str = Form(...),
    telegram_chat_id: str = Form(...),
    csrf_token: str = Form(...),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    if not _check_csrf(request, csrf_token):
        return RedirectResponse("/admin/groups", status_code=303)
    if not (3 <= len(name) <= 100) or type not in ("FREE", "VIP", "SMC", "INTERNAL"):
        return RedirectResponse("/admin/groups", status_code=303)
    group = TelegramGroup(name=name, type=type, mode="DEMO", telegram_chat_id=telegram_chat_id,
                          is_active=False)
    db.add(group)
    db.flush()
    admin_svc.log_action(db, action="create_group", resource_type="telegram_group",
                         resource_id=str(group.id), after={"name": name, "type": type},
                         actor=session["u"], **_audit_meta(request))
    db.commit()
    return RedirectResponse("/admin/groups", status_code=303)


@router.post("/groups/{group_id}/toggle")
def toggle_group(
    request: Request, group_id: int, csrf_token: str = Form(...),
    session: dict = Depends(require_session), db: Session = Depends(get_db),
):
    if not _check_csrf(request, csrf_token):
        return RedirectResponse("/admin/groups", status_code=303)
    group = db.get(TelegramGroup, group_id)
    if group:
        before = {"is_paused": group.is_paused}
        group.is_paused = not group.is_paused
        admin_svc.log_action(db, action="toggle_group_pause", resource_type="telegram_group",
                             resource_id=str(group_id), before=before,
                             after={"is_paused": group.is_paused}, actor=session["u"],
                             **_audit_meta(request))
        db.commit()
    return RedirectResponse("/admin/groups", status_code=303)


@router.post("/groups/{group_id}/activate-live")
def activate_live_group(
    request: Request, group_id: int, csrf_token: str = Form(...),
    session: dict = Depends(require_session), db: Session = Depends(get_db),
):
    if not _check_csrf(request, csrf_token):
        return RedirectResponse("/admin/groups", status_code=303)
    group = db.get(TelegramGroup, group_id)
    if group is None:
        return RedirectResponse("/admin/groups", status_code=303)

    before = {"mode": group.mode, "is_active": group.is_active, "is_paused": group.is_paused}
    error = admin_svc.live_activation_error(group)
    if error:
        group.notes = error
        admin_svc.log_action(
            db,
            action="activate_live_group_blocked",
            resource_type="telegram_group",
            resource_id=str(group_id),
            before=before,
            after={"reason": error},
            actor=session["u"],
            **_audit_meta(request),
        )
        db.commit()
        return RedirectResponse("/admin/groups", status_code=303)

    group.mode = "LIVE"
    group.is_active = True
    group.is_paused = False
    group.notes = None
    admin_svc.log_action(
        db,
        action="activate_live_group",
        resource_type="telegram_group",
        resource_id=str(group_id),
        before=before,
        after={"mode": group.mode, "is_active": group.is_active, "is_paused": group.is_paused},
        actor=session["u"],
        **_audit_meta(request),
    )
    db.commit()
    return RedirectResponse("/admin/groups", status_code=303)


@router.post("/groups/{group_id}/test")
def test_message(
    request: Request, group_id: int, csrf_token: str = Form(...),
    session: dict = Depends(require_session), db: Session = Depends(get_db),
):
    if not _check_csrf(request, csrf_token):
        return RedirectResponse("/admin/groups", status_code=303)
    group = db.get(TelegramGroup, group_id)
    if group:
        result = send_message(group.telegram_chat_id, "tradebot test message")
        group.last_test_message_at = datetime.now(timezone.utc)
        group.last_delivery_status = "SENT" if result.ok else "FAILED_RETRYABLE"
        admin_svc.log_action(db, action="test_message", resource_type="telegram_group",
                             resource_id=str(group_id), after={"ok": result.ok},
                             actor=session["u"], **_audit_meta(request))
        db.commit()
    return RedirectResponse("/admin/groups", status_code=303)


@router.get("/signals", response_class=HTMLResponse)
def signals(
    request: Request,
    page: int = 1,
    per_page: int = 50,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    data = admin_svc.signals_page(db, page=page, per_page=per_page)
    return _render(request, db, session, "admin/signals.html", "Signals",
                   {"signals": data["rows"], "pagination": data["pagination"]})


@router.get("/signals/{signal_id}", response_class=HTMLResponse)
def signal_detail(request: Request, signal_id: int, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    detail = admin_svc.signal_detail(db, signal_id)
    if detail is None:
        return RedirectResponse("/admin/signals", status_code=303)
    return _render(request, db, session, "admin/signal_detail.html", "Signals", {"d": detail})


@router.get("/deliveries", response_class=HTMLResponse)
def deliveries(
    request: Request,
    tab: str = "PENDING",
    page: int = 1,
    per_page: int = 50,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    tab = tab if tab in ("PENDING", "FAILED_RETRYABLE", "FAILED_PERMANENT", "SENT") else "PENDING"
    data = admin_svc.deliveries_by_status(db, tab, page=page, per_page=per_page)
    return _render(request, db, session, "admin/deliveries.html", "Deliveries",
                   {"tab": tab, "rows": data["rows"], "pagination": data["pagination"]})


@router.post("/deliveries/{outbox_id}/retry")
def retry_delivery(
    request: Request, outbox_id: int, csrf_token: str = Form(...),
    session: dict = Depends(require_session), db: Session = Depends(get_db),
):
    if not _check_csrf(request, csrf_token):
        return RedirectResponse("/admin/deliveries", status_code=303)
    ob = db.get(TelegramOutbox, outbox_id)
    if ob and ob.status in ("FAILED_RETRYABLE", "PENDING"):
        ob.next_attempt_at = datetime.now(timezone.utc)
        admin_svc.log_action(db, action="retry_delivery", resource_type="telegram_outbox",
                             resource_id=str(outbox_id), actor=session["u"], **_audit_meta(request))
        db.commit()
        # process immediately (single-worker MVP)
        delivery.process_outbox_row(db, ob)
        db.commit()
    return RedirectResponse(f"/admin/deliveries?tab={ob.status if ob else 'PENDING'}", status_code=303)


@router.post("/deliveries/{outbox_id}/skip")
def skip_delivery(
    request: Request, outbox_id: int, reason: str = Form(""), csrf_token: str = Form(...),
    session: dict = Depends(require_session), db: Session = Depends(get_db),
):
    if not _check_csrf(request, csrf_token):
        return RedirectResponse("/admin/deliveries", status_code=303)
    ob = db.get(TelegramOutbox, outbox_id)
    if ob and ob.status not in ("SENT",):
        ob.status = "SKIPPED"
        ob.last_error_message = reason or "Skipped by admin"
        admin_svc.log_action(db, action="skip_delivery", resource_type="telegram_outbox",
                             resource_id=str(outbox_id), after={"reason": reason},
                             actor=session["u"], **_audit_meta(request))
        db.commit()
    return RedirectResponse("/admin/deliveries", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    settings = get_settings()
    feeds_list = db.scalars(select(DataSourceFeed).where(DataSourceFeed.is_active.is_(True))).all()
    return _render(request, db, session, "admin/settings.html", "Settings", {
        "env": settings.app_env.upper(),
        "stale_grace": settings.stale_grace_minutes,
        "webhook_masked": _mask(settings.tradingview_webhook_token),
        "feeds": feeds_list,
    })


def _mask(secret: str) -> str:
    if len(secret) <= 8:
        return "********"
    return f"{secret[:4]}********{secret[-4:]}"


@api_router.post("/candles/import")
def import_candles(
    payload: list[CandleImportPayload] | dict,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Local/staging warmup import. Reuses the TradingView candle path."""
    if settings.app_env == "production":
        return error_response(403, "IMPORT_DISABLED", "Candle import is disabled in production")

    if isinstance(payload, dict):
        candles_raw = payload.get("candles")
        if not isinstance(candles_raw, list):
            return error_response(400, "INVALID_IMPORT_PAYLOAD", "Expected a list or {'candles': [...]}")
        try:
            candles = [CandleImportPayload.model_validate(item) for item in candles_raw]
        except Exception as exc:  # noqa: BLE001
            return error_response(400, "INVALID_IMPORT_PAYLOAD", str(exc)[:200])
    else:
        candles = payload

    source = db.scalar(select(DataSource).where(DataSource.code == "tradingview_bars"))
    if source is None:
        return error_response(400, "SOURCE_NOT_FOUND", "Seed data source tradingview_bars first")

    counts = {"created": 0, "updated": 0, "noop": 0, "enqueued": 0}
    try:
        for candle_payload in candles:
            norm = ingestion.normalize(db, source, candle_payload)
            _candle, outcome = ingestion.upsert_candle(db, source, norm)
            ingestion.update_feed_freshness(db, source, norm)
            counts[outcome] += 1
            if outcome in ("created", "updated") and enqueue_run_strategy(
                norm["symbol"], norm["timeframe"], norm["candle_time"], source.id
            ):
                counts["enqueued"] += 1
        db.commit()
    except ingestion.IngestError as exc:
        db.rollback()
        return error_response(exc.status_code, exc.code, exc.message)

    return JSONResponse({"imported": sum(counts[k] for k in ("created", "updated", "noop")), **counts})


@api_router.post("/signals/{signal_id}/outcome")
def update_signal_outcome_api(
    signal_id: int,
    payload: dict,
    db: Session = Depends(get_db),
) -> JSONResponse:
    status = payload.get("status")
    reason = payload.get("reason", "")
    if status not in ("WIN", "LOSS", "BREAKEVEN", "CANCELLED", "EXPIRED"):
        return error_response(400, "INVALID_OUTCOME_STATUS", "Invalid outcome status")
    
    sig = admin_svc.update_signal_outcome(db, signal_id, status, reason, actor="api")
    if sig is None:
        return error_response(404, "SIGNAL_NOT_FOUND", f"Signal {signal_id} not found")
    
    db.commit()
    return JSONResponse({"status": "OK", "signal_id": signal_id, "outcome": sig.metadata_["outcome"]})


@router.post("/signals/{signal_id}/outcome")
def update_signal_outcome_form(
    request: Request,
    signal_id: int,
    status: str = Form(...),
    reason: str = Form(""),
    csrf_token: str = Form(...),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    from app.api.admin import _check_csrf
    if not _check_csrf(request, csrf_token):
        return RedirectResponse(f"/admin/signals/{signal_id}", status_code=303)
    
    if status not in ("WIN", "LOSS", "BREAKEVEN", "CANCELLED", "EXPIRED"):
        return RedirectResponse(f"/admin/signals/{signal_id}", status_code=303)
    
    admin_svc.update_signal_outcome(db, signal_id, status, reason, actor=session["u"])
    db.commit()
    return RedirectResponse(f"/admin/signals/{signal_id}", status_code=303)
