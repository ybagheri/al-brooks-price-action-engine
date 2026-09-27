"""Phase 9 requires detection, quality and decision to be separate layers.

The specification calls this distinction mandatory. These tests assert the
separation holds: the detector must not score, and the scorer must not search.
"""

from __future__ import annotations

from albrooks.engine.configuration import AnalyzerConfig
from albrooks.setups.reversal import (
    LEG_BREAKOUT_FOLLOW,
    LEG_EMA_BREAK,
    LEG_PRESSURE,
    LEG_RETEST,
    ReversalLegs,
    analyze_reversal,
    assess_reversal_quality,
    detect_reversal,
)


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


CFG = AnalyzerConfig()


def test_detection_reports_legs_and_no_score() -> None:
    bars = _mtr_series(5)
    legs = detect_reversal(bars, len(bars) - 1, len(bars) - 1, 2.0, [], 1, CFG)
    assert legs.leg_count == 4
    assert legs.is_present
    assert legs.satisfied_legs() == [LEG_EMA_BREAK, LEG_RETEST, LEG_BREAKOUT_FOLLOW, LEG_PRESSURE]
    assert legs.missing_legs() == []
    # detection exposes no score or verdict at all
    assert not hasattr(legs, "score")
    assert not hasattr(legs, "verdict")


def test_quality_scores_a_detected_structure_without_searching() -> None:
    legs = ReversalLegs(direction=1, ema_break=True, retest=True)
    q = assess_reversal_quality(legs)
    assert q.verdict == "MINOR"
    assert q.score == 50
    assert q.satisfied == [LEG_EMA_BREAK, LEG_RETEST]
    assert q.missing == [LEG_BREAKOUT_FOLLOW, LEG_PRESSURE]
    assert q.max_score == 100


def test_quality_of_nothing_is_none() -> None:
    q = assess_reversal_quality(ReversalLegs(direction=1))
    assert q.verdict == "NONE" and q.score == 0
    assert q.leg_count == 0
    assert q.satisfied == [] and q.missing


def test_full_sequence_is_major() -> None:
    legs = ReversalLegs(
        direction=-1, ema_break=True, retest=True, bo_follow=True, pressure_ok=True
    )
    q = assess_reversal_quality(legs)
    assert q.verdict == "MAJOR" and q.score == 100 and q.is_major


def test_wrapper_is_equivalent_to_running_both_layers() -> None:
    for grind in (0, 5):
        bars = _mtr_series(grind)
        idx = len(bars) - 1
        legs = detect_reversal(bars, idx, idx, 2.0, [], 1, CFG)
        q = assess_reversal_quality(legs)
        combined = analyze_reversal(bars, idx, idx, 2.0, [], 1, CFG)
        assert combined.found == (q.verdict != "NONE")
        assert combined.verdict == q.verdict
        assert combined.score == q.score
        assert combined.cross_bar == legs.cross_bar
        assert combined.pressure_count == legs.pressure_count


def test_score_is_a_count_not_a_probability() -> None:
    """A perfect score means four of four legs, not certainty."""
    bars = _mtr_series(5)
    idx = len(bars) - 1
    r = analyze_reversal(bars, idx, idx, 2.0, [], 1, CFG)
    assert r.score == 100 == r.score  # bounded, and equal to max
    partial = analyze_reversal(bars, idx, idx, 2.0, [], 1, CFG)
    assert partial.score <= 100 and partial.score >= 0
    # the score is a multiple of the per-leg weight, i.e. a count in disguise
    assert partial.score % 25 == 0


def test_degenerate_and_invalid_inputs() -> None:
    legs = detect_reversal([], 0, 0, 2.0, [], 1, CFG)
    assert legs.leg_count == 0 and legs.direction == 1
    assert detect_reversal(_mtr_series(), 5, 5, 0.0, [], 1, CFG).leg_count == 0
    assert detect_reversal(_mtr_series(), -1, 5, 2.0, [], 1, CFG).leg_count == 0
    bad_dir = detect_reversal(_mtr_series(), 5, 5, 2.0, [], 0, CFG)
    assert bad_dir.direction == 0 and bad_dir.leg_count == 0


def test_satisfied_and_missing_are_complementary() -> None:
    for mask in range(16):
        legs = ReversalLegs(
            direction=1,
            ema_break=bool(mask & 1),
            retest=bool(mask & 2),
            bo_follow=bool(mask & 4),
            pressure_ok=bool(mask & 8),
        )
        assert len(legs.satisfied_legs()) + len(legs.missing_legs()) == 4
        assert legs.leg_count == len(legs.satisfied_legs())
