"""Unit tests for Phase 8 Breakout and Failed Breakout Engine."""

from albrooks.engine.configuration import AnalyzerConfig
from albrooks.setups.breakout import analyze_breakout


def mk(o: float, h: float, low_val: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low_val, "c": c}


def base(
    n: int = 29, h: float = 110.0, low_val: float = 100.0, c: float = 105.0
) -> list[dict[str, float]]:
    return [mk(c, h, low_val, c) for _ in range(n)]


def test_bull_breakout_pending() -> None:
    cfg = AnalyzerConfig()
    bars = base() + [mk(108, 113, 108, 112.5)]  # bar 29: close clears 110 + 0.2
    s = analyze_breakout(bars, 29, 29, 2.0, [], config=cfg)
    assert s.found and s.direction == 1
    assert s.breakout_bar == 29 and s.outcome == "PENDING"
    assert s.reference_price == 110.0 and not s.ref_is_swing
    assert s.decide_bar == -1 and not s.trap


def test_bull_follow_through() -> None:
    cfg = AnalyzerConfig()
    bars = base() + [
        mk(108, 113, 108, 112.5),  # 29: Breakout vs ref 110
        mk(112, 112.5, 110, 112),  # 30: holds beyond
    ]
    s = analyze_breakout(bars, 30, 30, 2.0, [], config=cfg)
    assert s.found and s.breakout_bar == 29
    assert s.outcome == "FOLLOW" and s.decide_bar == 30


def test_bull_failed_precedence() -> None:
    cfg = AnalyzerConfig()
    bars = base() + [
        mk(108, 113, 108, 112.5),  # 29: Breakout
        mk(112, 112.5, 110, 112),  # 30: extends
        mk(108, 109, 106, 108),  # 31: back inside (fail)
    ]
    s = analyze_breakout(bars, 31, 31, 2.0, [], config=cfg)
    assert s.found and s.breakout_bar == 29
    assert s.outcome == "FAILED" and s.decide_bar == 31
