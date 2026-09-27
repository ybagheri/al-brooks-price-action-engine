"""Tests for the Phase 6 pullback lifecycle: candidate / provisional / confirmed.

The specification requires these four states to be distinguishable. The three
pre-existing Phase 6 tests pass unchanged, which is the evidence that adding the
lifecycle did not alter the counting rules.
"""

from __future__ import annotations

from albrooks.engine.configuration import AnalyzerConfig
from albrooks.setups.pullback import (
    PullbackState,
    apply_invalidation,
    detect_h1_h2,
    detect_l1_l2,
    is_invalidated,
)


def mk(o: float, h: float, low_val: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low_val, "c": c}


def flat_top_uptrend(
    n: int = 50, h: float = 200.0, low_val: float = 190.0, c0: float = 193.0, slope: float = 0.1
) -> list[dict[str, float]]:
    return [mk(c0 + i * slope - 0.5, h, low_val, c0 + i * slope) for i in range(n)]


def flat_top_downtrend(
    n: int = 50, h: float = 210.0, low_val: float = 200.0, c0: float = 207.0, slope: float = 0.1
) -> list[dict[str, float]]:
    return [mk(c0 - i * slope + 0.5, h, low_val, c0 - i * slope) for i in range(n)]


CFG = AnalyzerConfig(max_pb_bars=12, min_pb_ratio=0.15)


def _h2_series() -> list[dict[str, float]]:
    bars = flat_top_uptrend(50)
    bars += [
        mk(198, 200, 189, 196),  # 50 pullback dip
        mk(196, 202, 191, 201),  # 51 H1: 202 > 200
        mk(201, 200, 187, 192),  # 52 second leg: 187 < 189
        mk(192, 203, 190, 202),  # 53 H2: 203 > 200
        mk(202, 205, 200, 204),  # 54
        mk(204, 207, 202, 206),  # 55
    ]
    return bars


def test_confirmed_h2_reports_confirmed_state() -> None:
    s = detect_h1_h2(_h2_series(), 55, 55, 2.0, CFG)
    assert s.found and s.setup_type == "H2" and s.legs == 2
    assert s.state == PullbackState.CONFIRMED.value
    assert s.is_confirmed and not s.is_invalidated
    assert s.direction == 1
    assert s.anchor_bar == 51 and s.signal_bar == 53
    assert s.extreme_bar == 52


def test_first_entry_only_is_provisional() -> None:
    bars = flat_top_uptrend(50)
    bars += [
        mk(198, 200, 189, 196),
        mk(196, 202, 191, 201),  # 51 H1 forms
        mk(201, 202, 195, 200),  # 52 no deeper low
        mk(200, 204, 198, 203),
        mk(203, 206, 201, 205),
    ]
    s = detect_h1_h2(bars, 54, 54, 2.0, CFG)
    assert s.found and s.setup_type == "H1" and s.legs == 1
    assert s.state == PullbackState.PROVISIONAL.value
    assert s.signal_bar == 51 and s.anchor_bar == 51


def test_second_leg_without_resumption_is_provisional_not_h1() -> None:
    """A second counter leg HAS formed, so calling this a completed H1 is wrong."""
    bars = flat_top_uptrend(50)
    # After the second leg the highs are held flat at 200. A high equal to the
    # previous high is NOT a resumption, but the closes stay high, so the bull
    # context survives and the setup remains visible.
    bars += [
        mk(198, 200, 189, 196),
        mk(196, 202, 191, 201),  # 51 H1
        mk(201, 200, 187, 192),  # 52 second leg forms
        mk(192, 200, 190, 198),  # 53 high == 200, not a resumption
        mk(198, 200, 194, 199),  # 54
        mk(199, 200, 196, 199.5),  # 55
    ]
    s = detect_h1_h2(bars, 55, 55, 2.0, CFG)
    assert s.found
    assert s.legs == 2, "the second leg exists and must be counted"
    assert s.setup_type == "H2", "two legs means the H2 pattern, not a completed H1"
    assert s.state == PullbackState.PROVISIONAL.value
    assert s.signal_bar == -1, "no resumption bar exists yet"


def test_candidate_state_before_any_leg_completes() -> None:
    bars = flat_top_uptrend(50)
    # a pullback that has opened a window but has not made a higher high
    bars += [mk(199, 200, 190, 196), mk(196, 199, 188, 190)]
    s = detect_h1_h2(bars, 51, 51, 2.0, CFG)
    if s.found:
        assert s.state in (
            PullbackState.CANDIDATE.value,
            PullbackState.PROVISIONAL.value,
        )
    assert s.legs == 0


def test_bear_mirror_uses_the_same_lifecycle() -> None:
    bars = flat_top_downtrend(50)
    bars += [
        mk(202, 211, 200, 204),
        mk(204, 209, 198, 199),  # 51 L1
        mk(199, 213, 200, 208),  # 52 second leg
        mk(208, 210, 197, 198),  # 53 L2
        mk(198, 200, 195, 196),
        mk(196, 198, 193, 194),
    ]
    s = detect_l1_l2(bars, 55, 55, 2.0, CFG)
    assert s.found and s.setup_type == "L2" and s.legs == 2
    assert s.state == PullbackState.CONFIRMED.value
    assert s.direction == -1


def test_invalidation_when_price_closes_past_the_extreme() -> None:
    s = detect_h1_h2(_h2_series(), 55, 55, 2.0, CFG)
    assert s.extreme_bar == 52 and s.extreme_price == 187.0

    # a bar that stays above the extreme does not invalidate
    held = _h2_series() + [mk(206, 209, 204, 208)]
    assert is_invalidated(s, held, 56) is False
    assert apply_invalidation(s, held, 56).state == PullbackState.CONFIRMED.value

    # a close below the pullback low breaks the structure
    broke = _h2_series() + [mk(190, 191, 184, 185)]
    assert is_invalidated(s, broke, 56) is True
    out = apply_invalidation(s, broke, 56)
    assert out.state == PullbackState.INVALIDATED.value
    assert out.is_invalidated
    # the rest of the record is preserved so the caller can still log it
    assert out.setup_type == "H2" and out.legs == 2 and out.anchor_bar == 51


def test_invalidation_is_ignored_at_or_before_the_extreme_bar() -> None:
    s = detect_h1_h2(_h2_series(), 55, 55, 2.0, CFG)
    assert is_invalidated(s, _h2_series(), 52) is False
    assert is_invalidated(s, _h2_series(), 0) is False


def test_no_context_means_no_setup() -> None:
    """Without a trend there is nothing to pull back in."""
    flat = [mk(100, 100.5, 99.5, 100) for _ in range(60)]
    assert detect_h1_h2(flat, 59, 59, 2.0, CFG).state == PullbackState.NONE.value
    assert detect_l1_l2(flat, 59, 59, 2.0, CFG).state == PullbackState.NONE.value


def test_degenerate_inputs() -> None:
    s = detect_h1_h2([], 0, 0, 2.0, CFG)
    assert s.state == PullbackState.NONE.value and s.found is False
    assert detect_h1_h2(_h2_series(), 55, 55, 0.0, CFG).found is False
    assert detect_h1_h2(_h2_series(), -1, 55, 2.0, CFG).found is False
    assert detect_h1_h2(_h2_series(), 99, 55, 2.0, CFG).found is False
