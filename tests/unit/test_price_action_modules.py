"""Tests for the focused price-action modules extracted from bars.py.

These lock in behaviour that the Phase 2 tests only covered indirectly through
`analyze_bar`, so a future refactor cannot silently change the primitives.
"""

from __future__ import annotations

from albrooks.price_action.climaxes import is_climax, is_stall, measure_bar
from albrooks.price_action.gaps import detect_gap, detect_micro_gap, gap_run_length
from albrooks.price_action.overlap import (
    count_inside_run,
    detect_barbwire,
    is_inside_bar,
    is_outside_bar,
    pair_overlap,
)
from albrooks.price_action.pressure import consecutive_run, count_pressure, push_count_back
from albrooks.price_action.wedges import detect_wedge, is_shrinking, is_tightening


def mk(o: float, h: float, low_val: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low_val, "c": c}


# ---------------------------------------------------------------- overlap


def test_pair_overlap_geometry() -> None:
    """Overlap is measured on BODIES, not full ranges.

    A bar whose body is half its range cannot report more than 0.5 overlap
    with an identical twin, which is a subtlety worth pinning.
    """
    twin = mk(100, 110, 90, 105)  # body 100..105, range 20
    assert abs(pair_overlap(twin, twin) - 5.0 / 20.0) < 1e-9
    # touching bodies share nothing
    assert pair_overlap(mk(100, 110, 90, 100), mk(110, 120, 110, 120)) == 0.0
    # zero-range bar must not divide by zero
    assert pair_overlap(mk(100, 100, 100, 100), mk(100, 110, 90, 105)) == 0.0


def test_inside_and_outside_bars() -> None:
    prev = mk(100, 110, 90, 105)
    assert is_inside_bar(mk(100, 105, 95, 102), prev)
    assert not is_inside_bar(mk(100, 115, 95, 102), prev)
    assert is_outside_bar(mk(100, 120, 80, 110), prev)
    # a strict inequality is required on at least one side
    assert not is_outside_bar(prev, prev)


def test_count_inside_run() -> None:
    bars = [
        mk(100, 110, 90, 100),
        mk(100, 105, 95, 100),
        mk(100, 103, 96, 100),
        mk(100, 115, 85, 110),
    ]
    assert count_inside_run(bars, 2, 3) == 2
    assert count_inside_run(bars, 3, 3) == 0
    assert count_inside_run(bars, 0, 3) == 0


def test_barbwire_requires_both_overlap_and_a_doji() -> None:
    """Both conditions are needed: heavy overlap AND a doji in the window.

    Bars with a body exactly half their range overlap each other by 0.5, which
    is the `overlap_ratio` threshold. The doji can sit at the window tail.
    """
    core = [mk(100, 101.5, 99.5, 101) for _ in range(5)]
    with_doji = [mk(100, 101.5, 99.5, 100.05)] + core
    without_doji = [mk(100, 101.5, 99.5, 100.9)] + core
    assert detect_barbwire(with_doji, 5, 5)
    # identical overlap, but no doji anywhere in the window
    assert not detect_barbwire(without_doji, 5, 5)
    # heavy overlap but only two pairs -> below the minimum
    assert not detect_barbwire(with_doji[:4], 3, 3)


# ---------------------------------------------------------------- pressure


def test_push_count_requires_both_close_and_extreme() -> None:
    bars = [
        mk(100, 105, 95, 100),
        mk(100, 106, 96, 105),
        mk(105, 108, 104, 107),
        mk(107, 109, 106, 108),
    ]
    assert push_count_back(bars, 3, 3, 1) == 3
    assert push_count_back(bars, 3, 3, -1) == 0
    assert push_count_back(bars, 0, 3, 1) == 0
    assert push_count_back(bars, 3, 3, 0) == 0


def test_consecutive_run_is_signed_and_doji_aware() -> None:
    rising = [mk(100, 105, 95, 104), mk(104, 109, 99, 108), mk(108, 113, 103, 112)]
    assert consecutive_run(rising, 2, 2) == 3
    falling = [mk(110, 115, 105, 106), mk(106, 111, 101, 102), mk(102, 107, 97, 98)]
    assert consecutive_run(falling, 2, 2) == -3
    # a doji at idx ends the run entirely (Brooks: a doji is a pause)
    with_doji = rising + [mk(112, 116, 112, 112.05)]
    assert consecutive_run(with_doji, 3, 3) == 0


def test_count_pressure_counts_strong_bars() -> None:
    bars = [
        mk(100, 110, 90, 109),  # strong bull: closes near high, big body
        mk(109, 119, 99, 118),  # strong bull
        mk(118, 128, 108, 109),  # strong bear: closes near low
    ]
    bull, bear = count_pressure(bars, 2, 2, lookback=3)
    assert bull == 2 and bear == 1
    assert count_pressure([], 0, 0) == (0, 0)


# ---------------------------------------------------------------- gaps


def test_detect_gap_both_directions() -> None:
    bars = [mk(100, 101, 99, 100), mk(102, 105, 101.5, 104.5)]
    up = detect_gap(bars, 1)
    assert up.found and up.direction == 1
    assert abs(up.size - 0.5) < 1e-9  # 101.5 - 101.0
    assert up.prior_extreme == 101.0 and up.gap_edge == 101.5

    down_bars = [mk(100, 101, 99, 100), mk(98, 98.5, 96, 96.5)]
    down = detect_gap(down_bars, 1)
    assert down.found and down.direction == -1
    assert abs(down.size - 0.5) < 1e-9  # 99.0 - 98.5

    # no gap when ranges touch
    assert not detect_gap([mk(100, 101, 99, 100), mk(100, 102, 98, 101)], 1).found
    # a gap needs a predecessor
    assert not detect_gap(bars, 0).found
    assert not detect_gap(bars, 99).found


def test_detect_micro_gap_size_gate() -> None:
    bars = [mk(100, 101, 99, 100), mk(102, 105, 101.5, 104.5)]
    assert detect_micro_gap(bars, 1, atr=2.0, min_size_atr=0.0).found
    # gate at 1.0 ATR = 2.0, but the gap is only 0.5
    assert not detect_micro_gap(bars, 1, atr=2.0, min_size_atr=1.0).found
    # with no ATR the raw detection stands
    assert detect_micro_gap(bars, 1, atr=0.0, min_size_atr=1.0).found


def test_gap_run_length() -> None:
    staircase = [
        mk(100, 101, 99, 100),
        mk(102, 103, 101.5, 102.5),
        mk(104, 105, 103.5, 104.5),
    ]
    assert gap_run_length(staircase, 2, 2) == 2
    # a single gap is a run of one, not zero
    mixed = [
        mk(100, 101, 99, 100),
        mk(102, 103, 101.5, 102.5),
        mk(100, 101, 99, 100.5),
    ]
    assert gap_run_length(mixed, 2, 2) == 1
    # no gap at all -> no run
    assert gap_run_length(staircase, 0, 2) == 0
    assert gap_run_length([], 1, 1) == 0


# ---------------------------------------------------------------- climaxes


def test_climax_and_stall() -> None:
    big = mk(100, 110, 90, 109)  # range 20
    assert is_climax(big, atr=5.0)  # 20 >= 2.0 * 5
    assert not is_climax(big, atr=50.0)
    assert not is_climax(big, atr=0.0)

    # small range with tails on both sides
    stall = mk(100, 101.0, 99.0, 100.02)
    assert is_stall(stall, atr=10.0)
    # small range but no tails
    solid = mk(100, 101.0, 99.0, 100.95)
    assert not is_stall(solid, atr=10.0)


def test_measure_bar_reports_character() -> None:
    char = measure_bar(mk(100, 110, 90, 109), atr=5.0)
    assert char.direction == 1
    assert char.is_climax and not char.is_stall
    assert abs(char.body_ratio - 9.0 / 20.0) < 1e-9
    assert not measure_bar(mk(100, 110, 90, 109), atr=0.0).is_climax


# ---------------------------------------------------------------- wedges


def test_is_shrinking_and_tightening() -> None:
    shrinking = [
        mk(100, 110, 90, 109),   # range 20
        mk(109, 116, 103, 115),  # range 13
        mk(115, 119, 110, 118),  # range 9
    ]
    assert is_shrinking(shrinking, 2, 3)

    expanding = [
        mk(100, 103, 99, 102),   # range 4
        mk(102, 108, 101, 107),  # range 7
        mk(107, 116, 106, 115),  # range 10
    ]
    assert not is_shrinking(expanding, 2, 3)

    # tightening compares the newest bar against the median of the prior window,
    # so it needs `window` bars of history before the current one
    contracting = [
        mk(100, 110, 90, 109),
        mk(109, 119, 99, 118),
        mk(118, 120, 117, 119),
        mk(119, 120.5, 118, 120),
        mk(120, 121, 119.5, 120.8),
    ]
    assert is_tightening(contracting, 4, window=4)
    assert not is_tightening(shrinking, 2, window=4)  # not enough history
    assert not is_tightening(contracting, 2, window=4)


def test_detect_wedge_requires_three_pushes() -> None:
    pushy = [
        mk(100, 105, 95, 100),
        mk(100, 106, 96, 105),
        mk(105, 108, 104, 107),
        mk(107, 109, 106, 108),
    ]
    assert detect_wedge(pushy, 3, 3, 1)
    assert not detect_wedge(pushy[:2], 1, 1, 1)  # not enough pushes
    assert not detect_wedge(pushy, 3, 3, -1)  # wrong direction
    assert not detect_wedge(pushy, 3, 3, 0)
