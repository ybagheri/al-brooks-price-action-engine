"""Unit tests for Phase 3 Swings, Pivots, and Legs."""

from albrooks.core.bars import Bar
from albrooks.core.legs import build_legs_from_swings, detect_two_leg_structures
from albrooks.core.swings import find_swings


def test_swing_detection_and_no_repaint() -> None:
    # Build a triangle peak at bar 5: bars 0..10
    # Swing High at index 5 with k=3
    # Confirmed only at index 5 + 3 = 8
    bars = []
    prices = [10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10]
    for i, p in enumerate(prices):
        bars.append(
            Bar(
                time=float(i * 60),
                open=p - 0.5,
                high=p,
                low=p - 1.0,
                close=p - 0.2,
                index=i,
            )
        )

    # At bar 7: swing at 5 is NOT yet confirmed (requires last_closed >= 5 + 3 = 8)
    swings_at_7 = find_swings(bars, last_closed_idx=7, k=3)
    assert len(swings_at_7) == 0

    # At bar 8: swing at 5 IS confirmed
    swings_at_8 = find_swings(bars, last_closed_idx=8, k=3)
    assert len(swings_at_8) == 1
    assert swings_at_8[0].bar_index == 5
    assert swings_at_8[0].price == 20.0
    assert swings_at_8[0].direction == 1
    assert swings_at_8[0].confirmed_bar_index == 8

    # Ensure historical freeze: expanding data to bar 10 does not alter swing 5's confirmed index
    swings_at_10 = find_swings(bars, last_closed_idx=10, k=3)
    assert len(swings_at_10) >= 1
    assert swings_at_10[0].bar_index == 5
    assert swings_at_10[0].price == 20.0
    assert swings_at_10[0].confirmed_bar_index == 8


def test_legs_and_two_leg_structures() -> None:
    # Zig-zag: Low at 2, High at 6, Low at 10, High at 14
    # Prices: 10 -> 20 -> 15 -> 25
    bars = []
    # Bar 0..18
    path = [
        12,
        11,
        10,
        13,
        16,
        19,
        20,
        18,
        16,
        14,
        15,
        18,
        21,
        24,
        25,
        23,
        20,
        19,
    ]
    for i, p in enumerate(path):
        bars.append(
            Bar(
                time=float(i * 60),
                open=p,
                high=p + 0.5,
                low=p - 0.5,
                close=p,
                index=i,
            )
        )

    swings = find_swings(bars, k=2)
    assert len(swings) >= 3

    legs = build_legs_from_swings(swings)
    assert len(legs) >= 2

    structures = detect_two_leg_structures(legs)
    for struct in structures:
        assert struct.leg1.direction == struct.leg2.direction
        assert struct.pullback_leg.direction != struct.leg1.direction
        assert struct.pullback_ratio > 0.0
