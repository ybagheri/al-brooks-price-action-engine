"""Tests for the Phase 5 structural detectors: channels, ranges, second entries.

Phase 5 requires facts and structural observations only. These tests pin that
contract: geometry and measurements, never a signal.
"""

from __future__ import annotations

from albrooks.core.channels import detect_channel
from albrooks.core.ranges import (
    count_edge_touches,
    detect_breakout_attempt,
    detect_trading_range,
)
from albrooks.core.second_entry import detect_second_entry
from albrooks.core.swings import find_swings


def mk(o: float, h: float, low_val: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low_val, "c": c}


def _bar(h: float, low_val: float) -> dict[str, float]:
    mid = (h + low_val) / 2.0
    return mk(mid, h, low_val, mid)


# Explicit zigzag with peaks at 2/7/12 and troughs at 4/9, chosen so that
# find_swings(k=2) resolves them unambiguously.
ZIGZAG: list[dict[str, float]] = [
    _bar(100.0, 99.0),
    _bar(101.0, 99.5),
    _bar(103.0, 100.0),  # peak 103
    _bar(101.0, 99.0),
    _bar(100.0, 98.0),  # trough 98
    _bar(101.0, 99.0),
    _bar(102.0, 100.0),
    _bar(104.0, 101.0),  # peak 104
    _bar(102.0, 100.0),
    _bar(101.0, 99.0),  # trough 99
    _bar(102.0, 100.0),
    _bar(103.0, 101.0),
    _bar(105.0, 102.0),  # peak 105
    _bar(103.0, 101.0),
    _bar(102.0, 100.0),
]


# ---------------------------------------------------------------- channels


def test_bull_channel_from_rising_swings() -> None:
    last = len(ZIGZAG) - 1
    swings = find_swings(ZIGZAG, last, 2)
    assert [(s.bar_index, s.direction) for s in swings] == [
        (2, 1),
        (4, -1),
        (7, 1),
        (9, -1),
        (12, 1),
    ]
    # The channel is built from the two most recent confirmed swings per side:
    # highs 104@7 and 105@12, lows 98@4 and 99@9.
    ch = detect_channel(ZIGZAG, last, k=2, atr=1.0)
    assert ch.direction == 1 and ch.is_bull
    assert abs(ch.slope - 0.2) < 1e-9  # (105 - 104) / (12 - 7)
    assert abs(ch.upper_price - 105.0) < 1e-9
    assert abs(ch.lower_price - 99.6) < 1e-9  # 99 + 0.2 * (12 - 9)
    assert abs(ch.width - 5.4) < 1e-9
    assert ch.parallel is True
    assert ch.first_touch_bar == 4 and ch.last_touch_bar == 12
    assert ch.confirmed_bar_index == 14
    assert ch.is_broken is False


def test_channel_is_rejected_when_slopes_disagree() -> None:
    # highs rising but lows falling is a wedge, not a channel
    wedge = [
        _bar(100.0, 98.0),
        _bar(101.0, 99.0),
        _bar(103.0, 100.0),
        _bar(101.0, 98.0),
        _bar(100.0, 96.0),
        _bar(101.0, 97.0),
        _bar(102.0, 98.0),
        _bar(104.0, 99.0),
        _bar(102.0, 97.0),
        _bar(101.0, 95.0),
    ]
    ch = detect_channel(wedge, len(wedge) - 1, k=2, atr=1.0)
    assert ch.direction == 0 and ch.width == 0.0


def test_channel_needs_enough_confirmed_swings() -> None:
    # only two bars -> no swings at all
    assert detect_channel(ZIGZAG[:3], 2, k=2, atr=1.0).direction == 0
    assert detect_channel([], 0, k=2, atr=1.0).direction == 0
    assert detect_channel(ZIGZAG, -1, k=2, atr=1.0).direction == 0


def test_channel_breakout_is_detected() -> None:
    bars = list(ZIGZAG) + [_bar(108.0, 105.0), _bar(110.0, 107.0)]
    last = len(bars) - 1
    ch = detect_channel(bars, last, k=2, atr=1.0)
    assert ch.is_broken and ch.breakout_direction == 1
    assert ch.breakout_bar == len(ZIGZAG)


def test_channel_has_no_lookahead() -> None:
    last = len(ZIGZAG) - 1
    base = detect_channel(ZIGZAG, last, k=2, atr=1.0).to_dict()
    padded = detect_channel(ZIGZAG + [_bar(200.0, 190.0)] * 8, last, k=2, atr=1.0).to_dict()
    assert base == padded


# ---------------------------------------------------------------- ranges


def test_trading_range_requires_tests_on_both_edges() -> None:
    flat = [mk(100 + (0.4 if i % 2 else -0.4), 101, 99, 100) for i in range(30)]
    rng = detect_trading_range(flat, 29, atr=1.0, lookback=20, min_touches=2)
    assert rng.high == 101.0 and rng.low == 99.0
    assert abs(rng.height - 2.0) < 1e-9
    assert rng.touches_high >= 2 and rng.touches_low >= 2
    assert rng.is_broken is False
    assert rng.contains(100.0) and not rng.contains(105.0)


def test_trading_range_rejects_one_sided_action() -> None:
    trending = [_bar(100.0 + i, 99.0 + i) for i in range(30)]
    # A trending market tests the high repeatedly and the low not at all, so it
    # is not a trading range.
    rng = detect_trading_range(trending, 29, atr=1.0, lookback=20, min_touches=2)
    assert rng.touches_low < 2 or rng.height == 0.0


def test_trading_range_break_and_reclaim() -> None:
    flat = [mk(100 + (0.4 if i % 2 else -0.4), 101, 99, 100) for i in range(20)]
    broke = flat + [mk(101.5, 104.0, 101.2, 103.0)]
    rng = detect_trading_range(broke, 20, atr=1.0, lookback=20, min_touches=2)
    assert rng.is_broken and rng.is_bull_break and rng.breakout_bar == 20
    assert rng.is_failed is False  # nothing has come back yet

    # To observe a break AND its reclaim the window must stop before both, so
    # hold_bars=2 leaves bars 20 and 21 outside the edge calculation.
    reclaimed = broke + [mk(102.0, 102.5, 99.5, 100.0)]
    rng2 = detect_trading_range(
        reclaimed, 21, atr=1.0, lookback=20, min_touches=2, hold_bars=2
    )
    assert rng2.is_broken and rng2.breakout_bar == 20
    assert rng2.is_failed and rng2.reclaim_bar == 21

    # With hold_bars=1 the break bar is inside the window, so the range simply
    # re-anchors to the new high and no break is reported. That is inherent to a
    # window-based range, not a defect, and is why hold_bars exists.
    reanchored = detect_trading_range(
        reclaimed, 21, atr=1.0, lookback=20, min_touches=2, hold_bars=1
    )
    assert reanchored.is_broken is False


def test_count_edge_touches() -> None:
    bars = [_bar(101.0, 100.0), _bar(101.0, 100.0), _bar(106.0, 105.0)]
    # the third bar is far above 101, so it is not a touch
    assert count_edge_touches(bars, 0, 2, 101.0, True, 0.1) == 2
    # both first bars sit exactly on the lower level, so both are touches
    assert count_edge_touches(bars, 0, 2, 100.0, False, 0.1) == 2


def test_breakout_attempt_and_reclaim() -> None:
    bars = [_bar(100.0, 99.0), _bar(103.0, 102.0), _bar(100.5, 100.0)]
    up = detect_breakout_attempt(bars, 1, 2, level=101.0, direction=1, tol_atr=0.1, atr=1.0)
    assert up.direction == 1 and up.excursion > 0
    assert up.reclaimed and up.reclaim_bar == 2

    never = [_bar(100.0, 99.0), _bar(103.0, 102.0), _bar(104.0, 103.0)]
    up2 = detect_breakout_attempt(never, 1, 2, level=101.0, direction=1, tol_atr=0.1, atr=1.0)
    assert up2.reclaimed is False and up2.reclaim_bar == -1

    # no break at all
    quiet = [_bar(100.0, 99.0), _bar(100.5, 99.5)]
    assert detect_breakout_attempt(quiet, 1, 1, 101.0, 1, 0.1, 1.0).excursion == 0.0
    assert detect_breakout_attempt(bars, 1, 2, 101.0, 0, 0.1, 1.0).excursion == 0.0
    assert detect_breakout_attempt(bars, 99, 2, 101.0, 1, 0.1, 1.0).excursion == 0.0


# ---------------------------------------------------------------- second entry


SECOND_ENTRY_SERIES = [
    mk(100.0, 100.5, 99.5, 100.0),
    mk(100.0, 102.0, 99.8, 101.8),  # push (entry 1)
    mk(101.8, 101.9, 99.5, 100.2),  # counter-move
    mk(100.2, 104.0, 100.0, 103.9),  # push (entry 2), extends
    mk(103.9, 104.2, 103.0, 103.5),  # counter-move ends the run
]


def test_second_entry_bull() -> None:
    se = detect_second_entry(SECOND_ENTRY_SERIES, 3, 4, 1, atr=1.0)
    assert se.found and se.direction == 1
    assert se.first_bar == 1 and se.second_bar == 3
    assert se.pullback_bars == 1
    assert abs(se.pullback_size - 2.5) < 1e-9  # 102.0 -> 99.5
    assert se.extends is True
    assert se.entry1_extreme == 102.0 and se.entry2_extreme == 104.0


def test_second_entry_rejected_when_run_has_ended() -> None:
    # bar 4 is a counter-move, so the second entry is no longer current
    assert detect_second_entry(SECOND_ENTRY_SERIES, 4, 4, 1, atr=1.0).found is False
    # and it does not exist yet at bar 1
    assert detect_second_entry(SECOND_ENTRY_SERIES, 1, 4, 1, atr=1.0).found is False


def test_second_entry_requires_deep_enough_pullback() -> None:
    # a huge ATR makes the same 2.5 pullback too shallow
    assert detect_second_entry(SECOND_ENTRY_SERIES, 3, 4, 1, atr=100.0).found is False


def test_second_entry_bear_mirror() -> None:
    mirrored = [
        mk(200.0, 200.5, 199.5, 200.0),
        mk(200.0, 200.2, 198.0, 198.2),  # push down (entry 1)
        mk(198.2, 200.5, 198.1, 200.4),  # counter-move
        mk(200.4, 201.0, 196.0, 196.1),  # push down (entry 2), extends
        mk(196.1, 196.2, 195.0, 195.2),
    ]
    se = detect_second_entry(mirrored, 3, 4, -1, atr=1.0)
    assert se.found and se.direction == -1 and se.extends is True
    assert se.entry1_extreme == 198.0 and se.entry2_extreme == 196.0


def test_second_entry_wrong_direction_or_degenerate() -> None:
    assert detect_second_entry(SECOND_ENTRY_SERIES, 3, 4, -1, atr=1.0).found is False
    assert detect_second_entry(SECOND_ENTRY_SERIES, 3, 4, 0, atr=1.0).found is False
    assert detect_second_entry(SECOND_ENTRY_SERIES, 3, 4, 1, atr=0.0).found is False
    assert detect_second_entry([], 0, 0, 1, atr=1.0).found is False
    assert detect_second_entry(SECOND_ENTRY_SERIES, -1, 4, 1, atr=1.0).found is False
