"""Tests for the Phase 8 breakout state machine, second-leg trap and pullback."""

from __future__ import annotations

from albrooks.core.channels import PriceChannel
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.setups.breakout import (
    BreakoutState,
    analyze_breakout,
    detect_breakout_pullback,
    detect_channel_breakout,
    detect_second_leg_trap,
)


def mk(o: float, h: float, low_val: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low_val, "c": c}


def base(n: int = 29, h: float = 110.0, low_val: float = 100.0, c: float = 105.0):
    return [mk(c, h, low_val, c) for _ in range(n)]


CFG = AnalyzerConfig()


def test_breakout_state_is_distinct_from_pending() -> None:
    """The bar that clears the reference is BREAKOUT, not yet resolved."""
    bars = base() + [mk(108, 113, 108, 112.5)]  # 29 clears 110
    s = analyze_breakout(bars, 29, 29, 2.0, [], config=CFG)
    assert s.found and s.state == BreakoutState.BREAKOUT.value
    assert s.breakout_bar == 29 and s.decide_bar == -1
    assert s.is_resolved is False
    # the historical outcome field is unchanged
    assert s.outcome == "PENDING"
    assert s.reference_kind == "N_BAR"


def test_pending_when_the_breakout_is_on_an_earlier_bar() -> None:
    # bar 30 closes at 110.1, inside the 110.0..110.2 band around the reference,
    # so it neither extends nor fails the break from bar 29
    bars = base() + [mk(108, 113, 108, 112.5), mk(110, 110.1, 109, 110.1)]
    s = analyze_breakout(bars, 30, 30, 2.0, [], config=CFG)
    assert s.state == BreakoutState.PENDING.value
    assert s.is_resolved is False
    assert s.breakout_bar == 29 and s.decide_bar == -1


def test_follow_through_and_failed_are_resolved_states() -> None:
    # bar 31 stays under the bar-29 high so it is not a fresh reference of its own
    followed = base() + [
        mk(108, 113, 108, 112.5),
        mk(112, 112.5, 110, 112),
        mk(111.5, 113.0, 111, 112.8),
    ]
    s = analyze_breakout(followed, 31, 31, 2.0, [], config=CFG)
    assert s.breakout_bar == 29
    assert s.state == BreakoutState.FOLLOW_THROUGH.value and s.is_resolved

    failed = base() + [
        mk(108, 113, 108, 112.5),
        mk(112, 112.5, 110, 112),
        mk(108, 109, 106, 108),
    ]
    f = analyze_breakout(failed, 31, 31, 2.0, [], config=CFG)
    assert f.state == BreakoutState.FAILED.value and f.is_resolved
    assert f.decide_bar == 31


def test_second_leg_trap() -> None:
    """Extend beyond the reference, then reverse back through it."""
    bars = [
        mk(100, 101, 99, 100),  # 0 reference area
        mk(101, 103, 100.5, 102.5),  # 1 breakout above 101
        mk(102.5, 105, 102, 104.5),  # 2 second leg extends
        mk(104, 104.5, 99.0, 99.5),  # 3 reverses back below 101
    ]
    bar = detect_second_leg_trap(
        bars, breakout_bar=1, last_closed=3, reference=101.0, direction=1, tol=0.2
    )
    assert bar == 3

    # no trap when the move simply holds
    holds = bars[:3] + [mk(104.5, 106, 104, 105.5)]
    assert detect_second_leg_trap(holds, 1, 3, 101.0, 1, 0.2) == -1

    # no trap when nothing ever extended beyond the reference
    flat = [mk(100, 101, 99, 100) for _ in range(5)]
    assert detect_second_leg_trap(flat, 1, 4, 101.0, 1, 0.2) == -1
    assert detect_second_leg_trap(bars, -1, 3, 101.0, 1, 0.2) == -1
    assert detect_second_leg_trap(bars, 1, 3, 101.0, 0, 0.2) == -1


def test_breakout_pullback_that_holds() -> None:
    bars = [
        mk(100, 101, 99, 100),
        mk(101, 104, 100.5, 103.5),  # 1 breakout
        mk(103, 103.2, 100.9, 101.2),  # 2 comes back to just above 101
    ]
    assert detect_breakout_pullback(bars, 1, 2, 101.0, 1, tol=0.5) == 2


def test_a_close_through_the_reference_is_a_failure_not_a_pullback() -> None:
    bars = [
        mk(100, 101, 99, 100),
        mk(101, 104, 100.5, 103.5),
        mk(103, 103.2, 98.0, 98.5),  # closes back below 101
    ]
    assert detect_breakout_pullback(bars, 1, 2, 101.0, 1, tol=0.5) == -1
    # and the same series is reported as FAILED by the state machine
    assert detect_breakout_pullback([], 0, 1, 101.0, 0, 0.5) == -1
    assert detect_breakout_pullback(bars, -1, 2, 101.0, 1, 0.5) == -1


def test_channel_breakout_projects_the_boundary_forward() -> None:
    channel = PriceChannel(
        direction=1,
        slope=0.5,
        upper_price=110.0,
        lower_price=100.0,
        upper_slope=0.5,
        lower_slope=0.5,
        width=10.0,
        last_touch_bar=10,
    )
    bars = [mk(100, 101, 99, 100) for _ in range(15)]
    bars[12] = mk(113, 115, 112.5, 114.5)  # upper at 12 is 110 + 0.5*2 = 111
    s = detect_channel_breakout(bars, 12, 14, channel, tol_atr=0.1, atr=2.0)
    assert s.found and s.is_bull
    assert s.state == BreakoutState.BREAKOUT.value
    assert s.reference_kind == "CHANNEL"
    assert abs(s.reference_price - 111.0) < 1e-9

    # inside the channel -> no breakout (the channel spans 101..111 at bar 12)
    quiet = [mk(108, 109, 107, 108) for _ in range(15)]
    assert detect_channel_breakout(quiet, 12, 14, channel, atr=2.0).found is False
    # an undetermined channel cannot break anything
    assert detect_channel_breakout(bars, 12, 14, PriceChannel(), atr=2.0).found is False
    # index guards
    assert detect_channel_breakout(bars, -1, 14, channel, atr=2.0).found is False
    assert detect_channel_breakout(bars, 99, 14, channel, atr=2.0).found is False


def test_state_field_is_present_on_every_result() -> None:
    empty = analyze_breakout([], 0, 0, 2.0, [], config=CFG)
    assert empty.state == BreakoutState.NONE.value
    assert empty.found is False
