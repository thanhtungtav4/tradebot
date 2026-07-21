from app.strategy.registry import all_strategies, get_strategy


def test_all_strategies_returns_registry_instances():
    strats = all_strategies()
    assert len(strats) >= 1
    codes = {s.code for s in strats}
    assert "liquidity_sweep" in codes
    # cùng instance như get_strategy
    assert get_strategy("liquidity_sweep") in strats
