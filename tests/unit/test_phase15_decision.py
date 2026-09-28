"""Tests for the decision engine (Phase 15).

This is the layer where this project finally answers, and where the temptation to
overstate is highest. The tests therefore pin the properties that keep the answer
honest, rather than the answer itself:

1. **It ranks, and says on what.** `RANKING_BASIS` is echoed in every decision and
   the sort is deterministic, so two candidates with identical numbers are
   separated only by a name and a run over the same inputs always agrees with
   itself. A ranking by declared criteria is a comparison, not an edge.
2. **Abstention is a real answer.** `NO_TRADE` (nothing to say) and `WAIT`
   (something to say, condition unmet) stay distinct, every gate reports *all* of
   its failures rather than the first, and every threshold appears in the veto
   detail so the comparison can be checked instead of trusted.
3. **It never infers a trade it was not given.** `enable_decision=False` answers
   `NO_TRADE`; no volatility reference answers `NO_TRADE`; nothing found answers
   `NO_TRADE`. And with candidates that all fail, nothing is ranked — the least
   bad of them is not a recommendation this layer has earned.
4. **No number here is a probability**, and the output says so rather than leaving
   the reader to find the module.

Expected values are hand-computed, not read back from the implementation.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from albrooks.decision.engine import (
    RANKING_BASIS,
    REASON_ALL_VETOED,
    REASON_CONFLICT,
    REASON_DISABLED,
    REASON_NO_ANALYSIS,
    REASON_NO_CANDIDATES,
    REASON_RANKED,
    Action,
    TradeCandidate,
    bundle_for,
    candidates_from_findings,
    decide,
)
from albrooks.decision.veto import (
    ADVERSE_EVIDENCE_CODES,
    KNOWN_VETOES,
    VETO_AGAINST_HIGHER_TIMEFRAME,
    VETO_EVIDENCE_TOO_WEAK,
    VETO_INVALID_GEOMETRY,
    VETO_NO_ATR,
    VETO_NO_DIRECTION,
    VETO_NO_OWN_EVIDENCE,
    VETO_RISK_REWARD_TOO_LOW,
    VETO_TERMINAL_SETUP,
    VETO_TOO_MANY_FAILED_ATTEMPTS,
    VETO_TRADE_IS_LATE,
    VETO_VOLATILITY_STOP_ONLY,
    Veto,
    blocking_codes,
    is_blocked,
    summary,
    vetoes_for,
)
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.evaluation.evidence import EvidenceBasis, EvidenceBundle, EvidenceFactor
from albrooks.evaluation.scoring import score
from albrooks.setups.base import SetupFinding
from albrooks.trade.plan import anatomy_for, build_trade_plan

CFG = AnalyzerConfig()
ATR = 2.0
#: Closes rising into bar 9, which closed at 104.0.
BARS: list[dict[str, float]] = [
    {"o": c - 0.2, "h": c + 0.5, "l": c - 0.5, "c": c}
    for c in (100.0, 101.0, 102.0, 103.0, 100.0, 101.0, 102.0, 103.0, 103.5, 104.0)
]


def make_candidate(
    *,
    direction: int = 1,
    legs: int = 4,
    payload: dict[str, Any] | None = None,
    id: str = "CANDIDATE#0",
    family: str = "REVERSAL",
    market_state: dict[str, Any] | None = None,
    factors: tuple[EvidenceFactor, ...] | None = None,
) -> TradeCandidate:
    """A candidate with a controllable evidence score and plan geometry.

    Evidence comes from a synthetic bundle rather than from a real detector, so a
    test can put a candidate at a chosen score without engineering a market that
    produces it. The *plan* is still built through the real builder, so the
    geometry under test is the geometry the pipeline produces.
    """
    body = (
        payload
        if payload is not None
        else {
            "direction": direction,
            "verdict": "MAJOR" if legs >= 4 else "MINOR",
            "score": legs * 25,
            "leg_count": legs,
            "satisfied": [f"LEG_{i}" for i in range(legs)],
            "missing": [],
            "cross_bar": 9,
        }
    )
    body.setdefault("direction", direction)
    plan = build_trade_plan(
        id.split("#")[0],
        body,
        bars=BARS,
        bar_index=9,
        atr=ATR,
        anatomy=anatomy_for(family),
        config=CFG,
    )
    if factors is None:
        factors = tuple(
            EvidenceFactor(
                source="TEST", code="W", weight=w, basis=EvidenceBasis.LIFECYCLE
            )
            for w in _weights(legs)
        )
    bundle = EvidenceBundle(subject=id, direction=direction, factors=factors)
    return TradeCandidate(
        candidate_id=id, plan=plan, bundle=bundle, evidence=score(bundle, CFG)
    )


def _weights(legs: int) -> list[float]:
    """`legs` factors each of weight `legs / 4`, so the mean is exactly
    `legs / 4` and every score in these tests is hand-computable: 1.0 for four
    legs, 0.5 for two, 0.25 for one."""
    return [min(1.0, legs / 4)] * legs


def adverse(*codes: str) -> tuple[EvidenceFactor, ...]:
    """Factors carrying the given evidence codes, as the breakout adapter emits
    them: asserted, unweighted, and adverse."""
    return tuple(
        EvidenceFactor(source="BREAKOUT", code=code, basis=EvidenceBasis.ASSERTED)
        for code in codes
    )


def weighted(value: float, *, direction: int = 1) -> tuple[EvidenceFactor, ...]:
    """Four measured factors at `value`, so the bundle's score is exactly `value`
    and any percentage point in a test is hand-computable."""
    return tuple(
        EvidenceFactor(
            source="TEST", code=f"M{i}", weight=value, basis=EvidenceBasis.MEASURED
        )
        for i in range(4)
    )


def vetoes(candidate: TradeCandidate, *, config: AnalyzerConfig = CFG, close: float = 104.0):
    return vetoes_for(candidate, close=close, atr=ATR, config=config)


def codes(candidate: TradeCandidate, **kwargs: Any) -> list[str]:
    return blocking_codes(vetoes(candidate, **kwargs))


# --------------------------------------------------------------------------
# The four actions
# --------------------------------------------------------------------------


def test_disabled_means_no_trade_and_never_an_inferred_trade() -> None:
    """`enable_decision=False` is the one setting where a plausible-looking BUY
    would be indefensible: the user asked for no decision."""
    result = decide(
        [make_candidate()],
        bars=BARS,
        last_closed=9,
        atr=ATR,
        config=AnalyzerConfig(enable_decision=False),
    )

    assert result.action == Action.NO_TRADE.value
    assert result.reason == REASON_DISABLED
    assert not result.is_actionable
    assert result.plan is None
    assert "enable_decision" in " ".join(result.explanation)


def test_no_volatility_reference_means_no_trade_not_an_ungated_decision() -> None:
    """Every gate is ATR-relative. Without an ATR none of them can be evaluated,
    and a decision over ungated candidates would rest on unchecked numbers."""
    result = decide([make_candidate()], bars=BARS, last_closed=9, atr=0.0)

    assert result.action == Action.NO_TRADE.value
    assert result.reason == REASON_NO_ANALYSIS


def test_nothing_found_is_no_trade_and_says_so() -> None:
    result = decide([], bars=BARS, last_closed=9, atr=ATR)

    assert result.action == Action.NO_TRADE.value
    assert result.reason == REASON_NO_CANDIDATES
    assert result.considered["considered"] == 0


def test_wait_and_no_trade_are_different_answers() -> None:
    """An empty result and a rejected one call for different behaviour from a
    caller. Collapsing them would make 'nothing found' look like a judgement."""
    empty = decide([], bars=BARS, last_closed=9, atr=ATR)
    rejected = decide(
        [make_candidate(legs=1)], bars=BARS, last_closed=9, atr=ATR
    )

    assert empty.action == Action.NO_TRADE.value
    assert rejected.action == Action.WAIT.value
    assert empty.reason != rejected.reason


def test_a_strong_candidate_is_ranked_and_bought() -> None:
    """Four legs is `LIFECYCLE` weight 1.0 per leg, so the score is exactly 1.0
    and the plan's reward:risk clears the default 1.0."""
    result = decide([make_candidate()], bars=BARS, last_closed=9, atr=ATR)

    assert result.action == Action.BUY.value
    assert result.reason == REASON_RANKED
    assert result.subject == "CANDIDATE#0"
    assert result.direction == 1
    assert result.evidence["value"] == pytest.approx(1.0)
    assert result.evidence["ppts"] == pytest.approx(100.0)
    assert result.is_actionable


def test_a_bear_candidate_is_sold() -> None:
    result = decide(
        [make_candidate(direction=-1)], bars=BARS, last_closed=9, atr=ATR
    )

    assert result.action == Action.SELL.value
    assert result.direction == -1


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------


def test_the_ranking_criteria_travel_with_the_answer() -> None:
    """A reader must not have to open this file to know why one plan won."""
    result = decide([make_candidate()], bars=BARS, last_closed=9, atr=ATR)

    assert tuple(result.ranking_basis) == RANKING_BASIS
    assert result.to_dict()["ranking_basis"] == list(RANKING_BASIS)


def test_higher_evidence_wins_even_when_the_other_side_has_better_reward() -> None:
    """Evidence first, by the declared order. The two-candidate ordering is the
    claim, so it is pinned rather than left to the implementation."""
    strong = make_candidate(legs=4, id="A#0")
    weak = make_candidate(legs=1, id="B#0")

    assert strong.evidence_value == pytest.approx(1.0)
    assert weak.evidence_value == pytest.approx(0.25)
    result = decide([weak, strong], bars=BARS, last_closed=9, atr=ATR)

    assert result.subject == "A#0"


def test_an_exact_tie_is_broken_by_name_so_the_run_is_reproducible() -> None:
    """Two candidates with identical numbers must not swap places between runs
    or between the order they happened to arrive in."""
    first = make_candidate(id="A#0")
    second = make_candidate(id="B#0")
    assert first.evidence_value == second.evidence_value

    forward = decide([first, second], bars=BARS, last_closed=9, atr=ATR)
    backward = decide([second, first], bars=BARS, last_closed=9, atr=ATR)

    assert forward.subject == backward.subject == "A#0"


def test_reward_to_risk_breaks_an_evidence_tie() -> None:
    """The second criterion, isolated.

    Both candidates have the same evidence and the same entry, and differ only in
    how far the stop sits. The *higher* reward:risk is given the later id, so the
    name tie-break would pick the other one: the winner therefore proves the
    reward:risk criterion ran, not the fallback.

    Geometry, with entry 104, target 108 (a 2.0 ATR fallback) and a 0.5 buffer:
    stop 101.5 gives risk 2.5 and reward:risk 1.6; stop 100.0 gives risk 4.0 and
    reward:risk 1.0 exactly, which clears `min_rr` because the gate is `>=`.
    """
    thin_rr = make_candidate(
        legs=4,
        id="A#0",
        family="PULLBACK",
        payload={
            "direction": 1,
            "state": "CONFIRMED",
            "reference_price": 104.0,
            "stop_price": 100.5,
        },
    )
    thick_rr = make_candidate(
        legs=4,
        id="B#0",
        family="PULLBACK",
        payload={
            "direction": 1,
            "state": "CONFIRMED",
            "reference_price": 104.0,
            "stop_price": 102.0,
        },
    )
    assert thin_rr.evidence_value == thick_rr.evidence_value
    assert thin_rr.plan.reward_to_risk == pytest.approx(1.0)
    assert thick_rr.plan.reward_to_risk == pytest.approx(1.6)
    assert VETO_RISK_REWARD_TOO_LOW not in codes(thin_rr)

    result = decide([thin_rr, thick_rr], bars=BARS, last_closed=9, atr=ATR)

    assert result.subject == "B#0"



def test_a_ranking_is_never_reported_as_a_probability() -> None:
    payload = decide([make_candidate()], bars=BARS, last_closed=9, atr=ATR).to_dict()

    assert payload["is_probability"] is False
    assert "confidence" not in payload
    assert any("not an edge" in line for line in payload["explanation"])


# --------------------------------------------------------------------------
# Vetoes
# --------------------------------------------------------------------------


def test_an_invalid_plan_is_vetoed_before_any_threshold_is_read() -> None:
    """A wrong-side stop is an arithmetically broken plan, not a weak one."""
    broken = make_candidate(
        payload={
            "direction": 1,
            "verdict": "MAJOR",
            "satisfied": ["L0", "L1", "L2", "L3"],
            "missing": [],
            "cross_bar": 9,
            "reference_price": 100.0,
            "stop_price": 108.0,
        },
        family="PULLBACK",
    )

    assert VETO_INVALID_GEOMETRY in codes(broken)


def test_a_directionless_plan_is_vetoed_because_it_cannot_be_ranked() -> None:
    """The invariant "every eligible candidate has a direction" is a property of
    the gates, not a branch in the ranking code."""
    flat = make_candidate(direction=0, payload={"verdict": "MAJOR", "satisfied": ["L0"]})

    assert VETO_NO_DIRECTION in codes(flat)
    result = decide([flat], bars=BARS, last_closed=9, atr=ATR)
    assert result.action == Action.WAIT.value


def test_a_terminal_setup_is_vetoed() -> None:
    terminal = make_candidate(
        payload={
            "direction": 1,
            "outcome": "FAILED",
            "state": "FAILED",
            "reference_price": 100.0,
            "breakout_bar": 9,
        },
        family="BREAKOUT",
    )

    assert VETO_TERMINAL_SETUP in codes(terminal)


def test_the_evidence_gate_names_both_numbers() -> None:
    """A veto that only said `EVIDENCE_TOO_WEAK` would be unfalsifiable."""
    weak = make_candidate(legs=1)  # score exactly 0.25
    assert weak.evidence_value == pytest.approx(0.25)

    found = [v for v in vetoes(weak) if v.code == VETO_EVIDENCE_TOO_WEAK]
    assert len(found) == 1
    assert "0.2500" in found[0].detail
    assert "0.4000" in found[0].detail
    assert found[0].config_key == "min_score"
    assert found[0].blocking


def test_the_evidence_gate_is_a_boundary_and_the_value_survives_throughput() -> None:
    """Exactly at `min_score` passes; a hair below fails."""
    at_limit = make_candidate(legs=1, id="A#0")
    assert at_limit.evidence_value == pytest.approx(0.25)
    loose = AnalyzerConfig(min_score=0.25)
    tight = AnalyzerConfig(min_score=0.2501)

    assert VETO_EVIDENCE_TOO_WEAK not in codes(at_limit, config=loose)
    assert VETO_EVIDENCE_TOO_WEAK in codes(at_limit, config=tight)


def test_the_risk_reward_gate_names_both_numbers() -> None:
    thin = make_candidate(
        payload={
            "direction": 1,
            "verdict": "MAJOR",
            "satisfied": ["L0", "L1", "L2", "L3"],
            "missing": [],
            "cross_bar": 9,
            "reference_price": 104.0,
            "stop_price": 90.0,  # risk 14.0, reward 4.0 -> 0.2857
        },
        family="PULLBACK",
    )
    found = [v for v in vetoes(thin) if v.code == VETO_RISK_REWARD_TOO_LOW]

    # entry 104, stop 90 less the 0.5 buffer = 89.5, so risk 14.5 against a
    # 4.0 reward that no target key could improve on.
    assert thin.plan.risk == pytest.approx(14.5)
    assert thin.plan.reward_to_risk == pytest.approx(4.0 / 14.5)
    assert len(found) == 1
    assert "0.2759" in found[0].detail
    assert found[0].config_key == "min_rr"


def test_the_lateness_gate_measures_drift_from_the_plan_entry() -> None:
    """`max_late_atr` says the plan is *stale*, not wrong. At 104.0 the drift is
    zero; at 105.0 it is exactly 0.5 ATR, which is the boundary."""
    plan_entry = 104.0

    at_limit = vetoes(make_candidate(), close=plan_entry + 1.0)  # 0.5 ATR
    beyond = vetoes(make_candidate(), close=plan_entry + 1.0001)

    assert VETO_TRADE_IS_LATE not in blocking_codes(at_limit)
    assert VETO_TRADE_IS_LATE in blocking_codes(beyond)
    detail = next(
        v.detail for v in beyond if v.code == VETO_TRADE_IS_LATE
    )
    assert "max_late_atr" in detail


def test_a_volatility_only_stop_is_reported_but_never_blocks() -> None:
    """A plan on an invented stop is materially weaker, and the reader is told —
    but excluding it would be a judgement the engine has not earned."""
    weak = make_candidate()
    assert not weak.plan.has_structural_stop

    found = next(v for v in vetoes(weak) if v.code == VETO_VOLATILITY_STOP_ONLY)
    assert not found.blocking
    assert not is_blocked([found])
    result = decide([weak], bars=BARS, last_closed=9, atr=ATR)
    assert result.action == Action.BUY.value
    assert any(
        v["code"] == VETO_VOLATILITY_STOP_ONLY for v in result.to_dict()["vetoes"]
    )


def test_too_many_adverse_observations_block_and_the_codes_are_listed() -> None:
    """Two of the only adverse codes the Phase 13 adapters emit is at the default
    limit of two and passes; the plan's own terminal flag makes three and blocks.
    The detail names the codes, so the count has a stated basis."""
    pending = make_candidate(
        family="BREAKOUT",
        factors=adverse("BREAKOUT_TRAP", "SECOND_LEG_TRAP"),
        payload={
            "direction": 1,
            "outcome": "PENDING",
            "state": "PENDING",
            "reference_price": 100.0,
            "breakout_bar": 9,
        },
    )
    failed = make_candidate(
        family="BREAKOUT",
        factors=adverse("BREAKOUT_TRAP", "SECOND_LEG_TRAP"),
        payload={
            "direction": 1,
            "outcome": "FAILED",
            "state": "FAILED",
            "reference_price": 100.0,
            "breakout_bar": 9,
        },
    )

    assert set(ADVERSE_EVIDENCE_CODES) == {"BREAKOUT_TRAP", "SECOND_LEG_TRAP"}
    assert VETO_TOO_MANY_FAILED_ATTEMPTS not in codes(pending)
    assert VETO_TERMINAL_SETUP in codes(failed)

    found = next(v for v in vetoes(failed) if v.code == VETO_TOO_MANY_FAILED_ATTEMPTS)
    assert "3 adverse observations" in found.detail
    assert "BREAKOUT_TRAP" in found.detail and "SECOND_LEG_TRAP" in found.detail
    assert found.config_key == "max_failed_attempts"
    # And the gate moves with the knob.
    assert not [
        v
        for v in vetoes(failed, config=AnalyzerConfig(max_failed_attempts=3))
        if v.code == VETO_TOO_MANY_FAILED_ATTEMPTS
    ]


def test_every_gate_of_one_candidate_is_reported_not_just_the_first() -> None:
    """A reader fixing one condition should not have to re-run to find the next."""
    doomed = make_candidate(
        legs=1,
        family="PULLBACK",
        payload={
            "direction": 1,
            "state": "INVALIDATED",
            "setup_type": "H2",
            "signal_bar": 9,
            "reference_price": 100.0,
            "stop_price": 90.0,
        },
    )
    found = set(codes(doomed))

    assert VETO_EVIDENCE_TOO_WEAK in found
    assert VETO_RISK_REWARD_TOO_LOW in found
    assert VETO_TRADE_IS_LATE in found
    assert VETO_TERMINAL_SETUP in found
    assert len(found) == 4


def test_a_candidate_with_only_shared_context_is_vetoed() -> None:
    """Found in Phase 16, by wiring the pipeline.

    `score()` averages within each source and then across sources, so a bundle
    holding a single source scores that source's value outright. Market-state
    context is added to *every* candidate and is identical for all of them, so a
    bundle with nothing but context scores at the market state's value with no
    penalty for having said nothing about its setup. A fading measured move whose
    adapter did not exist was scoring 100 ppts that way, outranking a measured move
    with real factors behind it.
    """
    context_only = make_candidate(
        id="CTX#0",
        factors=(
            EvidenceFactor(
                source="MARKET_STATE", code="STRONG_EMA_TREND_SLOPE", weight=1.0
            ),
        ),
    )
    assert context_only.evidence_value == pytest.approx(1.0)
    assert not context_only.has_own_evidence
    assert VETO_NO_OWN_EVIDENCE in codes(context_only)

    # And a candidate with evidence of its own is unaffected.
    assert make_candidate().has_own_evidence
    assert VETO_NO_OWN_EVIDENCE not in codes(make_candidate())


def test_a_candidate_must_say_something_about_its_own_setup_to_be_ranked() -> None:
    """The structural half of the same fix: a missing adapter anywhere now yields a
    refused candidate rather than a plausible-looking one."""
    context_only = make_candidate(
        id="CTX#0",
        factors=(
            EvidenceFactor(source="MARKET_STATE", code="RANGE_TIGHTENING", weight=0.9),
        ),
    )

    result = decide([context_only], bars=BARS, last_closed=9, atr=ATR)

    assert result.action == Action.WAIT.value
    assert result.reason == REASON_ALL_VETOED
    assert result.considered["blocking_summary"] == {VETO_NO_OWN_EVIDENCE: 1}


def test_a_fade_and_the_measured_move_it_fades_do_not_score_identically() -> None:
    """Without the fade's lifecycle factor the two bundled the same projection
    evidence, scored exactly the same, and the decision layer reported a
    zero-width `EVIDENCE_CONFLICT` on every strong measured move."""
    from albrooks.evaluation.evidence import from_fading_measured_move, from_measured_move

    projection = {"family": "RANGE", "direction": 1, "evidence": [
        {"code": "MM_SCALE", "weight": 0.8, "detail": ""},
    ]}
    trend = EvidenceBundle(
        subject="M", direction=1, factors=from_measured_move(projection)
    )
    fade = EvidenceBundle(
        subject="F",
        direction=-1,
        factors=from_fading_measured_move({"state": "POTENTIAL", "projection": projection}),
    )

    assert score(trend).value != score(fade).value
    assert score(trend).value > score(fade).value


def test_a_weak_fade_does_not_create_a_conflict_against_a_strong_projection() -> None:
    """The case the two fixes together exist for, and it is the pipeline's default
    behaviour on a trending series: a `POTENTIAL` fade is a weaker claim than a
    confirmed projection, so the sides are not in conflict."""
    trend = make_candidate(
        id="MM#0",
        family="MEASURED_MOVE",
        factors=weighted(0.95),
        payload={
            "direction": 1,
            "family": "RANGE",
            "target_price": 112.0,
            "origin": {"bar_index": 4, "price": 104.0},
        },
    )
    fade = make_candidate(
        id="FM#1",
        direction=-1,
        family="FADING_MEASURED_MOVE",
        factors=weighted(0.80, direction=-1),
        payload={
            "direction": 1,
            "fade_direction": -1,
            "state": "POTENTIAL",
            "projection": {"origin": {"bar_index": 4, "price": 104.0}},
        },
    )

    result = decide([trend, fade], bars=BARS, last_closed=9, atr=ATR)

    assert result.reason == REASON_RANKED
    assert result.action == Action.BUY.value


def test_the_declared_veto_codes_are_covered() -> None:
    """`KNOWN_VETOES` must include the code the multi-timeframe pipeline raises,
    or a consumer iterating a decision's vetoes would have to read two lists."""
    assert VETO_AGAINST_HIGHER_TIMEFRAME in KNOWN_VETOES
    assert VETO_NO_OWN_EVIDENCE in KNOWN_VETOES


def test_no_gates_are_short_circuited_by_a_broken_geometry() -> None:
    """A broken plan still gets its threshold comparison, so the reader sees the
    whole picture rather than a single arithmetic complaint."""
    broken = make_candidate(
        legs=1,
        payload={
            "direction": 1,
            "verdict": "MINOR",
            "satisfied": ["LEG_0"],
            "missing": [],
            "cross_bar": 9,
            "reference_price": 100.0,
            "stop_price": 108.0,
        },
        family="PULLBACK",
    )
    found = set(codes(broken))

    assert VETO_INVALID_GEOMETRY in found
    assert VETO_EVIDENCE_TOO_WEAK in found


def test_the_declared_veto_codes_match_the_module() -> None:
    """A new gate cannot be added without being declared, and a declared code
    cannot go missing."""
    from albrooks.decision import veto as module

    declared = {
        value
        for name, value in vars(module).items()
        if name.startswith("VETO_") and isinstance(value, str)
    }
    assert declared == set(KNOWN_VETOES)


def test_the_summary_counts_codes_rather_than_picking_the_worst_one() -> None:
    """Picking a single 'most important' veto would hide the others."""
    a = make_candidate(legs=1, id="A#0")
    b = make_candidate(legs=1, id="B#0")
    counted = summary(vetoes(a) + vetoes(b))

    assert counted[VETO_EVIDENCE_TOO_WEAK] == 2


def test_the_no_atr_gate_agrees_with_the_engine_level_refusal() -> None:
    """`decide()` refuses before it gates, so the gate is only reachable by a
    caller driving `vetoes_for` directly. It has to agree, or the two paths would
    describe the same market differently."""
    assert VETO_NO_ATR in blocking_codes(
        vetoes_for(make_candidate(), close=104.0, atr=0.0, config=CFG)
    )
    assert decide(
        [make_candidate()], bars=BARS, last_closed=9, atr=0.0
    ).reason == REASON_NO_ANALYSIS


# --------------------------------------------------------------------------
# Abstention
# --------------------------------------------------------------------------


def test_nothing_is_ranked_when_every_candidate_is_vetoed() -> None:
    """Ranking the least bad candidate would be a recommendation this layer has
    not earned, so the answer is WAIT with the gates named."""
    result = decide(
        [make_candidate(legs=1, id="A#0"), make_candidate(legs=1, id="B#0")],
        bars=BARS,
        last_closed=9,
        atr=ATR,
    )

    assert result.action == Action.WAIT.value
    assert result.reason == REASON_ALL_VETOED
    assert result.subject == ""
    assert result.plan is None
    assert result.considered["eligible"] == 0
    assert result.considered["blocking_summary"][VETO_EVIDENCE_TOO_WEAK] == 2
    # The per-candidate detail survives the abstention.
    assert len(result.vetoes) >= 2
    assert "gates that fired" in result.explanation[1]


def test_an_abstention_still_reports_how_to_change_the_answer() -> None:
    """A reader who disagrees with the outcome should see which knob to turn
    rather than having to look up six."""
    result = decide([make_candidate(legs=1)], bars=BARS, last_closed=9, atr=ATR)
    text = " ".join(result.explanation)

    for key in ("min_score", "min_rr", "max_late_atr", "max_failed_attempts"):
        assert key in text


def test_a_conflict_between_the_two_sides_is_a_wait() -> None:
    """Both directions eligible with neither dominating is a disagreement, not a
    reading. The gap is compared in percentage points against `conflict_ppts`, and
    80 against 75 is a 5-point gap under the default limit of 10."""
    bull = make_candidate(
        id="BULL#0", factors=weighted(0.80, direction=1)
    )
    bear = make_candidate(
        id="BEAR#0", direction=-1, factors=weighted(0.75, direction=-1)
    )
    assert bull.evidence_ppts == pytest.approx(80.0)
    assert bear.evidence_ppts == pytest.approx(75.0)

    result = decide([bull, bear], bars=BARS, last_closed=9, atr=ATR)
    assert result.action == Action.WAIT.value
    assert result.reason == REASON_CONFLICT
    assert result.sides == {"bull_ppts": 80.0, "bear_ppts": 75.0}
    assert result.subject == "" and result.plan is None

    # Narrowing the allowed conflict to below the gap resolves it.
    resolved = decide(
        [bull, bear],
        bars=BARS,
        last_closed=9,
        atr=ATR,
        config=AnalyzerConfig(conflict_ppts=4.9),
    )
    assert resolved.action == Action.BUY.value
    assert resolved.reason == REASON_RANKED


def test_a_conflict_exactly_at_the_limit_is_resolved_not_waited() -> None:
    """`conflict_ppts` is exclusive: only a gap *below* it is a conflict."""
    bull = make_candidate(id="BULL#0", factors=weighted(0.80, direction=1))
    bear = make_candidate(
        id="BEAR#0", direction=-1, factors=weighted(0.75, direction=-1)
    )

    result = decide(
        [bull, bear],
        bars=BARS,
        last_closed=9,
        atr=ATR,
        config=AnalyzerConfig(conflict_ppts=5.0),
    )

    assert result.action == Action.BUY.value


def test_one_side_alone_cannot_be_in_conflict() -> None:
    result = decide(
        [make_candidate(legs=4, id="BULL#0")], bars=BARS, last_closed=9, atr=ATR
    )

    assert result.action == Action.BUY.value
    assert result.sides["bear_ppts"] == 0.0


# --------------------------------------------------------------------------
# Candidates and evidence
# --------------------------------------------------------------------------


def test_a_candidate_carries_its_plan_its_bundle_and_its_score_together() -> None:
    """The three travel together because a plan alone cannot be judged and a
    score alone cannot be acted on — and the score is computed once, at
    construction, so the gate and the report cannot disagree."""
    candidate = make_candidate()
    payload = candidate.to_dict()

    assert payload["plan"]["subject"] == candidate.plan.subject
    assert payload["bundle"]["subject"] == candidate.candidate_id
    assert payload["evidence"]["value"] == candidate.evidence_value
    assert candidate.evidence_ppts == candidate.evidence_value * 100.0


def test_candidates_are_built_from_findings_in_the_order_they_arrived() -> None:
    """Registration order is what makes `candidate_id` and the ranking
    reproducible, so it is preserved rather than sorted."""
    findings = [
        SetupFinding(
            detector="PULLBACK_H",
            kind="DEFAULT",
            direction=1,
            found=True,
            payload={
                "found": True,
                "direction": 1,
                "setup_type": "H2",
                "state": "CONFIRMED",
                "reference_price": 104.0,
                "stop_price": 100.0,
                "signal_bar": 9,
                "extreme_price": 100.0,
            },
        ),
        SetupFinding(
            detector="PULLBACK_L",
            kind="DEFAULT",
            direction=-1,
            found=True,
            payload={"found": True, "direction": -1, "setup_type": "L1", "state": "PROVISIONAL"},
        ),
    ]
    candidates = candidates_from_findings(
        findings, bars=BARS, last_closed=9, atr=ATR, config=CFG
    )

    assert [c.candidate_id for c in candidates] == ["PULLBACK_H#0", "PULLBACK_L#1"]
    assert candidates[0].plan.stop_basis == "PULLBACK_EXTREME"
    assert candidates[1].plan.direction == -1


def test_a_finding_with_a_malformed_payload_is_skipped() -> None:
    broken = SetupFinding(
        detector="MYSTERY", kind="DEFAULT", direction=1, found=True, payload=None
    )

    assert candidates_from_findings(
        [broken], bars=BARS, last_closed=9, atr=ATR, config=CFG
    ) == []


def test_context_joins_every_bundle_because_it_is_part_of_the_claim() -> None:
    """The same pullback in a strong trend and in a tight range are not the same
    claim, so the context cannot be a separate input the decision might skip.

    The assertion is on *contribution*, not on the score rising: `score()` balances
    sources, so adding a second source whose factors are mostly bare assertions
    can pull the aggregate down. That is the Phase 13 rule working, not a bug, and
    a test claiming "context always raises the score" would be claiming something
    the model does not do.
    """
    payload = {"direction": 1, "state": "CONFIRMED", "setup_type": "H2"}
    bare = bundle_for("PULLBACK", payload)
    with_context = bundle_for(
        "PULLBACK",
        payload,
        {"evidence": ["STRONG_EMA_TREND_SLOPE: 1.00", "RANGE_TIGHTENING_COMPRESSION"]},
    )

    assert [f.source for f in bare.factors] == ["PULLBACK"]
    assert "MARKET_STATE" in {f.source for f in with_context.factors}
    assert "MARKET_STATE" in score(with_context).by_source
    assert "MARKET_STATE" not in score(bare).by_source


def test_an_unknown_family_contributes_no_factors_rather_than_a_wrong_number() -> None:
    bundle = bundle_for("NOT_A_FAMILY", {"direction": 1, "state": "X"})

    assert bundle.factors == ()
    assert score(bundle).is_usable is False


def test_the_bundle_subject_names_what_the_payload_actually_is() -> None:
    assert bundle_for("PULLBACK", {"setup_type": "H2"}).subject == "PULLBACK:H2"
    assert bundle_for("MEASURED_MOVE", {"family": "RANGE"}).subject == (
        "MEASURED_MOVE:RANGE"
    )
    assert bundle_for("BREAKOUT", {}).subject == "BREAKOUT:NONE"


# --------------------------------------------------------------------------
# Serialisation and the closed-bar contract
# --------------------------------------------------------------------------


def test_the_decision_round_trips_through_json() -> None:
    result = decide([make_candidate()], bars=BARS, last_closed=9, atr=ATR)
    restored = json.loads(json.dumps(result.to_dict()))

    assert restored["action"] == Action.BUY.value
    assert restored["ranking_basis"] == list(RANKING_BASIS)
    assert restored["is_probability"] is False
    assert restored["explanation"] == list(result.explanation)


def test_the_decision_cannot_see_a_bar_after_its_own() -> None:
    """The invariant, restated: appending bars must not change the decision for an
    earlier index, and the late-trade gate is the most obvious way to break it."""
    longer = BARS + [{"o": 200.0, "h": 201.0, "l": 199.0, "c": 200.0}] * 5
    candidate = make_candidate()

    at_bar = decide([candidate], bars=BARS, last_closed=9, atr=ATR)
    with_future = decide([candidate], bars=longer, last_closed=9, atr=ATR)

    assert at_bar.to_dict() == with_future.to_dict()


def test_a_bar_index_past_the_data_is_clamped_not_rejected() -> None:
    result = decide([make_candidate()], bars=BARS, last_closed=99, atr=ATR)

    assert result.action == Action.BUY.value


def test_a_veto_serialises_with_its_comparison_and_its_key() -> None:
    veto = Veto(
        code="X", subject="S", detail="d", blocking=False, config_key="min_rr"
    )

    assert veto.to_dict() == {
        "code": "X",
        "subject": "S",
        "detail": "d",
        "blocking": False,
        "config_key": "min_rr",
    }


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_the_six_decision_keys_are_now_read() -> None:
    """They were declared and consumed by nothing for three phases. A test that
    each one changes an outcome is the only way that stops being true again."""
    candidate = make_candidate(legs=1, id="A#0")

    assert VETO_EVIDENCE_TOO_WEAK in codes(candidate)
    assert VETO_EVIDENCE_TOO_WEAK not in codes(
        candidate, config=AnalyzerConfig(min_score=0.1)
    )

    thin = make_candidate(
        payload={
            "direction": 1,
            "verdict": "MAJOR",
            "satisfied": ["L0", "L1", "L2", "L3"],
            "missing": [],
            "cross_bar": 9,
            "reference_price": 104.0,
            "stop_price": 90.0,
        },
        family="PULLBACK",
    )
    assert VETO_RISK_REWARD_TOO_LOW in codes(thin)
    assert VETO_RISK_REWARD_TOO_LOW not in codes(
        thin, config=AnalyzerConfig(min_rr=0.1)
    )

    assert VETO_TRADE_IS_LATE in codes(candidate, close=110.0)
    assert VETO_TRADE_IS_LATE not in codes(
        candidate, close=110.0, config=AnalyzerConfig(max_late_atr=99.0)
    )

    assert VETO_TOO_MANY_FAILED_ATTEMPTS not in codes(candidate)
    assert not decide([candidate], bars=BARS, last_closed=9, atr=ATR).is_actionable
    assert not decide(
        [candidate],
        bars=BARS,
        last_closed=9,
        atr=ATR,
        config=AnalyzerConfig(enable_decision=False),
    ).is_actionable
    assert (
        decide(
            [make_candidate(legs=4), make_candidate(legs=2, direction=-1, id="B#1")],
            bars=BARS,
            last_closed=9,
            atr=ATR,
            config=AnalyzerConfig(conflict_ppts=99.0),
        ).reason
        == REASON_CONFLICT
    )


def test_min_score_is_on_the_same_scale_as_the_evidence_score() -> None:
    """Its declared default was 40.0, on a 0-100 scale the Phase 13 model never
    had. On a 0..1 score it rejected every candidate, including a perfect one."""
    perfect = make_candidate(legs=4)
    assert perfect.evidence_value == pytest.approx(1.0)
    assert AnalyzerConfig().min_score <= 1.0
    assert VETO_EVIDENCE_TOO_WEAK not in codes(perfect, config=CFG)


def test_the_decision_keys_round_trip_through_config() -> None:
    config = AnalyzerConfig(
        enable_decision=False,
        min_score=0.55,
        min_rr=2.0,
        max_late_atr=0.25,
        conflict_ppts=5.0,
        max_failed_attempts=1,
    )

    assert AnalyzerConfig.from_dict(config.to_dict()) == config
