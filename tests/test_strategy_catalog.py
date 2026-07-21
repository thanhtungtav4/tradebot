from app.seed import seed
from app.services.strategy_catalog import source_symbol_for, strategy_catalog
from app.strategy.registry import all_strategies, get_strategy


def test_all_strategies_returns_registry_instances():
    strats = all_strategies()
    assert len(strats) >= 1
    codes = {s.code for s in strats}
    assert "liquidity_sweep" in codes
    # cùng instance như get_strategy
    assert get_strategy("liquidity_sweep") in strats


def test_source_symbol_for_falls_back_to_canonical(db):
    seed(db)
    db.flush()
    # symbol lạ fallback = chính nó
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
