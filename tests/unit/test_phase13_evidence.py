"""Tests for the setup evidence model (Phase 13).

The engine reports *why* something fired in five different vocabularies, and
before this phase the only place that met them was `Analyzer._evidence()`, which
produced entries where four of the five sources had **no `weight` key at all**.

These tests pin the three properties that make a unified number defensible:

1. **A factor says why its number is that number.** `MEASURED`, `LIFECYCLE` and
   `ASSERTED` are different kinds of claim, and collapsing them would invent
   precision the underlying layers do not have. `CONFIRMED` is not "0.75
   confirmed", and an unquantified observation is not "measured, and came out 0".
2. **The score is reproducible from its own factors.** It is a pure function of
   the bundle, so it can never drift away from the evidence it claims to
   summarise.
3. **Absence is never dressed up as weakness.** No evidence is `NONE`, an
   invalidated pullback is excluded rather than scored low, and a bundle built
   only from assertions is flagged as unquantified.

The aggregate is checked against hand-computed means rather than against
whatever the implementation happens to produce, so a change in the arithmetic
has to be deliberate.
"""

from __future__ import annotations

import json

import pytest

from albrooks.engine.configuration import AnalyzerConfig
from albrooks.evaluation.evidence import (
    KNOWN_SOURCES,
    UNQUANTIFIED_WEIGHT,
    EvidenceBasis,
    EvidenceBundle,
    EvidenceFactor,
    clamp01,
    from_breakout,
    from_fading_measured_move,
    from_market_state,
    from_measured_move,
    from_pullback,
    from_reversal,
)
from albrooks.evaluation.scoring import (
    BAND_MODERATE,
    BAND_NONE,
    BAND_STRONG,
    BAND_WEAK,
    WARN_NO_EVIDENCE,
    WARN_PARTIAL_QUANTIFIED,
    WARN_SINGLE_SOURCE,
    WARN_UNQUANTIFIED_ONLY,
    band,
    compare,
    measured_only,
    score,
)
from albrooks.setups.reversal import ReversalQuality

CFG = AnalyzerConfig(range_lookback=20)


def measured(code: str, weight: float, source: str = "MEASURED_MOVE") -> EvidenceFactor:
    return EvidenceFactor(
        source=source, code=code, weight=weight, basis=EvidenceBasis.MEASURED
    )


def lifecycle(code: str, weight: float, source: str = "PULLBACK") -> EvidenceFactor:
    return EvidenceFactor(
        source=source, code=code, weight=weight, basis=EvidenceBasis.LIFECYCLE
    )


def asserted(code: str, source: str = "BREAKOUT") -> EvidenceFactor:
    return EvidenceFactor(source=source, code=code, basis=EvidenceBasis.ASSERTED)


def bundle(*factors: EvidenceFactor, subject: str = "TEST") -> EvidenceBundle:
    return EvidenceBundle(subject=subject, factors=tuple(factors))


# --------------------------------------------------------------------------
# EvidenceFactor
# --------------------------------------------------------------------------


def test_a_factor_records_why_its_number_is_that_number() -> None:
    """The load-bearing field. A number without a basis is a lie waiting to happen."""
    assert measured("MM_SCALE", 1.0).basis is EvidenceBasis.MEASURED
    assert lifecycle("CONFIRMED", 1.0).basis is EvidenceBasis.LIFECYCLE
    assert asserted("BREAKOUT_TRAP").basis is EvidenceBasis.ASSERTED


def test_only_a_measured_factor_counts_as_quantified() -> None:
    """A lifecycle position is not a measurement, however confident it looks."""
    assert measured("X", 1.0).is_quantified
    assert not lifecycle("CONFIRMED", 1.0).is_quantified
    assert not asserted("TRAP").is_quantified


@pytest.mark.parametrize(
    ("raw", "expected"), [(-1.0, 0.0), (0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (2.0, 1.0)]
)
def test_a_weight_outside_the_unit_interval_is_clamped(raw: float, expected: float) -> None:
    assert measured("X", raw).weight == expected


def test_a_nan_weight_becomes_zero_rather_than_poisoning_an_average() -> None:
    """NaN compares False against 0, so it would pass a `> 0` check and then
    make the whole mean NaN."""
    assert measured("X", float("nan")).weight == 0.0
    assert score(bundle(measured("A", 1.0), measured("B", float("nan")))).value == 0.5


def test_clamp01_handles_nan_and_the_ends() -> None:
    assert clamp01(float("nan")) == 0.0
    assert clamp01(-5.0) == 0.0
    assert clamp01(5.0) == 1.0
    assert clamp01(0.25) == 0.25


def test_an_asserted_factor_is_never_recorded_as_zero() -> None:
    """A zero would claim "measured, and came out nil", and would drag an
    average down as though it were a negative observation."""
    factor = asserted("RANGE_TIGHTENING_COMPRESSION")
    assert factor.weight == UNQUANTIFIED_WEIGHT
    assert factor.weight > 0.0
    assert not factor.is_quantified


def test_a_factor_serialises_with_its_basis() -> None:
    """`basis` travels with the number, so a consumer is not left guessing."""
    payload = json.loads(json.dumps(measured("MM_SCALE", 0.75).to_dict()))
    assert payload == {
        "source": "MEASURED_MOVE",
        "code": "MM_SCALE",
        "weight": 0.75,
        "basis": "MEASURED",
        "family": "",
        "detail": "",
    }


def test_a_factor_is_immutable() -> None:
    """Evidence is a record of what was observed; it must not be edited."""
    with pytest.raises(Exception):
        measured("X", 1.0).weight = 0.0  # type: ignore[misc]


# --------------------------------------------------------------------------
# EvidenceBundle
# --------------------------------------------------------------------------


def test_a_bundle_groups_its_factors_by_source() -> None:
    grouped = bundle(measured("A", 1.0), lifecycle("B", 0.5), measured("C", 0.2)).by_source()
    assert {k: [f.code for f in v] for k, v in grouped.items()} == {
        "MEASURED_MOVE": ["A", "C"],
        "PULLBACK": ["B"],
    }


def test_quantified_share_is_the_fraction_that_was_measured() -> None:
    b = bundle(measured("A", 1.0), lifecycle("B", 1.0), asserted("C"))
    assert b.quantified_share == pytest.approx(1 / 3)


def test_quantified_share_is_one_when_everything_was_measured() -> None:
    assert bundle(measured("A", 1.0), measured("B", 0.2)).quantified_share == 1.0


def test_quantified_share_of_an_empty_bundle_is_zero_not_a_division_error() -> None:
    """An empty bundle has no measured evidence in it, which is the honest reading."""
    assert bundle().quantified_share == 0.0


def test_a_bundle_is_iterable_and_sized() -> None:
    b = bundle(measured("A", 1.0), measured("B", 0.5))
    assert len(b) == 2
    assert [f.code for f in b] == ["A", "B"]


def test_a_bundle_serialises() -> None:
    payload = json.loads(json.dumps(bundle(measured("A", 1.0), subject="X").to_dict()))
    assert payload["subject"] == "X"
    assert payload["factors"][0]["code"] == "A"


# --------------------------------------------------------------------------
# Adapters read a payload as readily as a model
# --------------------------------------------------------------------------


def test_the_measured_move_adapter_reads_a_payload_as_well_as_a_model() -> None:
    """Added in Phase 15, which found the gap.

    Every detector's public path is `to_dict()`: the setup registry hands findings
    around as plain dicts and `Analyzer.analyze()` reports them as dicts, so an
    adapter that only understood objects could not reach the measured-move evidence
    at all. The object is still preferred, so nothing changes for a caller passing
    a real `MeasuredMoveProjection`.
    """
    payload = {
        "found": True,
        "family": "RANGE",
        "direction": 1,
        "evidence": [
            {"code": "MM_SCALE", "weight": 0.8, "detail": "3.1 ATR"},
            {"code": "MM_BREAKOUT_MARGIN", "weight": 0.4, "detail": ""},
        ],
    }

    factors = from_measured_move(payload)

    assert [f.code for f in factors] == ["MM_SCALE", "MM_BREAKOUT_MARGIN"]
    assert factors[0].weight == pytest.approx(0.8)
    assert factors[0].family == "RANGE"
    assert all(f.basis is EvidenceBasis.MEASURED for f in factors)


def test_the_reversal_adapter_reads_a_payload_as_well_as_a_model() -> None:
    payload = {
        "verdict": "MAJOR",
        "direction": -1,
        "score": 100,
        "satisfied": ["EMA_BREAK", "RETEST"],
        "missing": ["BO_FOLLOW"],
    }

    factors = from_reversal(payload)

    assert [f.code for f in factors] == ["EMA_BREAK", "RETEST", "VERDICT_MAJOR"]
    assert all(f.weight == 1.0 for f in factors)
    assert "-1" in factors[-1].detail


def test_a_payload_and_its_model_normalise_identically() -> None:
    """The point of reading both is that they are not two vocabularies."""
    payload = {
        "verdict": "MINOR",
        "direction": 1,
        "satisfied": ["EMA_BREAK"],
        "missing": [],
    }
    model = ReversalQuality(
        verdict="MINOR", direction=1, satisfied=["EMA_BREAK"], missing=[]
    )

    assert from_reversal(payload) == from_reversal(model)


def test_a_fade_normalises_as_its_projection_evidence_plus_its_lifecycle() -> None:
    """Added in Phase 16, which found two real problems at once.

    A `FadingSetup` carries no factors of its own, so without unwrapping
    `projection` its bundle held nothing but the shared market-state factors — and
    because `score()` averages within each source, a single-source bundle scores
    that source's value outright. A fade was scoring 100 ppts on market context
    alone. The lifecycle factor is what also makes a fade distinguishable from the
    measured move it fades; without it the two scored identically and the decision
    layer reported a zero-width `EVIDENCE_CONFLICT` on every strong projection.
    """
    payload = {
        "family": "RANGE",
        "fade_direction": -1,
        "state": "POTENTIAL",
        "projection": {
            "family": "RANGE",
            "direction": 1,
            "evidence": [{"code": "MM_SCALE", "weight": 0.8, "detail": "3.1 ATR"}],
        },
    }

    factors = from_fading_measured_move(payload)

    assert [f.code for f in factors] == ["MM_SCALE", "POTENTIAL"]
    assert {f.source for f in factors} == {"FADING_MEASURED_MOVE"}
    assert factors[1].basis is EvidenceBasis.LIFECYCLE
    assert factors[1].weight == pytest.approx(0.4)


@pytest.mark.parametrize(
    ("state", "expected"),
    [("PROJECTED", 0.2), ("POTENTIAL", 0.4), ("DEVELOPING", 0.7), ("CONFIRMED", 1.0)],
)
def test_a_fade_lifecycle_orders_weakest_first(state: str, expected: float) -> None:
    factors = from_fading_measured_move({"state": state, "projection": None})

    assert [f.weight for f in factors] == [pytest.approx(expected)]


@pytest.mark.parametrize("state", ["COMPLETED", "INVALIDATED"])
def test_a_terminal_fade_is_excluded_rather_than_scored(state: str) -> None:
    """A terminal negative is not a weak observation, it is a dead one."""
    assert from_fading_measured_move({"state": state, "projection": None}) == []


def test_a_fade_without_a_projection_still_reports_its_lifecycle() -> None:
    """The lifecycle is the fade's own evidence and does not depend on the target
    being present."""
    factors = from_fading_measured_move({"state": "DEVELOPING", "projection": None})

    assert [f.code for f in factors] == ["DEVELOPING"]


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def test_the_score_is_the_mean_of_its_factors() -> None:
    """Checked against a hand-computed mean, not against the implementation."""
    assert score(bundle(measured("A", 1.0), measured("B", 0.0))).value == 0.5


def test_each_source_gets_an_equal_say_regardless_of_how_many_factors_it_has() -> None:
    """A flat mean would let the chattier source dominate on arithmetic alone.

    The reversal adapter emits one factor per satisfied leg; the pullback adapter
    emits exactly one. Without per-source averaging a four-leg reversal would
    outweigh a confirmed pullback purely by count.
    """
    b = bundle(
        measured("MM_SCALE", 1.0),
        measured("MM_MARGIN", 1.0),
        measured("MM_GAP", 1.0),
        measured("MM_FAIL", 1.0),
        lifecycle("CONFIRMED", 0.0),
    )
    result = score(b)
    # 1.0 for the measured-move source, 0.0 for the pullback source.
    assert result.value == pytest.approx(0.5)
    assert result.by_source == {"MEASURED_MOVE": 1.0, "PULLBACK": 0.0}


def test_the_score_is_reproducible_from_its_own_factors() -> None:
    """The property the measured-move `confidence` already guarantees."""
    b = bundle(measured("A", 0.9), lifecycle("B", 0.2, "REVERSAL"), asserted("C"))
    expected = (0.9 + 0.2 + UNQUANTIFIED_WEIGHT) / 3
    assert score(b).value == pytest.approx(expected)
    assert score(b).value == score(b).value


def test_the_score_does_not_depend_on_factor_order() -> None:
    b = bundle(measured("A", 0.1), measured("B", 0.9), lifecycle("C", 0.5))
    reversed_bundle = EvidenceBundle(
        subject=b.subject, factors=tuple(reversed(b.factors))
    )
    assert score(b).value == score(reversed_bundle).value


def test_an_empty_bundle_scores_nothing_and_says_so() -> None:
    """No evidence is `NONE`, not `WEAK` — the two are different statements."""
    result = score(bundle())
    assert result.value == 0.0
    assert result.band == BAND_NONE
    assert result.warnings == (WARN_NO_EVIDENCE,)
    assert not result.is_usable


def test_evidence_built_only_from_assertions_is_flagged_as_unquantified() -> None:
    """A number derived entirely from presence flags is not a measurement."""
    result = score(bundle(asserted("A"), asserted("B")))
    assert WARN_UNQUANTIFIED_ONLY in result.warnings
    assert result.quantified_share == 0.0


def test_partially_quantified_evidence_is_flagged() -> None:
    result = score(bundle(measured("A", 1.0), asserted("B")))
    assert result.warnings == (WARN_PARTIAL_QUANTIFIED,)


def test_fully_measured_multi_source_evidence_carries_no_caveat() -> None:
    result = score(bundle(measured("A", 1.0), measured("B", 1.0, "REVERSAL")))
    assert result.warnings == ()


def test_a_single_source_bundle_is_flagged() -> None:
    """One source agreeing with itself is weaker evidence than two agreeing."""
    assert WARN_SINGLE_SOURCE in score(bundle(measured("A", 1.0))).warnings


def test_measured_only_drops_what_was_never_measured() -> None:
    """The question a reader of a low score should be able to ask directly."""
    b = bundle(measured("A", 0.9), lifecycle("B", 1.0), asserted("C"))
    assert [f.code for f in measured_only(b)] == ["A"]


def test_measured_only_of_an_unmeasured_bundle_is_empty_rather_than_raising() -> None:
    filtered = measured_only(bundle(asserted("A")))
    assert len(filtered) == 0
    assert score(filtered).warnings == (WARN_NO_EVIDENCE,)


def test_is_usable_distinguishes_no_evidence_from_weak_evidence() -> None:
    assert not score(bundle()).is_usable
    assert score(bundle(measured("A", 0.05))).is_usable


def test_the_score_output_says_it_is_not_a_probability() -> None:
    """Recorded in the payload so a consumer is told, rather than having to know."""
    assert score(bundle(measured("A", 0.9))).to_dict()["is_probability"] is False


# --------------------------------------------------------------------------
# Banding
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, BAND_NONE),
        (0.01, BAND_WEAK),
        (0.39, BAND_WEAK),
        (0.40, BAND_MODERATE),
        (0.69, BAND_MODERATE),
        (0.70, BAND_STRONG),
        (1.0, BAND_STRONG),
    ],
)
def test_band_thresholds_come_from_configuration(value: float, expected: str) -> None:
    assert band(value, CFG) == expected


def test_the_band_thresholds_are_configurable_rather_than_buried() -> None:
    """ARCHITECTURE.md §11: no heuristic threshold is a literal inside a detector."""
    strict = AnalyzerConfig(evidence_moderate_band=0.95, evidence_strong_band=0.99)
    assert band(0.90, CFG) == BAND_STRONG
    assert band(0.90, strict) == BAND_WEAK


def test_there_are_four_bands_and_no_more() -> None:
    """Deliberately coarse; finer banding would imply a resolution these
    heuristics do not have."""
    assert {band(v / 100, CFG) for v in range(101)} == {
        BAND_NONE,
        BAND_WEAK,
        BAND_MODERATE,
        BAND_STRONG,
    }


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------


def test_compare_orders_by_score() -> None:
    bundles = [
        bundle(measured("A", 0.2), subject="LOW"),
        bundle(measured("B", 0.9), subject="HIGH"),
    ]
    assert compare(bundles, CFG) == [("HIGH", 0.9), ("LOW", 0.2)]


def test_compare_is_deterministic_for_equal_scores() -> None:
    """Equal scores must not reorder between runs or Python versions."""
    bundles = [
        bundle(measured("A", 0.5), subject="ZULU"),
        bundle(measured("B", 0.5), subject="ALPHA"),
    ]
    assert compare(bundles, CFG) == [("ALPHA", 0.5), ("ZULU", 0.5)]


def test_compare_of_nothing_is_empty_rather_than_an_error() -> None:
    assert compare([], CFG) == []


# --------------------------------------------------------------------------
# Adapters
# --------------------------------------------------------------------------


def test_the_measured_move_adapter_preserves_the_engines_own_weights() -> None:
    class Item:
        code = "MM_SCALE"
        weight = 0.875
        detail = "measured range 10.0 = 2.00 ATR"

    class Projection:
        family = "RANGE"
        evidence = [Item()]

    factor = from_measured_move(Projection())[0]
    assert factor.source == "MEASURED_MOVE"
    assert factor.code == "MM_SCALE"
    assert factor.weight == 0.875
    assert factor.basis is EvidenceBasis.MEASURED
    assert factor.family == "RANGE"


def test_the_measured_move_adapter_passes_through_an_empty_projection() -> None:
    class Blank:
        family = "NONE"
        evidence = ()

    assert from_measured_move(Blank()) == []


def test_market_state_reads_a_trailing_number_as_a_measurement() -> None:
    class State:
        evidence = ["STRONG_EMA_TREND_SLOPE: 1.00"]

    factor = from_market_state(State())[0]
    assert factor.code == "STRONG_EMA_TREND_SLOPE"
    assert factor.weight == 1.0
    assert factor.basis is EvidenceBasis.MEASURED


def test_market_state_keeps_a_bare_observation_unquantified() -> None:
    """Compression being present is not a magnitude — flattening it to a number
    would discard the distinction the market-state engine drew."""

    class State:
        evidence = ["RANGE_TIGHTENING_COMPRESSION"]

    factor = from_market_state(State())[0]
    assert factor.basis is EvidenceBasis.ASSERTED
    assert factor.weight == UNQUANTIFIED_WEIGHT


def test_market_state_does_not_read_a_number_from_the_middle_of_a_detail() -> None:
    """"closed 0.8 beyond the edge" must not be read as the number 0.8."""

    class State:
        evidence = ["MARGIN: closed 0.8 beyond the edge"]

    assert from_market_state(State())[0].basis is EvidenceBasis.ASSERTED


def test_reversal_legs_are_lifecycle_facts_at_full_weight() -> None:
    """A leg is satisfied or it is not; a graded weight would be meaningless."""

    class Quality:
        satisfied = ["EMA_BREAK", "EMA_RETEST_HELD"]
        verdict = "MINOR"
        direction = -1

    factors = from_reversal(Quality())
    assert [f.code for f in factors] == [
        "EMA_BREAK",
        "EMA_RETEST_HELD",
        "VERDICT_MINOR",
    ]
    assert all(f.basis is EvidenceBasis.LIFECYCLE for f in factors)
    assert all(f.weight == 1.0 for f in factors)


def test_reversal_with_no_verdict_reports_no_verdict_factor() -> None:
    class Quality:
        satisfied = ["EMA_BREAK"]
        verdict = "NONE"
        direction = 1

    assert [f.code for f in from_reversal(Quality())] == ["EMA_BREAK"]


def test_an_invalidated_pullback_is_excluded_rather_than_scored_low() -> None:
    """"Scored badly" and "not a candidate" are different, and a caller must be
    able to tell them apart."""
    assert from_pullback({"state": "INVALIDATED", "found": True}) == []


def test_a_confirmed_pullback_ranks_above_a_candidate() -> None:
    confirmed = from_pullback({"state": "CONFIRMED", "found": True})[0]
    candidate = from_pullback({"state": "CANDIDATE", "found": True})[0]
    assert confirmed.weight > candidate.weight
    assert confirmed.basis is EvidenceBasis.LIFECYCLE


def test_a_pullback_keeps_its_family_and_setup_type() -> None:
    factor = from_pullback(
        {"state": "CONFIRMED", "found": True, "family": "H_PULLBACK", "setup_type": "H2"}
    )[0]
    assert factor.family == "H_PULLBACK"
    assert factor.detail == "H2"


def test_a_failed_breakout_is_excluded_rather_than_scored_low() -> None:
    """A failed breakout is not a weak breakout; it is the opposite one."""
    assert from_breakout({"outcome": "FAILED", "found": True}) == []


def test_a_follow_through_breakout_outranks_a_pending_one() -> None:
    follow = from_breakout({"outcome": "FOLLOW", "found": True})[0]
    pending = from_breakout({"outcome": "PENDING", "found": True})[0]
    assert follow.weight > pending.weight


def test_breakout_traps_are_recorded_rather_than_subtracted() -> None:
    """A bundle is always a mean of what was observed, never a number things
    were taken away from."""
    factors = from_breakout(
        {"outcome": "FOLLOW", "found": True, "trap": True, "second_leg_trap": True}
    )
    assert [f.code for f in factors] == [
        "OUTCOME_FOLLOW",
        "BREAKOUT_TRAP",
        "SECOND_LEG_TRAP",
    ]
    assert all(f.weight > 0.0 for f in factors)


def test_every_known_source_has_an_adapter() -> None:
    """The registry of sources and the adapters must not drift apart."""
    import albrooks.evaluation.evidence as ev

    for source in KNOWN_SOURCES:
        assert hasattr(ev, f"from_{source.lower()}")


# --------------------------------------------------------------------------
# Integration: real engine output through the whole model
# --------------------------------------------------------------------------


def _rally(n: int = 60) -> list[dict[str, float]]:
    """Rally, pullback, rally — the series the other suites use."""
    out: list[dict[str, float]] = []
    price = 100.0
    for i in range(n):
        if i < n * 0.33:
            o, h, low, c = price, price + 1.0, price - 1.0, price + 0.8
        elif i < n * 0.5:
            o, h, low, c = price, price + 1.0, price - 1.0, price - 0.4
        else:
            o, h, low, c = price, price + 1.2, price - 0.6, price + 1.0
        price = c
        out.append({"o": o, "h": h, "l": low, "c": c})
    return out


def _real_bundle() -> EvidenceBundle:
    """Build a bundle from real engine output, not from fixtures."""
    from albrooks.context.market_state import analyze_market_state
    from albrooks.core.bars import BarSeries
    from albrooks.core.legs import build_legs_from_swings
    from albrooks.core.swings import find_swings
    from albrooks.price_action.bars import calculate_atr_series
    from albrooks.setups.breakout import analyze_breakout
    from albrooks.setups.measured_move import detect_measured_moves
    from albrooks.setups.pullback import detect_h1_h2

    series = BarSeries(_rally(60))
    closed = len(series) - 1
    atr = calculate_atr_series(series, period=CFG.atr_period)[closed]
    swings = find_swings(series, last_closed_idx=closed, k=CFG.swing_k)
    legs = build_legs_from_swings(swings)

    state = analyze_market_state(series, closed, closed, atr, config=CFG)
    moves = detect_measured_moves(
        series, swings, atr=atr, last_closed=closed, legs=legs, config=CFG
    )
    pullback = detect_h1_h2(series, closed, closed, atr, config=CFG).to_dict()
    breakout = analyze_breakout(series, closed, closed, atr, swings=swings, config=CFG).to_dict()

    factors: list[EvidenceFactor] = []
    factors += from_market_state(state)
    for move in moves:
        factors += from_measured_move(move)
    if pullback.get("found"):
        factors += from_pullback(pullback)
    if breakout.get("found"):
        factors += from_breakout(breakout)
    return EvidenceBundle(subject="INTEGRATION", factors=tuple(factors))


def test_real_engine_output_flows_through_the_whole_model() -> None:
    """The integration test: every adapter fed by the real detectors.

    A signature drift or a renamed field would surface here rather than in
    whichever consumer happened to call it first.
    """
    b = _real_bundle()
    result = score(b, CFG)
    assert len(b) > 0
    assert 0.0 <= result.value <= 1.0
    assert result.band in {BAND_NONE, BAND_WEAK, BAND_MODERATE, BAND_STRONG}
    json.dumps(b.to_dict())
    json.dumps(result.to_dict())


def test_real_evidence_is_never_reported_as_a_probability() -> None:
    assert _real_bundle() and score(_real_bundle(), CFG).to_dict()["is_probability"] is False


def test_every_real_factor_declares_its_basis() -> None:
    """The one invariant that must hold for all real output, without exception."""
    for factor in _real_bundle():
        assert factor.basis in set(EvidenceBasis)
        assert 0.0 <= factor.weight <= 1.0
        assert factor.source
        assert factor.code


def test_every_real_source_is_one_this_module_declares() -> None:
    """An unrecognised source would silently escape the per-source weighting."""
    assert {f.source for f in _real_bundle()} <= set(KNOWN_SOURCES)
