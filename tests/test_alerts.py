"""O1: edge-triggered admin alerts when a component degrades."""

from app.services import alerts


def test_transitions_detected():
    old = {"db": "OK", "redis": "OK", "telegram_api": "OK"}
    new = {"db": "DOWN", "redis": "OK", "telegram_api": "DEGRADED"}
    # Only components that moved OK -> not OK should be reported.
    degraded = alerts.newly_degraded(old, new)
    assert degraded == {"db": "DOWN", "telegram_api": "DEGRADED"}


def test_no_alert_when_still_bad():
    # Already DOWN last cycle -> don't re-alert (edge trigger, not level trigger).
    old = {"db": "DOWN"}
    new = {"db": "DOWN"}
    assert alerts.newly_degraded(old, new) == {}


def test_recovery_not_an_alert():
    old = {"db": "DOWN"}
    new = {"db": "OK"}
    assert alerts.newly_degraded(old, new) == {}


def test_unknown_is_not_degraded():
    # UNKNOWN is a neutral/startup state, not a failure worth paging on.
    old = {"telegram_api": "OK"}
    new = {"telegram_api": "UNKNOWN"}
    assert alerts.newly_degraded(old, new) == {}
