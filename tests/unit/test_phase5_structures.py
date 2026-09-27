"""Unit tests for Phase 5 Price Action Structures (Exhaustion, Climaxes, Wedges)."""

from albrooks.core.structures import detect_exhaustion, detect_wedge, push_count_back
from albrooks.engine.configuration import AnalyzerConfig


def mk(o: float, h: float, low_val: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low_val, "c": c}


def test_climax_and_stall_bar() -> None:
    cfg = AnalyzerConfig(big_bar_atr=2.0, small_bar_atr=0.5)
    bars = [mk(100, 101, 99, 100)] * 5
    # Add a huge bar (range 5.0 vs ATR 2.0 -> 2.5x ATR -> Climax)
    bars.append(mk(100, 105, 100, 104.8))
    ex = detect_exhaustion(bars, 5, 5, direction=1, atr=2.0, config=cfg)
    assert ex.climax is True
    assert ex.stall is False

    # Add a stall bar (range 0.6 vs ATR 2.0 -> small bar with long tails)
    bars.append(mk(105.0, 105.45, 104.55, 105.0))  # body 0.1, up_w 0.3, lo_w 0.2
    ex2 = detect_exhaustion(bars, 6, 6, direction=1, atr=2.0, config=cfg)
    assert ex2.stall is True


def test_pushes_and_wedge() -> None:
    cfg = AnalyzerConfig(min_pushes=3)
    # Consecutive 4 bull bars making higher highs and higher closes
    bars = [mk(100 + i * 2, 103 + i * 2, 99 + i * 2, 102.5 + i * 2) for i in range(10)]
    pushes = push_count_back(bars, 9, 9, direction=1)
    assert pushes >= 4

    is_w = detect_wedge(bars, 9, 9, direction=1)
    assert is_w is True

    ex = detect_exhaustion(bars, 9, 9, direction=1, atr=2.0, config=cfg)
    assert ex.push_ok is True
    assert ex.wedge is True
    assert ex.breadth >= 2
