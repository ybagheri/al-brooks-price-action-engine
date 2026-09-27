"""MarketState must expose mode / direction / strength per the specification.

These are the fields the public API promises. They are proxies, not
probabilities, and the tests pin that contract rather than any particular
market verdict.
"""

from __future__ import annotations

from albrooks.context.market_state import STATES, MarketState, analyze_market_state
from albrooks.engine.configuration import AnalyzerConfig


def mk(o: float, h: float, low_val: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low_val, "c": c}


def rising(n: int = 60, step: float = 0.5) -> list[dict[str, float]]:
    bars = []
    px = 100.0
    for _ in range(n):
        bars.append(mk(px - 0.2, px + 0.6, px - 0.6, px + 0.4))
        px += step
    return bars


def falling(n: int = 60, step: float = 0.5) -> list[dict[str, float]]:
    bars = []
    px = 160.0
    for _ in range(n):
        bars.append(mk(px + 0.2, px + 0.6, px - 0.6, px - 0.4))
        px -= step
    return bars


def test_mode_direction_and_strength_are_consistent() -> None:
    cfg = AnalyzerConfig()
    bull = analyze_market_state(rising(), 59, 59, atr=1.0, config=cfg)
    assert bull.mode == "BULL_TREND"
    assert bull.direction == 1
    assert 0.0 < bull.strength <= 1.0
    assert bull.is_trending and not bull.is_range

    bear = analyze_market_state(falling(), 59, 59, atr=1.0, config=cfg)
    assert bear.mode == "BEAR_TREND"
    assert bear.direction == -1
    assert bear.is_trending


def test_state_remains_an_alias_of_mode() -> None:
    """Backward compatibility: `state` must always mirror `mode`."""
    cfg = AnalyzerConfig()
    for bars in (rising(), falling()):
        s = analyze_market_state(bars, len(bars) - 1, len(bars) - 1, atr=1.0, config=cfg)
        assert s.state == s.mode
        assert s.to_dict()["state"] == s.to_dict()["mode"]


def test_strength_is_not_a_probability() -> None:
    """`strength` is a share of the mode vote, so it is bounded by 1 and sums to 1."""
    cfg = AnalyzerConfig()
    s = analyze_market_state(rising(), 59, 59, atr=1.0, config=cfg)
    assert sum(s.percentages) == 100
    assert all(0 <= p <= 100 for p in s.percentages)
    assert len(s.percentages) == len(STATES)
    # strength is the winning share, and nothing can exceed certainty here
    assert s.strength <= 1.0
    # the strongest mode must be the one reported
    assert STATES[s.percentages.index(max(s.percentages))] == s.mode


def test_neutral_and_invalid_states_have_zero_direction() -> None:
    cfg = AnalyzerConfig()
    s = analyze_market_state(rising(), 59, 59, atr=1.0, config=cfg)
    neutral_modes = {"TRADING_RANGE", "BREAKOUT_MODE", "TRANSITION", "UNKNOWN"}
    if s.mode in neutral_modes:
        assert s.direction == 0
    default = MarketState()
    assert default.mode == "UNKNOWN" and default.direction == 0
    assert default.strength == 0.0 and default.valid is False


def test_disabled_state_engine_returns_unknown() -> None:
    cfg = AnalyzerConfig(enable_market_state=False)
    s = analyze_market_state(rising(), 59, 59, atr=1.0, config=cfg)
    assert s.valid is False and s.mode == "UNKNOWN" and s.strength == 0.0
