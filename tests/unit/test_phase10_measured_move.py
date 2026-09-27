"""Unit tests for Phase 10 Measured Move Engine."""

from __future__ import annotations

import json

from albrooks.core.legs import Leg
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.setups.measured_move import (
    detect_measured_moves,
    project_channel,
    project_gap,
    project_inverse,
    project_leg_equality,
    project_range,
)


def mk(o: float, h: float, low_val: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low_val, "c": c}


def sw(bar: int, price: float, direction: int, confirmed: int | None = None) -> dict:
    return {
        "bar": bar,
        "price": price,
        "dir": direction,
        "confirmed_bar": bar + 3 if confirmed is None else confirmed,
    }


# --------------------------------------------------------------------------
# Leg 1 = Leg 2 (regular)
# --------------------------------------------------------------------------


def test_leg_equality_bull_and_bear() -> None:
    cfg = AnalyzerConfig()
    atr = 2.0

    bull = project_leg_equality(sw(5, 90.0, -1), sw(12, 100.0, 1), sw(17, 95.0, -1), atr, cfg)
    assert bull is not None
    assert bull.family == "REGULAR" and bull.direction == 1
    assert bull.mm_range == 10.0
    assert bull.target_price == 105.0  # 95 + (100 - 90)
    assert bull.reference_price == 95.0
    assert bull.origin_bar == 5 and bull.anchor_bar == 17
    assert abs(bull.pullback_depth - 0.5) < 1e-9

    bear = project_leg_equality(sw(5, 110.0, 1), sw(12, 100.0, -1), sw(17, 105.0, 1), atr, cfg)
    assert bear is not None
    assert bear.direction == -1
    assert bear.target_price == 95.0  # 105 - (110 - 100)


def test_leg_equality_pullback_gates() -> None:
    cfg = AnalyzerConfig(min_pb_ratio=0.15, max_pb_ratio=0.90)
    a0, a1 = sw(5, 90.0, -1), sw(12, 100.0, 1)
    atr = 2.0

    # depth 0.10 < 0.15 -> too shallow for a regular pullback
    assert project_leg_equality(a0, a1, sw(17, 99.0, -1), atr, cfg) is None
    # depth 1.10 > 0.90 -> too deep (that is a new trend, not a pullback)
    assert project_leg_equality(a0, a1, sw(17, 89.0, -1), atr, cfg) is None
    # both boundaries are inclusive
    assert project_leg_equality(a0, a1, sw(17, 98.5, -1), atr, cfg) is not None
    assert project_leg_equality(a0, a1, sw(17, 91.0, -1), atr, cfg) is not None


def test_leg_equality_leg_size_and_order_gates() -> None:
    cfg = AnalyzerConfig(min_leg_bars=3, min_leg_atr=1.0)
    atr = 2.0

    short = (sw(5, 90.0, -1), sw(7, 100.0, 1), sw(17, 95.0, -1))
    assert project_leg_equality(*short, atr, cfg) is None
    tiny = (sw(5, 90.0, -1), sw(12, 91.0, 1), sw(17, 90.5, -1))
    assert project_leg_equality(*tiny, atr, cfg) is None
    unordered = (sw(20, 90.0, -1), sw(12, 100.0, 1), sw(17, 95.0, -1))
    assert project_leg_equality(*unordered, atr, cfg) is None
    wrong_polarity = (sw(5, 90.0, 1), sw(12, 100.0, 1), sw(17, 95.0, -1))
    assert project_leg_equality(*wrong_polarity, atr, cfg) is None
    # zero ATR never projects
    good = (sw(5, 90.0, -1), sw(12, 100.0, 1), sw(17, 95.0, -1))
    assert project_leg_equality(*good, 0.0, cfg) is None


# --------------------------------------------------------------------------
# Channel (shallow pullback only)
# --------------------------------------------------------------------------


def test_channel_shallow_only_and_mutually_exclusive() -> None:
    cfg = AnalyzerConfig(min_pb_ratio=0.15)
    a0, a1 = sw(5, 90.0, -1), sw(12, 100.0, 1)
    atr = 2.0

    shallow = sw(17, 99.0, -1)  # depth 0.10
    chan = project_channel(a0, a1, shallow, atr, cfg)
    assert chan is not None and chan.family == "CHANNEL" and chan.direction == 1
    assert chan.target_price == 109.0  # 99 + 10
    assert project_leg_equality(a0, a1, shallow, atr, cfg) is None

    # a regular-depth pullback is a CHANNEL reject
    assert project_channel(a0, a1, sw(17, 95.0, -1), atr, cfg) is None
    # no pullback at all (depth 0.0) is not a channel either
    assert project_channel(a0, a1, sw(17, 100.0, -1), atr, cfg) is None
    # channel can be disabled entirely
    assert project_channel(a0, a1, shallow, atr, AnalyzerConfig(enable_channel_mm=False)) is None


# --------------------------------------------------------------------------
# Range height projection
# --------------------------------------------------------------------------


def test_range_projection_bull_and_bear() -> None:
    cfg = AnalyzerConfig(enable_range_mm=True, range_lookback=10)
    atr = 1.0

    bars = [mk(100, 101, 99, 100) for _ in range(20)]
    bars[19] = mk(101, 102, 100.5, 102.5)  # close above the 10-bar high of 101
    bull = project_range(bars, 19, atr, cfg)
    assert bull is not None and bull.family == "RANGE" and bull.direction == 1
    assert bull.mm_range == 2.0  # HH 101 - LL 99
    assert bull.target_price == 104.5  # 102.5 + 2.0
    assert bull.reference_price == 102.5 and bull.anchor_bar == 19
    assert bull.origin_bar == 9

    bars[19] = mk(99, 99.5, 98, 97.5)  # close below the 10-bar low of 99
    bear = project_range(bars, 19, atr, cfg)
    assert bear is not None and bear.direction == -1
    assert bear.target_price == 95.5  # 97.5 - 2.0

    # inside the range -> no projection
    bars[19] = mk(100, 101, 99, 100)
    assert project_range(bars, 19, atr, cfg) is None


def test_range_projection_gates() -> None:
    cfg = AnalyzerConfig(range_lookback=10)
    atr = 1.0
    bars = [mk(100, 101, 99, 100) for _ in range(20)]

    # not enough history for the lookback window
    assert project_range(bars, 5, atr, cfg) is None
    # range height 2.0 < min_leg_atr 1.0 * atr 3.0
    assert project_range(bars, 19, 3.0, cfg) is None
    # family disabled
    off = AnalyzerConfig(range_lookback=10, enable_range_mm=False)
    assert project_range(bars, 19, atr, off) is None
    # degenerate inputs
    assert project_range(bars, 19, 0.0, cfg) is None
    assert project_range([], 0, atr, cfg) is None
    assert project_range(bars, -1, atr, cfg) is None


# --------------------------------------------------------------------------
# Measuring gap projection
# --------------------------------------------------------------------------


def test_gap_projection_bull_and_bear() -> None:
    cfg = AnalyzerConfig(enable_gap_mm=True, min_gap_atr=1.0)
    atr = 1.0

    bars = [mk(100, 101, 99, 100) for _ in range(10)]
    bars[9] = mk(102, 105, 101.5, 104.5)  # gaps above prior high, closes at the top
    bull = project_gap(bars, 9, atr, cfg)
    assert bull is not None and bull.family == "GAP" and bull.direction == 1
    assert bull.mm_range == 3.5  # close 104.5 - prior high 101.0
    assert bull.target_price == 108.0  # 104.5 + 3.5
    assert bull.reference_price == 104.5

    bars[9] = mk(98, 98.5, 96, 96.5)  # gaps below prior low, closes at the bottom
    bear = project_gap(bars, 9, atr, cfg)
    assert bear is not None and bear.direction == -1
    assert bear.mm_range == 2.5  # prior low 99.0 - close 96.5
    assert bear.target_price == 94.0  # 96.5 - 2.5


def test_gap_projection_gates() -> None:
    cfg = AnalyzerConfig(enable_gap_mm=True, min_gap_atr=1.0)
    atr = 1.0
    bars = [mk(100, 101, 99, 100) for _ in range(10)]

    # no gap away from the prior bar
    bars[9] = mk(100, 102, 99.5, 101.5)
    assert project_gap(bars, 9, atr, cfg) is None
    # strong close but the bar is not a gap
    bars[9] = mk(100, 101.2, 99.8, 101.0)
    assert project_gap(bars, 9, atr, cfg) is None
    # real gap but the bar is too narrow vs ATR
    assert project_gap(bars, 9, 5.0, cfg) is None
    # gap too small to matter (0.25 * atr floor)
    tight = [mk(100, 100.2, 99.8, 100) for _ in range(10)]
    tight[9] = mk(100.3, 100.6, 100.25, 100.55)
    assert project_gap(tight, 9, 1.0, cfg) is None
    # family disabled
    bars[9] = mk(102, 105, 101.5, 104.5)
    assert project_gap(bars, 9, atr, AnalyzerConfig(enable_gap_mm=False)) is None
    # index guards
    assert project_gap(bars, 0, atr, cfg) is None
    assert project_gap(bars, 99, atr, cfg) is None
    assert project_gap(bars, 9, 0.0, cfg) is None


# --------------------------------------------------------------------------
# Inverse projection (failed breakout of the leg extreme)
# --------------------------------------------------------------------------


def test_inverse_bull_leg_break_and_reclaim() -> None:
    cfg = AnalyzerConfig(failed_bo_bars=5)
    bars = [mk(100, 101, 99, 100) for _ in range(20)]
    # bull leg 90 -> 100; bar 13 closes above 100, bar 14 reclaims back below
    bars[13] = mk(100.5, 103.0, 100.2, 102.0)
    bars[14] = mk(100.0, 100.5, 99.0, 99.5)

    leg = {"start_index": 5, "end_index": 12, "start_price": 90.0, "end_price": 100.0}
    inv = project_inverse(bars, leg, 2.0, config=cfg)
    assert inv is not None and inv.family == "INVERSE" and inv.direction == -1
    assert inv.mm_range == 10.0
    assert inv.anchor_bar == 14
    # conservative anchor: low of the failure high bar (100.2) minus leg range
    assert abs(inv.reference_price - 100.2) < 1e-9
    assert abs(inv.target_price - 90.2) < 1e-9

    # same result when the leg arrives as a typed Leg object
    typed = Leg(
        start_index=5,
        end_index=12,
        start_price=90.0,
        end_price=100.0,
        direction=1,
        bars_count=7,
        price_change=10.0,
        confirmed_index=15,
    )
    inv2 = project_inverse(bars, typed, 2.0, config=cfg)
    assert inv2 is not None and inv2.to_dict() == inv.to_dict()


def test_inverse_bear_leg_break_and_reclaim() -> None:
    cfg = AnalyzerConfig(failed_bo_bars=5)
    bars = [mk(100, 101, 99, 100) for _ in range(20)]
    # bear leg 110 -> 100; bar 13 closes below 100, bar 14 reclaims back above
    bars[13] = mk(99.0, 99.5, 96.0, 97.0)
    bars[14] = mk(97.5, 100.5, 97.0, 100.2)

    leg = {"start_index": 5, "end_index": 12, "start_price": 110.0, "end_price": 100.0}
    inv = project_inverse(bars, leg, 2.0, config=cfg)
    assert inv is not None and inv.direction == 1
    assert inv.anchor_bar == 14
    # anchor is the HIGH of the failure low bar (99.5) plus leg range
    assert abs(inv.reference_price - 99.5) < 1e-9
    assert abs(inv.target_price - 109.5) < 1e-9


def test_inverse_requires_reclaim_within_window() -> None:
    cfg = AnalyzerConfig(failed_bo_bars=3)
    bars = [mk(100, 101, 99, 100) for _ in range(20)]
    leg = {"start_index": 5, "end_index": 12, "start_price": 90.0, "end_price": 100.0}

    # no break at all
    assert project_inverse(bars, leg, 2.0, config=cfg) is None

    # breaks but never reclaims
    bars[13] = mk(100.5, 103.0, 100.2, 102.0)
    for i in (14, 15, 16):
        bars[i] = mk(102, 104, 101.5, 103.0)
    assert project_inverse(bars, leg, 2.0, config=cfg) is None

    # reclaims only after the window expired
    bars[16] = mk(101, 101.5, 99.0, 99.5)
    assert project_inverse(bars, leg, 2.0, config=cfg) is None

    # reclaims inside the window -> valid
    bars[15] = mk(101, 101.5, 99.0, 99.5)
    assert project_inverse(bars, leg, 2.0, config=cfg) is not None

    # leg too small vs ATR
    small = {"start_index": 5, "end_index": 12, "start_price": 90.0, "end_price": 91.0}
    assert project_inverse(bars, small, 2.0, config=cfg) is None
    # family disabled
    assert project_inverse(bars, leg, 2.0, config=AnalyzerConfig(enable_inverse_mm=False)) is None
    # zero ATR
    assert project_inverse(bars, leg, 0.0, config=cfg) is None


# --------------------------------------------------------------------------
# Aggregation, no-lookahead and serialization
# --------------------------------------------------------------------------


def _range_plus_gap_series() -> list[dict[str, float]]:
    bars = [mk(100, 101, 99, 100) for _ in range(20)]
    bars[19] = mk(101, 105, 101.5, 104.5)  # range breakout + measuring gap in one bar
    return bars


def test_detect_measured_moves_aggregates_families() -> None:
    cfg = AnalyzerConfig(range_lookback=10, min_leg_atr=1.0, min_gap_atr=1.0)
    swings = [
        sw(5, 90.0, -1, confirmed=8),
        sw(10, 100.0, 1, confirmed=13),
        sw(14, 95.0, -1, confirmed=17),
    ]
    projs = detect_measured_moves(
        _range_plus_gap_series(), swings, atr=1.0, last_closed=19, config=cfg
    )
    families = {p.family for p in projs}
    assert families == {"REGULAR", "RANGE", "GAP"}

    by_family = {p.family: p for p in projs}
    assert by_family["REGULAR"].target_price == 105.0
    assert by_family["RANGE"].target_price == 106.5
    assert by_family["GAP"].target_price == 108.0
    # serializable for the LLM / dashboard layers
    payload = json.loads(json.dumps([p.to_dict() for p in projs]))
    assert {d["family"] for d in payload} == families


def test_detect_measured_moves_ignores_unconfirmed_swings() -> None:
    cfg = AnalyzerConfig(range_lookback=10)
    bars = _range_plus_gap_series()
    base = [sw(5, 90.0, -1, confirmed=8), sw(10, 100.0, 1, confirmed=13)]
    # the pullback swing is only confirmed on bar 20, so it must not be used at bar 19
    pending = base + [sw(14, 95.0, -1, confirmed=20)]

    at_19 = detect_measured_moves(bars, pending, atr=1.0, last_closed=19, config=cfg)
    assert not any(p.family == "REGULAR" for p in at_19)

    # same swing, confirmed in time -> the Leg1=Leg2 projection appears
    ready = base + [sw(14, 95.0, -1, confirmed=17)]
    at_19_ready = detect_measured_moves(bars, ready, atr=1.0, last_closed=19, config=cfg)
    regular = [p for p in at_19_ready if p.family == "REGULAR"]
    assert len(regular) == 1 and regular[0].target_price == 105.0

    # once bar 20 closes the pending swing becomes usable and matches exactly
    with_bar_20 = bars + [mk(104.5, 105, 104, 104.5)]
    at_20 = detect_measured_moves(with_bar_20, pending, atr=1.0, last_closed=20, config=cfg)
    resumed = [p for p in at_20 if p.family == "REGULAR"]
    assert len(resumed) == 1
    # same projection, only the recorded confirmation bar of B0 differs
    assert (resumed[0].direction, resumed[0].target_price) == (
        regular[0].direction,
        regular[0].target_price,
    )
    assert (resumed[0].origin_bar, resumed[0].anchor_bar) == (5, 14)

    # last_closed beyond the available data is clamped, never an error
    clamped = detect_measured_moves(bars, pending, atr=1.0, last_closed=999, config=cfg)
    assert [p.to_dict() for p in clamped] == [p.to_dict() for p in at_19]


def test_detect_measured_moves_is_free_of_lookahead() -> None:
    cfg = AnalyzerConfig(range_lookback=10)
    bars = _range_plus_gap_series()
    swings = [
        sw(5, 90.0, -1, confirmed=8),
        sw(10, 100.0, 1, confirmed=13),
        sw(14, 95.0, -1, confirmed=17),
        sw(24, 110.0, 1, confirmed=27),  # a swing that only exists in the future
    ]

    base = detect_measured_moves(bars, swings, atr=1.0, last_closed=19, config=cfg)
    # a range that later breaks out, well after bar 19
    future = bars + [mk(105, 106, 104, 105) for _ in range(11)]
    future.append(mk(105, 108, 105, 107.5))

    after_future = detect_measured_moves(future, swings, atr=1.0, last_closed=19, config=cfg)
    assert [p.to_dict() for p in base] == [p.to_dict() for p in after_future]

    # and the newest-bar families do move once later bars actually close
    extended = detect_measured_moves(future, swings, atr=1.0, last_closed=31, config=cfg)
    assert any(p.family == "RANGE" and p.anchor_bar == 31 for p in extended)


def test_detect_measured_moves_degenerate_inputs() -> None:
    cfg = AnalyzerConfig()
    flat = [mk(100, 100.01, 99.99, 100) for _ in range(30)]
    assert detect_measured_moves(flat, [], atr=0.0, config=cfg) == []
    assert detect_measured_moves([], [], atr=1.0, config=cfg) == []
    assert detect_measured_moves(flat, [], atr=1.0, last_closed=-1, config=cfg) == []
    # last_closed beyond the data is clamped, not an error
    assert isinstance(detect_measured_moves(flat, [], atr=1.0, last_closed=999, config=cfg), list)


def _inverse_series() -> list[dict[str, float]]:
    """A swing low at 4, a confirmed swing high at 10, then break + reclaim."""
    rows = [
        (99.0, 98.5, 98.0, 98.5),
        (98.5, 98.0, 97.5, 98.0),
        (98.0, 97.5, 97.0, 97.5),
        (97.5, 97.0, 96.5, 97.0),
        (96.8, 96.0, 95.0, 95.2),
        (97.0, 96.8, 95.8, 96.8),
        (97.5, 97.2, 96.5, 97.2),
        (98.0, 97.8, 97.2, 97.8),
        (99.0, 98.8, 98.2, 98.8),
        (99.5, 99.2, 99.0, 99.4),
        (100.0, 99.8, 99.2, 99.8),  # swing high, confirmed on bar 13
        (99.6, 99.0, 98.5, 99.0),
        (99.2, 98.5, 98.0, 98.5),
        (99.0, 98.0, 97.5, 98.0),
        (103.0, 102.0, 100.2, 102.0),  # closes above the 99.8 swing high
        (100.5, 99.5, 99.0, 99.5),  # reclaims back below it
    ]
    return [mk(*r) for r in rows]


def test_detect_measured_moves_finds_channel() -> None:
    swings = [sw(5, 90.0, -1, 8), sw(12, 100.0, 1, 15), sw(17, 99.0, -1, 20)]
    flat = [mk(95, 96, 94, 95) for _ in range(30)]
    projs = detect_measured_moves(flat, swings, atr=2.0, last_closed=29)
    assert [p.family for p in projs] == ["CHANNEL"]
    assert projs[0].direction == 1 and projs[0].target_price == 109.0
    # a deeper pullback of the same triple is a REGULAR projection instead
    regular_swings = [sw(5, 90.0, -1, 8), sw(12, 100.0, 1, 15), sw(17, 95.0, -1, 20)]
    projs = detect_measured_moves(flat, regular_swings, atr=2.0, last_closed=29)
    assert [p.family for p in projs] == ["REGULAR"]
    assert projs[0].target_price == 105.0


def test_detect_measured_moves_finds_inverse() -> None:
    from albrooks.core.swings import find_swings

    bars = _inverse_series()
    last = len(bars) - 1
    swings = find_swings(bars, last, 3)
    assert [(s.bar_index, s.direction) for s in swings] == [(4, -1), (10, 1)]

    cfg = AnalyzerConfig(enable_range_mm=False, enable_gap_mm=False)
    projs = detect_measured_moves(bars, swings, atr=2.0, last_closed=last, config=cfg)
    assert [p.family for p in projs] == ["INVERSE"]
    inv = projs[0]
    assert inv.direction == -1 and inv.anchor_bar == 15
    # leg range 99.8 - 95.0, anchored at the low of the failure high bar (100.2)
    assert abs(inv.mm_range - 4.8) < 1e-9
    assert abs(inv.target_price - 95.4) < 1e-9
