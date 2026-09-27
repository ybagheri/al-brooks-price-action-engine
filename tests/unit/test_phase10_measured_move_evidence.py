"""Evidence, confidence and reference-leg tests for the Measured Move engine.

The existing Phase 10 suite pins the projection *geometry*. These tests pin the
*reasoning* the engine now reports alongside each projection: which leg it measured
from, where the target is measured off, and the evidence behind its confidence.

The load-bearing property is that `confidence` is always exactly the mean of the
stored evidence weights. If that ever stops holding, the scalar becomes a
free-floating number that no longer describes its own inputs, and a caller reading
only the scalar would be misled.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from albrooks.engine.configuration import AnalyzerConfig
from albrooks.setups.measured_move import (
    CHANNEL_MIN_DEPTH,
    EV_BREAKOUT_MARGIN,
    EV_FAILURE_DEPTH,
    EV_GAP_QUALITY,
    EV_PULLBACK_BAND,
    EV_SCALE,
    MeasuredMoveProjection,
    MMFamily,
    detect_measured_moves,
    project_channel,
    project_gap,
    project_inverse,
    project_leg_equality,
    project_range,
)
from albrooks.setups.measured_move_types import (
    MeasuredMoveEvidence,
    MeasuredMoveLeg,
    MeasuredMoveOrigin,
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


def _weights(p: MeasuredMoveProjection) -> list[float]:
    return [e.weight for e in p.evidence]


def _factor(p: MeasuredMoveProjection, code: str) -> float:
    """The weight of a single named evidence factor."""
    return next(e.weight for e in p.evidence if e.code == code)


LEG = {"start_index": 5, "end_index": 12, "start_price": 90.0, "end_price": 100.0}


def _inverse_bars(reclaim_close: float = 99.5) -> list[dict[str, float]]:
    """A 90 -> 100 leg, a break above 100 on bar 13, a reclaim on bar 14."""
    bars = [mk(100, 101, 99, 100) for _ in range(20)]
    bars[13] = mk(100.5, 103.0, 100.2, 102.0)
    bars[14] = mk(100.0, 100.5, 99.0, reclaim_close)
    return bars


def _all_projections() -> list[MeasuredMoveProjection]:
    """One live projection of every family, from five separate scenarios."""
    cfg = AnalyzerConfig(range_lookback=10)
    atr = 1.0

    regular = project_leg_equality(
        sw(5, 90.0, -1), sw(12, 100.0, 1), sw(17, 95.0, -1), atr, cfg
    )
    channel = project_channel(
        sw(5, 90.0, -1), sw(12, 100.0, 1), sw(17, 99.0, -1), atr, cfg
    )

    range_bars = [mk(100, 101, 99, 100) for _ in range(20)]
    range_bars[19] = mk(101, 102, 100.5, 102.5)
    rng = project_range(range_bars, 19, atr, cfg)

    gap_bars = [mk(100, 101, 99, 100) for _ in range(10)]
    gap_bars[9] = mk(102, 105, 101.5, 104.5)
    gap = project_gap(gap_bars, 9, atr, cfg)

    inv = project_inverse(_inverse_bars(), LEG, 2.0, config=cfg)

    return [regular, channel, rng, gap, inv]


# --------------------------------------------------------------------------
# Confidence is derived, never asserted independently
# --------------------------------------------------------------------------


def test_confidence_is_exactly_the_mean_of_its_evidence() -> None:
    for p in _all_projections():
        assert p is not None
        expected = sum(_weights(p)) / len(p.evidence)
        assert abs(p.confidence - expected) < 1e-12, p.family


def test_every_family_reports_scale_plus_exactly_one_structure_factor() -> None:
    """One scale factor, plus the one structure factor that family actually has.

    A family is not penalised for having a single structure factor: confidence is the
    mean of the factors that exist, not a fixed-length sum.
    """
    own = {
        "REGULAR": EV_PULLBACK_BAND,
        "CHANNEL": EV_PULLBACK_BAND,
        "RANGE": EV_BREAKOUT_MARGIN,
        "GAP": EV_GAP_QUALITY,
        "INVERSE": EV_FAILURE_DEPTH,
    }
    for p in _all_projections():
        assert p is not None
        codes = [e.code for e in p.evidence]
        assert codes == [EV_SCALE, own[p.family]], p.family
        assert len(p.evidence) == 2
        # a repeated code would double-count in the mean
        assert len(set(codes)) == len(codes), p.family


def test_the_target_is_one_measured_range_from_the_reference() -> None:
    """Why there is deliberately no "distance to target" evidence factor.

    In every family the target sits exactly one measured range from the reference
    price, so such a factor is `mm_range` restated with a different constant: two
    names for one number, whose apparent independence from the scale factor is an
    artefact of the arithmetic rather than a second opinion. This test pins the
    relationship, so reintroducing the duplicate has to be a conscious decision.
    """
    for p in _all_projections():
        assert p is not None
        assert abs(abs(p.target_price - p.reference_price) - p.mm_range) < 1e-9
        # the scale factor is the ramped measured range, against SCALE_FULL_ATR
        expected = min(max(p.mm_range / (2.0 * 1.0), 0.0), 1.0)
        assert abs(_factor(p, EV_SCALE) - expected) < 1e-12


def test_every_weight_and_confidence_is_within_the_unit_interval() -> None:
    for p in _all_projections():
        assert p is not None
        for w in _weights(p):
            assert 0.0 <= w <= 1.0, (p.family, w)
        assert 0.0 <= p.confidence <= 1.0, p.family


# --------------------------------------------------------------------------
# Each factor responds to the thing it claims to measure
# --------------------------------------------------------------------------


def test_scale_factor_grows_with_the_measured_range() -> None:
    cfg = AnalyzerConfig(min_leg_atr=0.0, min_pb_ratio=0.0, max_pb_ratio=1.0)
    atr = 1.0
    # identical leg length and bar count; only the leg's size differs
    small = project_leg_equality(
        sw(5, 100.0, -1), sw(12, 101.0, 1), sw(17, 100.5, -1), atr, cfg
    )
    large = project_leg_equality(
        sw(5, 100.0, -1), sw(12, 110.0, 1), sw(17, 105.0, -1), atr, cfg
    )
    assert small is not None and large is not None
    assert _factor(large, EV_SCALE) > _factor(small, EV_SCALE)
    # the ramp saturates rather than running away on a large leg
    assert _factor(large, EV_SCALE) == 1.0


def test_pullback_band_factor_peaks_mid_band_and_is_zero_at_the_edges() -> None:
    cfg = AnalyzerConfig(min_pb_ratio=0.20, max_pb_ratio=0.80)
    atr = 1.0

    def band(pullback_price: float) -> float:
        # leg 90 -> 100, so depth = (100 - pullback) / 10
        p = project_leg_equality(
            sw(5, 90.0, -1), sw(12, 100.0, 1), sw(17, pullback_price, -1), atr, cfg
        )
        assert p is not None
        return _factor(p, EV_PULLBACK_BAND)

    assert band(95.0) == 1.0  # depth 0.50, the centre of [0.20, 0.80]
    # Either gate boundary scores zero, not a small positive value: sitting exactly
    # on a limit is the same as being outside the band, not a graded near-miss.
    assert abs(band(98.0)) < 1e-12  # depth 0.20
    assert abs(band(92.0)) < 1e-12  # depth 0.80
    assert 0.0 < band(96.0) < 1.0  # depth 0.40
    assert 0.0 < band(94.0) < 1.0  # depth 0.60


def test_channel_scores_against_its_own_shallow_band_not_the_regular_one() -> None:
    """A depth is only comparable to the band of the family that accepted it."""
    cfg = AnalyzerConfig(min_pb_ratio=0.15)
    p = project_channel(
        sw(5, 90.0, -1), sw(12, 100.0, 1), sw(17, 99.0, -1), 1.0, cfg
    )
    assert p is not None
    depth = p.pullback_depth
    assert abs(depth - 0.10) < 1e-9
    # 0.10 sits near the middle of the channel's [0.02, 0.15] band, so it scores well
    assert _factor(p, EV_PULLBACK_BAND) > 0.5
    # the same depth against the regular band [0.15, 0.90] would be far outside it
    mid, half = (0.15 + 0.90) / 2, (0.90 - 0.15) / 2
    assert 1.0 - abs(depth - mid) / half < 0.0
    # the channel gate's lower bound is the same constant the evidence band starts at
    assert CHANNEL_MIN_DEPTH == 0.02


def test_gap_quality_factor_rewards_closing_on_the_extreme() -> None:
    cfg = AnalyzerConfig(min_gap_atr=1.0)
    atr = 1.0

    def quality(close: float) -> float:
        p = project_gap_quality(close)
        assert p is not None
        return _factor(p, EV_GAP_QUALITY)

    def project_gap_quality(close: float):
        bars = [mk(100, 101, 99, 100) for _ in range(10)]
        bars[9] = mk(102, 105, 101.5, close)
        return project_gap(bars, 9, atr, cfg)

    # The gate requires (close - 101.5) / 3.5 >= 0.75, i.e. a close at or above
    # 104.125. A close of 102.0 sits at 14% of the bar and is rejected outright, so
    # the graded range runs only from the gate up to the high of 105.0.
    assert project_gap_quality(102.0) is None
    at_gate = quality(104.125)
    assert abs(at_gate) < 1e-12
    assert quality(105.0) == 1.0  # closes on the high
    assert quality(105.0) > quality(104.5) > at_gate


def test_failure_depth_factor_grows_with_the_reclaim_through_the_extreme() -> None:
    def depth(reclaim_close: float) -> float:
        p = project_inverse(_inverse_bars(reclaim_close), LEG, 2.0)
        assert p is not None
        return _factor(p, EV_FAILURE_DEPTH)

    assert depth(99.0) > depth(99.9)  # a deeper reclaim scores higher
    assert depth(99.0) == 1.0


def test_weights_are_relative_not_probabilities() -> None:
    """The docstring's central claim, asserted rather than merely written.

    Weights rank factors against each other, so two strong factors may sum above
    1.0. A future change that normalised them to sum to 1 would quietly turn the
    number into a probability; this test fails and forces that decision.
    """
    summed_above_one = False
    for p in _all_projections():
        assert p is not None
        # a mean, not a sum
        assert p.confidence == sum(_weights(p)) / 2
        summed_above_one |= sum(_weights(p)) > 1.0
    # the case that makes the distinction observable rather than theoretical
    assert summed_above_one


# --------------------------------------------------------------------------
# Reference leg: which geometry was measured, and in which direction
# --------------------------------------------------------------------------


def test_swing_families_report_the_a0_a1_leg_they_measured_from() -> None:
    p = project_leg_equality(
        sw(5, 90.0, -1, 8), sw(12, 100.0, 1, 15), sw(17, 95.0, -1, 20), 2.0, AnalyzerConfig()
    )
    assert p is not None and p.reference_leg is not None
    leg = p.reference_leg
    assert leg.kind == "SWING"
    assert (leg.start_index, leg.end_index) == (5, 12)
    assert (leg.start_price, leg.end_price) == (90.0, 100.0)
    assert leg.direction == 1
    assert leg.size == 10.0 == p.mm_range
    # the reference carries its own confirmation bar, so a caller can audit the
    # no-lookahead claim for the leg and not only for the swings it already holds
    assert leg.confirmed_index == 15
    assert leg.label == "A0->A1"


def test_range_family_reports_the_window_and_leaves_direction_unset() -> None:
    cfg = AnalyzerConfig(range_lookback=10)
    bars = [mk(100, 101, 99, 100) for _ in range(20)]
    bars[19] = mk(101, 102, 100.5, 102.5)
    p = project_range(bars, 19, 1.0, cfg)
    assert p is not None and p.reference_leg is not None
    leg = p.reference_leg
    assert leg.kind == "RANGE"
    assert (leg.start_index, leg.end_index) == (9, 18)
    assert (leg.start_price, leg.end_price) == (99.0, 101.0)
    assert leg.size == 2.0
    # A range is two-sided. Recording a direction here would be a fabricated edge;
    # the projection's own direction lives on the projection.
    assert leg.direction == 0
    assert p.direction == 1
    assert leg.confirmed_index == 18


def test_gap_family_reports_the_prior_extreme_and_the_gap_bar() -> None:
    bars = [mk(100, 101, 99, 100) for _ in range(10)]
    bars[9] = mk(102, 105, 101.5, 104.5)
    p = project_gap(bars, 9, 1.0, AnalyzerConfig(min_gap_atr=1.0))
    assert p is not None and p.reference_leg is not None
    leg = p.reference_leg
    assert leg.kind == "GAP"
    assert (leg.start_index, leg.end_index) == (8, 9)
    assert leg.start_price == 101.0  # the prior high the gap cleared
    assert leg.end_price == 101.5  # the gap bar's own low
    assert leg.direction == 1
    assert leg.size == 3.5 == p.mm_range


def test_inverse_reports_the_leg_whose_extreme_failed() -> None:
    p = project_inverse(_inverse_bars(), LEG, 2.0)
    assert p is not None and p.reference_leg is not None
    leg = p.reference_leg
    assert leg.kind == "INVERSE"
    assert (leg.start_index, leg.end_index) == (5, 12)
    assert (leg.start_price, leg.end_price) == (90.0, 100.0)
    # the leg's own direction, which is the opposite of the projection it produces
    assert leg.direction == 1
    assert p.direction == -1


def test_every_family_populates_a_reference_leg_and_an_origin() -> None:
    kinds = {
        "SWING": {"REGULAR", "CHANNEL"},
        "RANGE": {"RANGE"},
        "GAP": {"GAP"},
        "INVERSE": {"INVERSE"},
    }
    seen: set[str] = set()
    for p in _all_projections():
        assert p is not None
        assert p.reference_leg is not None and p.origin is not None
        assert p.reference_leg.kind in kinds
        assert p.family in kinds[p.reference_leg.kind], p.family
        # the leg must be a real span, not a placeholder
        assert p.reference_leg.end_index > p.reference_leg.start_index
        assert p.reference_leg.size > 0
        seen.add(p.reference_leg.kind)
    assert seen == set(kinds)


# --------------------------------------------------------------------------
# Origin: where the target is measured from
# --------------------------------------------------------------------------


def test_origin_records_the_bar_and_price_the_target_is_measured_from() -> None:
    swing = project_leg_equality(
        sw(5, 90.0, -1, 8), sw(12, 100.0, 1, 15), sw(17, 95.0, -1, 20), 2.0, AnalyzerConfig()
    )
    assert swing is not None and swing.origin is not None
    assert swing.origin.kind == "SWING"
    assert swing.origin.bar_index == 17
    assert swing.origin.price == 95.0
    # the target is exactly one measured range from the origin, along the direction
    expected = swing.origin.price + swing.direction * swing.mm_range
    assert abs(swing.target_price - expected) < 1e-9

    bars = [mk(100, 101, 99, 100) for _ in range(10)]
    bars[9] = mk(102, 105, 101.5, 104.5)
    gap = project_gap(bars, 9, 1.0, AnalyzerConfig())
    assert gap is not None and gap.origin is not None
    assert gap.origin.kind == "GAP_CLOSE"
    assert (gap.origin.bar_index, gap.origin.price) == (9, 104.5)

    inv = project_inverse(_inverse_bars(), LEG, 2.0)
    assert inv is not None and inv.origin is not None
    assert inv.origin.kind == "FAILURE"
    assert inv.origin.bar_index == 14


# --------------------------------------------------------------------------
# Serialization and structural guarantees
# --------------------------------------------------------------------------


def test_evidence_survives_serialization_as_plain_json() -> None:
    """Phase 22 hands these straight to an LLM, so no dataclass may leak through."""
    projs = detect_measured_moves(
        [mk(100, 101, 99, 100) for _ in range(20)],
        [sw(5, 90.0, -1, 8), sw(10, 100.0, 1, 13), sw(14, 95.0, -1, 17)],
        atr=1.0,
        last_closed=19,
        config=AnalyzerConfig(range_lookback=10),
    )
    assert projs, "expected at least one projection"
    payload = json.loads(json.dumps([p.to_dict() for p in projs]))
    for entry in payload:
        assert isinstance(entry["confidence"], float)
        assert isinstance(entry["evidence"], list)
        assert entry["evidence"], "a found projection must carry its evidence"
        for item in entry["evidence"]:
            assert isinstance(item, dict)
            assert set(item) == {"code", "weight", "detail"}
            assert isinstance(item["weight"], float)
            assert item["detail"], "every factor explains itself in words"
        assert entry["reference_leg"] is not None
        assert set(entry["reference_leg"]) == {
            "kind", "start_index", "end_index", "start_price", "end_price",
            "direction", "size", "confirmed_index", "label",
        }
        assert entry["origin"] is not None
        assert set(entry["origin"]) == {"bar_index", "price", "kind"}


def test_the_default_projection_claims_no_evidence() -> None:
    """The no-projection default must not be mistaken for a scored one."""
    blank = MeasuredMoveProjection()
    assert blank.found is False
    assert blank.evidence == ()
    assert blank.confidence == 0.0
    assert blank.reference_leg is None
    assert blank.origin is None
    assert blank.family == "NONE"


def test_evidence_types_are_immutable_value_objects() -> None:
    leg = MeasuredMoveLeg(kind="SWING", start_index=1, end_index=2)
    origin = MeasuredMoveOrigin(bar_index=3, price=1.0, kind="SWING")
    item = MeasuredMoveEvidence(EV_SCALE, 0.5, "detail")
    # hashable, so evidence can key a set or a cache without defensive copying
    assert len({leg, MeasuredMoveLeg(kind="SWING", start_index=1, end_index=2)}) == 1
    assert hash(origin) and hash(item)
    for obj, attr in ((leg, "start_index"), (origin, "price"), (item, "weight")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(obj, attr, 99)


def test_confidence_is_deterministic_and_free_of_lookahead() -> None:
    """The evidence must depend on closed bars only, like the geometry does."""
    cfg = AnalyzerConfig(range_lookback=10)
    bars = [mk(100, 101, 99, 100) for _ in range(20)]
    swings = [
        sw(5, 90.0, -1, 8),
        sw(10, 100.0, 1, 13),
        sw(14, 95.0, -1, 17),
        sw(24, 110.0, 1, 27),  # a swing that only exists in the future
    ]
    base = detect_measured_moves(bars, swings, atr=1.0, last_closed=19, config=cfg)
    assert base
    future = bars + [mk(104.5, 108, 104, 107.5) for _ in range(12)]
    after = detect_measured_moves(future, swings, atr=1.0, last_closed=19, config=cfg)
    assert [(p.family, p.confidence, p.to_dict()) for p in base] == [
        (p.family, p.confidence, p.to_dict()) for p in after
    ]
    # and repeating the same call reproduces it bit for bit
    again = detect_measured_moves(bars, swings, atr=1.0, last_closed=19, config=cfg)
    assert [p.to_dict() for p in again] == [p.to_dict() for p in base]


def test_atr_scales_the_confidence_rather_than_changing_the_target() -> None:
    """ATR is a unit of measure here, not an input to the geometry.

    A doubled ATR leaves every target untouched and only re-scales the evidence, so
    a projection's price cannot silently depend on the volatility reference chosen.
    """
    swings = (sw(5, 90.0, -1), sw(12, 100.0, 1), sw(17, 95.0, -1))
    low_vol = project_leg_equality(*swings, 2.0, AnalyzerConfig())
    high_vol = project_leg_equality(*swings, 8.0, AnalyzerConfig())
    assert low_vol is not None and high_vol is not None
    assert low_vol.target_price == high_vol.target_price == 105.0
    assert low_vol.mm_range == high_vol.mm_range == 10.0
    # a 10.0 range is 5 ATR at the first reference and 1.25 ATR at the second
    assert _factor(low_vol, EV_SCALE) == 1.0
    assert _factor(high_vol, EV_SCALE) < 1.0
    assert low_vol.confidence > high_vol.confidence


def test_every_family_in_the_enum_reports_evidence() -> None:
    """A new family that skipped the evidence model would be caught here."""
    assert {p.family for p in _all_projections()} == {f.value for f in MMFamily}


def test_origin_never_looks_past_the_projection_anchor() -> None:
    """The no-lookahead rule applied to the evidence, not only the geometry."""
    for p in _all_projections():
        assert p is not None and p.origin is not None
        assert p.origin.bar_index <= p.anchor_bar, p.family
        if p.reference_leg is not None and p.reference_leg.confirmed_index >= 0:
            assert p.reference_leg.confirmed_index <= p.anchor_bar, p.family
