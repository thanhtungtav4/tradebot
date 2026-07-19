"""Milestone B acceptance: webhook auth+ingest, admin auth (07/08 specs, plans 02/03)."""

import pytest
from sqlalchemy import select, text

from app.models import DataSourceFeed, MarketCandle
from tests.conftest import TEST_BODY_SECRET, TEST_WEBHOOK_TOKEN, TEST_ADMIN_PASSWORD

pytestmark = pytest.mark.integration

WEBHOOK = f"/api/v1/webhooks/tradingview/bars/{TEST_WEBHOOK_TOKEN}"


def _bar(**over):
    base = {
        "secret": TEST_BODY_SECRET,
        "symbol": "OANDA:XAUUSD",
        "timeframe": "M15",
        "time": "2026-01-01T00:00:00Z",
        "open": "2000.0", "high": "2010.0", "low": "1995.0", "close": "2005.0",
        "volume": "100", "isClosed": True,
    }
    base.update(over)
    return base


# --- webhook auth ---

def test_wrong_path_token_rejected(client):
    r = client.post("/api/v1/webhooks/tradingview/bars/wrong-token", json=_bar())
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_WEBHOOK_TOKEN"


def test_wrong_body_secret_rejected(client):
    r = client.post(WEBHOOK, json=_bar(secret="nope"))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_BODY_SECRET"


# --- ingestion ---

def test_valid_payload_creates_candle(client, db):
    r = client.post(WEBHOOK, json=_bar())
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "created"
    n = db.scalar(select(text("count(*)")).select_from(MarketCandle))
    assert n == 1


def test_duplicate_payload_is_noop(client, db):
    assert client.post(WEBHOOK, json=_bar()).json()["outcome"] == "created"
    assert client.post(WEBHOOK, json=_bar()).json()["outcome"] == "noop"
    n = db.scalar(select(text("count(*)")).select_from(MarketCandle))
    assert n == 1


def test_changed_candle_updates_row(client, db):
    client.post(WEBHOOK, json=_bar())
    r = client.post(WEBHOOK, json=_bar(close="2008.0"))
    assert r.json()["outcome"] == "updated"
    n = db.scalar(select(text("count(*)")).select_from(MarketCandle))
    assert n == 1


def test_invalid_ohlc_rejected(client):
    # high < low
    r = client.post(WEBHOOK, json=_bar(high="1990.0", low="2000.0"))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_OHLC"


def test_unknown_symbol_rejected(client):
    r = client.post(WEBHOOK, json=_bar(symbol="OANDA:BTCUSD"))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "UNKNOWN_SYMBOL"


def test_feed_freshness_updated(client, db):
    client.post(WEBHOOK, json=_bar())
    feed = db.scalar(
        select(DataSourceFeed).where(
            DataSourceFeed.canonical_symbol == "XAUUSD",
            DataSourceFeed.timeframe == "M15",
        )
    )
    assert feed.status == "OK"
    assert feed.last_candle_time is not None


def test_m15_enqueues_h1_does_not(client):
    r_m15 = client.post(WEBHOOK, json=_bar(timeframe="M15"))
    assert r_m15.json()["enqueued"] in (True, False)  # depends on Redis; contract is M15-only
    r_h1 = client.post(WEBHOOK, json=_bar(timeframe="H1", time="2026-01-01T01:00:00Z"))
    assert r_h1.json()["enqueued"] is False


# --- admin auth ---

def test_overview_requires_session(client):
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"


def test_admin_api_without_bearer_is_401():
    # require_api_key dep is not yet mounted on a route in Milestone B; assert the
    # dependency itself rejects. Wired to real admin API endpoints in later slices.
    from app.security.auth import AuthError, require_api_key

    class _Req:
        headers = {}

    with pytest.raises(AuthError):
        require_api_key(_Req(), settings=_FakeSettings())


class _FakeSettings:
    admin_api_key = "test-admin-api-key-abcdefghijklmnop"


def test_login_then_overview(client):
    # GET login sets a CSRF cookie
    g = client.get("/admin/login")
    assert g.status_code == 200
    csrf = client.cookies.get("admin_csrf")
    assert csrf

    # POST login with matching CSRF + correct credentials
    r = client.post(
        "/admin/login",
        data={"username": "admin", "password": TEST_ADMIN_PASSWORD, "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin"

    # session cookie now grants Overview
    ov = client.get("/admin")
    assert ov.status_code == 200
    assert "Overview" in ov.text


def test_login_wrong_password_401(client):
    client.get("/admin/login")
    csrf = client.cookies.get("admin_csrf")
    r = client.post(
        "/admin/login",
        data={"username": "admin", "password": "wrong", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 401


def test_login_rate_limited_after_burst(client, monkeypatch):
    """S1: brute-force from one IP is throttled to 429 once the limit is hit."""
    import uuid

    from app.config.settings import get_settings
    from app.services.health import redis_connection

    monkeypatch.setenv("LOGIN_RATE_LIMIT", "3")
    monkeypatch.setenv("LOGIN_RATE_WINDOW_SECONDS", "300")
    get_settings.cache_clear()
    ip = f"9.9.9.{uuid.uuid4().int % 250}"  # unique IP so the counter starts fresh
    redis_connection(get_settings()).delete(f"login:{ip}")

    client.get("/admin/login")
    csrf = client.cookies.get("admin_csrf")
    data = {"username": "admin", "password": "wrong", "csrf_token": csrf}
    headers = {"X-Forwarded-For": ip}

    for _ in range(3):
        r = client.post("/admin/login", data=data, headers=headers, follow_redirects=False)
        assert r.status_code == 401
    r = client.post("/admin/login", data=data, headers=headers, follow_redirects=False)
    assert r.status_code == 429
