"""Unit tests for Phase 4 Market Context and State Engine."""

from albrooks.context.market_state import analyze_market_state
from albrooks.engine.configuration import AnalyzerConfig


def mk(o: float, h: float, low_val: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low_val, "c": c}


def test_bull_trend() -> None:
    cfg = AnalyzerConfig()
    bars = [mk(100 + 2 * i, 103 + 2 * i, 99 + 2 * i, 102 + 2 * i) for i in range(60)]
    m = analyze_market_state(bars, 59, 59, 2.0, cfg)
    assert m.valid and m.state == "BULL_TREND"
    assert sum(m.percentages) == 100
    assert m.trend > 0.8
    assert m.pressure == 1.0


def test_bear_trend_mirror() -> None:
    cfg = AnalyzerConfig()
    bars = [mk(302 - 2 * i, 303 - 2 * i, 299 - 2 * i, 300 - 2 * i) for i in range(60)]
    m = analyze_market_state(bars, 59, 59, 2.0, cfg)
    assert m.valid and m.state == "BEAR_TREND"
    assert sum(m.percentages) == 100
    assert m.trend < -0.8
    assert m.pressure == -1.0


def test_bull_channel_grind() -> None:
    cfg = AnalyzerConfig()
    bars = [mk(100 + 0.2 * i, 104 + 0.2 * i, 98 + 0.2 * i, 103.5 + 0.2 * i) for i in range(60)]
    m = analyze_market_state(bars, 59, 59, 3.0, cfg)
    assert m.valid and m.state == "BULL_CHANNEL"
    assert sum(m.percentages) == 100
    assert m.chop >= 0.5


def test_trading_range() -> None:
    cfg = AnalyzerConfig()
    bars = []
    for i in range(60):
        if i % 2 == 0:
            bars.append(mk(98, 102, 98, 101.5))
        else:
            bars.append(mk(102, 102, 98, 98.5))
    m = analyze_market_state(bars, 59, 59, 2.0, cfg)
    assert m.valid and m.state == "TRADING_RANGE"
    assert sum(m.percentages) == 100
