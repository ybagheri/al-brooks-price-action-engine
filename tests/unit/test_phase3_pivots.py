"""Unit tests for Phase 3 pivot detection and significance measurement."""

from __future__ import annotations

from albrooks.core.pivots import (
    count_touches,
    find_major_pivots,
    find_pivots,
    measure_strength,
)


def mk(o: float, h: float, low_val: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low_val, "c": c}


def flat(n: int = 30) -> list[dict[str, float]]:
    return [mk(100, 101, 99, 100) for _ in range(n)]


def _tested_level_series() -> list[dict[str, float]]:
    """A swing low at bar 10 (95.0) that price revisits three times and holds."""
    bars = flat(30)
    bars[10] = mk(99.0, 99.5, 95.0, 95.5)
    bars[14] = mk(96.0, 97.0, 95.2, 96.5)
    bars[18] = mk(96.0, 97.0, 95.3, 96.5)
    bars[22] = mk(96.0, 97.0, 95.1, 96.5)
    return bars


def test_pivot_carries_confirmation_delay() -> None:
    """A pivot must not be visible before its confirmation bar closes."""
    bars = _tested_level_series()
    p10 = [p for p in find_pivots(bars, 29, 3, atr=2.0) if p.bar_index == 10]
    assert len(p10) == 1
    assert p10[0].confirmed_bar_index == 13  # bar + k
    assert p10[0].direction == -1 and p10[0].price == 95.0

    # with last_closed=12 the swing is not yet confirmed, so no pivot
    assert not any(p.bar_index == 10 for p in find_pivots(bars, 12, 3, atr=2.0))
    # with last_closed=13 it appears
    assert any(p.bar_index == 10 for p in find_pivots(bars, 13, 3, atr=2.0))


def test_strength_and_touch_counting() -> None:
    bars = _tested_level_series()
    p10 = next(p for p in find_pivots(bars, 29, 3, atr=2.0) if p.bar_index == 10)
    # the level was tested at bars 14, 18 and 22
    assert p10.touches == 3
    assert p10.is_major is True
    # nothing broke 95.0 inside the dominance window
    assert p10.strength >= 20


def test_touches_ignore_bars_after_last_closed() -> None:
    bars = _tested_level_series()
    early = next(p for p in find_pivots(bars, 16, 3, atr=2.0) if p.bar_index == 10)
    late = next(p for p in find_pivots(bars, 29, 3, atr=2.0) if p.bar_index == 10)
    assert early.touches == 1  # only the bar-14 test is visible at last_closed=16
    assert late.touches == 3
    assert early.price == late.price == 95.0


def test_major_pivots_filter() -> None:
    bars = _tested_level_series()
    major = find_major_pivots(bars, 29, 3, atr=2.0)
    assert major, "the well-tested level must be major"
    all_pivots = find_pivots(bars, 29, 3, atr=2.0)
    assert len(major) < len(all_pivots)
    assert all(p.touches >= 2 for p in major)


def test_pivots_have_no_lookahead() -> None:
    """The whole pivot list at a given bar must not change when future bars arrive."""
    bars = _tested_level_series()
    future = bars + [mk(100, 105, 100, 104) for _ in range(10)]
    base = [p.to_dict() for p in find_pivots(bars, 29, 3, atr=2.0)]
    after = [p.to_dict() for p in find_pivots(future, 29, 3, atr=2.0)]
    assert base == after


def test_zero_atr_falls_back_without_measurement() -> None:
    bars = _tested_level_series()
    pivots = find_pivots(bars, 29, 3, atr=0.0)
    assert pivots
    assert all(p.strength == 1 and p.touches == 0 for p in pivots)
    assert all(p.tolerance == 0.0 for p in pivots)


def test_degenerate_inputs_do_not_crash() -> None:
    bars = flat(30)
    assert find_pivots([], 0, 3, atr=1.0) == []
    assert count_touches(bars, {"bar_index": 5, "price": 100.0, "direction": -1}, 0.0, 29) == 0
    assert measure_strength(bars, {"bar_index": 5, "price": 100.0, "direction": 1}, 0.0, 29) == 1
    # a pivot bar at the very end has no future bars to test
    assert count_touches(bars, {"bar_index": 29, "price": 100.0, "direction": 1}, 2.0, 29) == 0
