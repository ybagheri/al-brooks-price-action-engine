"""Unit tests for Phase 9 Reversal and Major Trend Reversal (MTR) Engine."""

from albrooks.engine.configuration import AnalyzerConfig
from albrooks.setups.reversal import analyze_reversal


def mk(o: float, h: float, low_val: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low_val, "c": c}


def _mtr_series(n_grind: int = 5) -> list[dict[str, float]]:
    bars = []
    c = 100.0
    for _ in range(15):
        bars.append(mk(c, c + 1, c - 1, c))
    c -= 2.0
    bars.append(mk(c + 0.5, c + 1, c - 1, c))
    c -= 2.0
    bars.append(mk(c + 0.5, c + 1, c - 1, c))
    prev_h = bars[-1]["h"]
    for _ in range(3):
        c += 2.5
        h = max(prev_h + 0.3, c + 0.5)
        bars.append(mk(c - 0.5, h, c - 1.0, c))
        prev_h = h
    for _ in range(n_grind):
        c += 0.15
        h = max(prev_h + 0.2, c + 0.3)
        bars.append(mk(c - 0.05, h, c - 0.3, c))
        prev_h = h
    return bars


def test_mtr_major_all_four_legs() -> None:
    cfg = AnalyzerConfig()
    bars = _mtr_series(5)
    idx = len(bars) - 1
    s = analyze_reversal(bars, idx, idx, 2.0, [], reversal_direction=1, config=cfg)
    assert s.found and s.verdict == "MAJOR"
    assert s.ema_break and s.retest
    assert s.bo_follow and s.pressure_ok
    assert s.pressure_count >= 5 and s.score == 100 and s.cross_bar >= 0


def test_mtr_minor_partial() -> None:
    cfg = AnalyzerConfig()
    bars = _mtr_series(0)
    idx = len(bars) - 1
    s = analyze_reversal(bars, idx, idx, 2.0, [], reversal_direction=1, config=cfg)
    assert s.found and s.verdict == "MINOR"
    assert s.ema_break and s.retest
    assert not s.bo_follow and not s.pressure_ok
    assert s.score == 50
