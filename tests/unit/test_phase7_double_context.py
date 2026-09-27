"""Tests for Phase 7 double top/bottom context: third test, breakout, failure.

Phase 7 requires a double test and breakout/failure context. Neither existed.
"""

from __future__ import annotations

from albrooks.engine.configuration import AnalyzerConfig
from albrooks.setups.double import (
    classify_double_context,
    detect_double_test,
    detect_micro_double_bottom_with_context,
    detect_micro_double_top,
    detect_micro_double_top_with_context,
    find_major_double_bottom,
    find_major_double_bottom_with_context,
    find_major_double_top,
    find_major_double_top_with_context,
)


def mk(o: float, h: float, low_val: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low_val, "c": c}


def sw(bar: int, price: float, direction: int) -> dict:
    return {"bar": bar, "price": price, "dir": direction, "confirmed_bar": bar + 3}


CFG = AnalyzerConfig(double_tol_atr=0.25)


def _top_series() -> list[dict[str, float]]:
    """A micro double top at 100 with a third test, an upside break, a reclaim."""
    return [
        mk(98, 100.0, 97, 98),  # 0 first top
        mk(98, 97.0, 96, 96.5),  # 1 trough
        mk(97, 100.1, 97, 99.5),  # 2 second top
        mk(99, 99.9, 97, 98.0),  # 3
        mk(98, 100.05, 97.5, 99.0),  # 4 third test, no break
        mk(99, 99.9, 98, 98.5),  # 5
        mk(98.5, 104.0, 98.4, 103.0),  # 6 upside break through 100
        mk(103, 103.5, 98.0, 99.0),  # 7 reclaim back below the level
    ]


def test_micro_double_top_basics_unchanged() -> None:
    p = detect_micro_double_top(_top_series(), 2, 2, atr=2.0, config=CFG)
    assert p.found and p.is_micro and p.is_double_top
    assert (p.bar1, p.bar2) == (0, 2)
    # context is not populated by the bare detector
    assert p.level == 0.0 and p.is_broken is False


def test_third_test_and_breakout_and_failure() -> None:
    bars = _top_series()
    p = detect_micro_double_top_with_context(bars, 2, 7, atr=2.0, config=CFG)
    assert p.found
    assert abs(p.level - 100.05) < 1e-6  # mean of 100.0 and 100.1
    # bar 3 already reaches 99.9, within tolerance of the 100.05 level
    assert p.is_tested and p.test_bar == 3
    assert p.test_count >= 1
    assert p.is_broken and p.breakout_bar == 6
    assert p.breakout_direction == 1  # upside break through a double top
    assert p.is_failed and p.failure_bar == 7


def test_break_that_holds_is_not_failed() -> None:
    bars = _top_series()[:7]  # ends on the break, no reclaim
    p = detect_micro_double_top_with_context(bars, 2, 6, atr=2.0, config=CFG)
    assert p.is_broken and p.breakout_bar == 6
    assert p.is_failed is False and p.failure_bar == -1


def test_major_double_top_with_context() -> None:
    swings = [sw(0, 100.0, 1), sw(2, 94.0, -1), sw(4, 100.1, 1), sw(6, 93.0, -1), sw(8, 100.05, 1)]
    base = find_major_double_top(swings, 2.0, CFG)
    assert base.found and base.direction == -1 and (base.bar1, base.bar2) == (4, 8)

    bars = [mk(100, 101, 99, 100) for _ in range(12)]
    with_ctx = find_major_double_top_with_context(swings, bars, 11, 2.0, CFG)
    assert with_ctx.found
    assert abs(with_ctx.level - 100.075) < 1e-6
    assert with_ctx.is_tested and with_ctx.test_bar == 9
    assert with_ctx.is_broken is False


def test_major_double_bottom_mirrors_the_top() -> None:
    swings = [sw(1, 90.0, -1), sw(6, 95.0, 1), sw(11, 90.2, -1)]
    bars = [mk(90, 91, 89, 90) for _ in range(14)]
    bars[12] = mk(90, 91, 89, 90)
    bars[13] = mk(90, 90.5, 86.0, 87.0)  # downside break through 90
    p = find_major_double_bottom_with_context(swings, bars, 13, 2.0, CFG)
    assert p.found and p.is_double_bottom
    assert p.is_broken and p.breakout_direction == -1 and p.breakout_bar == 13
    assert p.is_failed is False

    unrecovered = find_major_double_bottom(swings, 2.0, CFG)
    assert unrecovered.level == 0.0 and unrecovered.is_broken is False


def test_detect_double_test_standalone() -> None:
    bars = [mk(100, 101, 99, 100) for _ in range(10)]
    bars[8] = mk(100, 100.2, 99, 100.0)  # touches 100, does not close beyond
    assert detect_double_test(bars, 9, level=100.0, is_resistance=True, atr=2.0, config=CFG) >= 1
    # support side
    support = [mk(100, 101, 99, 100) for _ in range(10)]
    support[8] = mk(100, 100.2, 99.8, 100.0)
    assert (
        detect_double_test(support, 9, level=100.0, is_resistance=False, atr=2.0, config=CFG)
        >= 1
    )
    # min_tests gates the result
    assert detect_double_test(
        bars, 9, level=100.0, is_resistance=True, atr=2.0, min_tests=99, config=CFG
    ) == 0
    # a close beyond the level is a break, so it is excluded from the count
    broke = [mk(100, 101, 99, 100) for _ in range(10)]
    broke[8] = mk(100, 105, 99, 104)
    counted = detect_double_test(
        broke, 9, level=100.0, is_resistance=True, atr=2.0, window=10, config=CFG
    )
    assert counted == 9  # the nine untouched bars, and not the breaking one


def test_context_classification_is_defensive() -> None:
    bars = _top_series()
    trending = [
        mk(100 + i * 0.3, 100.2 + i * 0.3, 100 + i * 0.3, 100.1 + i * 0.3)
        for i in range(5)
    ]
    not_found = detect_micro_double_top(trending, 4, 4, atr=2.0, config=CFG)
    assert not_found.found is False
    # enriching a not-found pattern must not invent a level
    same = classify_double_context(not_found, bars, 7, 2.0, CFG)
    assert same.level == 0.0 and same.is_broken is False
    # bad inputs
    p = detect_micro_double_top(bars, 2, 2, atr=2.0, config=CFG)
    assert classify_double_context(p, bars, 7, 0.0, CFG).level == 0.0
    assert classify_double_context(p, bars, -1, 2.0, CFG).level == 0.0
    assert classify_double_context(p, bars, 99, 2.0, CFG).level == 0.0


def test_micro_double_bottom_with_context_is_wired() -> None:
    bars = [
        mk(102, 103, 100.0, 101),  # 0 first bottom
        mk(101, 105, 101, 104),  # 1 rally
        mk(104, 104, 100.1, 101),  # 2 second bottom
        mk(101, 101, 96.0, 97.0),  # 3 downside break
        mk(97, 103, 97, 102.0),  # 4 reclaim back above the level
    ]
    p = detect_micro_double_bottom_with_context(bars, 2, 4, atr=2.0, config=CFG)
    assert p.found and p.is_double_bottom
    assert p.is_broken and p.breakout_direction == -1 and p.breakout_bar == 3
    assert p.is_failed and p.failure_bar == 4
