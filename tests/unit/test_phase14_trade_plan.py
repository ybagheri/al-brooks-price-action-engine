"""Tests for the trade plan engine (Phase 14).

A `TradePlan` is the geometry of a hypothetical trade: entry, stop, target, and
the distance between them. These tests pin the four properties that make that
geometry defensible rather than merely plausible:

1. **Every level carries a basis.** A stop at `101.20` means something different
   when it came from a swing low than when it came from an ATR multiple, and a
   volatility fallback must never be readable as a structural claim.
2. **Issues are arithmetic; warnings are not acted on.** `is_valid` means the
   three prices are on the correct sides of each other and nothing more. Gating
   on merit belongs to Phase 15, so a plan this module considers weak is still
   returned, with the reason attached.
3. **A plan is not a recommendation, a ranking, or an order.** No score here is a
   probability, plans come back in registration order, and nothing in the module
   sizes or prices a position.
4. **Closed bars only.** The plan for a given bar is identical whether or not
   later bars exist — including when the caller hands over swings whose right-side
   confirmation lands *after* that bar.

Expected values are computed by hand in the comments rather than taken from
whatever the implementation produces, so a change in the arithmetic has to be
deliberate. Floats that are exact in binary (`104 - 99.5`) are compared with `==`
on purpose; only the divisions use `pytest.approx`.
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from albrooks.core.swings import SwingPoint
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.setups.base import SetupFinding
from albrooks.trade.plan import (
    ANATOMY_BY_FAMILY,
    BLOCKING_ISSUES,
    DEFAULT_ANATOMY,
    ENTRY_BASIS_LAST_CLOSE,
    ENTRY_BASIS_NONE,
    ENTRY_BASIS_SETUP,
    ISSUE_ENTRY_UNDEFINED,
    ISSUE_NO_ATR,
    ISSUE_NO_DIRECTION,
    ISSUE_RISK_NOT_POSITIVE,
    ISSUE_STOP_NOT_PROTECTIVE,
    ISSUE_STOP_UNDEFINED,
    ISSUE_TARGET_NOT_AHEAD,
    ISSUE_TARGET_UNDEFINED,
    NOTE_DOUBLE_TARGET_NOT_MEASURED,
    NOTE_REVERSAL_HAS_NO_LEVELS,
    STOP_BASIS_ATR,
    STOP_BASIS_BREAKOUT_REFERENCE,
    STOP_BASIS_NONE,
    STOP_BASIS_PATTERN_EXTREME,
    STOP_BASIS_PULLBACK_EXTREME,
    STOP_BASIS_SWING,
    TARGET_BASIS_ATR,
    TARGET_BASIS_FADE_ORIGIN,
    TARGET_BASIS_MEASURED_MOVE,
    TARGET_BASIS_NONE,
    TARGET_BASIS_SWING,
    WARN_EVIDENCE_NOT_A_PROBABILITY,
    WARN_STOP_WIDE,
    WARN_TARGET_DROPPED,
    WARN_TERMINAL_SETUP,
    WARN_VOLATILITY_FALLBACK_STOP,
    WARN_VOLATILITY_FALLBACK_TARGET,
    SetupAnatomy,
    TradePlan,
    anatomy_for,
    build_trade_plan,
    plans_from_findings,
)

#: Defaults, spelled out so the expected numbers below are readable.
#: buffer = 0.25 * atr; fallback stop = 1.0 * atr; fallback target = 2.0 * atr.
CFG = AnalyzerConfig()
ATR = 2.0


def make_bars(closes: list[float], pad: float = 0.5) -> list[dict[str, float]]:
    """A deterministic bar series from a list of closes."""
    return [
        {"time": float(i), "o": c, "h": c + pad, "l": c - pad, "c": c}
        for i, c in enumerate(closes)
    ]


def swing(bar: int, price: float, direction: int, k: int = 3) -> SwingPoint:
    """A fractal swing, confirmed `k` bars after the bar it sits on."""
    return SwingPoint(
        bar_index=bar,
        price=price,
        direction=direction,
        confirmed_bar_index=bar + k,
        is_high=direction > 0,
        is_low=direction < 0,
    )


#: Closes rising into bar 9, which closed at 104.0.
RALLY = make_bars([100.0, 101.0, 102.0, 103.0, 100.0, 101.0, 102.0, 103.0, 103.5, 104.0])

#: A bull pullback at bar 9: reference 104.0, the low it was built on 100.0.
BULL_PULLBACK: dict[str, object] = {
    "found": True,
    "setup_type": "H2",
    "legs": 2,
    "signal_bar": 9,
    "reference_price": 104.0,
    "stop_price": 100.0,
    "direction": 1,
    "state": "CONFIRMED",
    "extreme_bar": 4,
    "extreme_price": 100.0,
}


def plan_bull(payload: Any = None, **kwargs: Any) -> TradePlan:
    """A plan for the bull-pullback fixture, with any argument overridable."""
    return build_trade_plan(
        "PULLBACK_H",
        BULL_PULLBACK if payload is None else payload,
        bars=kwargs.pop("bars", RALLY),
        bar_index=kwargs.pop("bar_index", 9),
        atr=kwargs.pop("atr", ATR),
        anatomy=anatomy_for("PULLBACK"),
        config=kwargs.pop("config", CFG),
        **kwargs,
    )


# --------------------------------------------------------------------------
# Geometry: the happy paths, with hand-computed numbers
# --------------------------------------------------------------------------


def test_a_bull_pullback_plan_is_exact_arithmetic() -> None:
    """entry 104; stop = pullback low 100 less the 0.25*2 = 0.5 buffer = 99.5;
    target = 104 + 2.0*2 = 108. So risk 4.5, reward 4.0."""
    plan = plan_bull()

    assert plan.entry == 104.0
    assert plan.stop == 99.5
    assert plan.target == 108.0
    assert plan.entry_basis == ENTRY_BASIS_SETUP
    assert plan.stop_basis == STOP_BASIS_PULLBACK_EXTREME
    assert plan.target_basis == TARGET_BASIS_ATR
    assert plan.risk == pytest.approx(4.5)
    assert plan.reward == pytest.approx(4.0)
    assert plan.reward_to_risk == pytest.approx(4.0 / 4.5)
    assert plan.is_valid
    assert plan.has_structural_stop


def test_the_short_case_is_the_long_case_mirrored() -> None:
    """Same algorithm, sign flipped: stop 104 + 0.5 = 104.5, target 100."""
    plan = build_trade_plan(
        "PULLBACK_L",
        {
            "direction": -1,
            "setup_type": "L2",
            "signal_bar": 9,
            "reference_price": 100.0,
            "stop_price": 104.0,
            "extreme_price": 104.0,
        },
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        anatomy=anatomy_for("PULLBACK"),
    )

    assert plan.is_short
    assert plan.stop == 104.5
    assert plan.target == 96.0
    assert plan.stop_reference == 104.0
    assert plan.risk == pytest.approx(4.5)
    assert plan.reward == pytest.approx(4.0)


def test_the_references_the_levels_came_from_travel_with_the_plan() -> None:
    """A reader has to be able to check a level against the setup it came from."""
    plan = plan_bull()

    assert plan.entry_reference == 104.0
    assert plan.stop_reference == 100.0
    # A volatility fallback has no reference: recording 0.0 would look like a
    # level at zero rather than the absence of one.
    assert plan.target_reference == 0.0


def test_a_breakout_is_stopped_beyond_the_reference_and_entered_at_the_close() -> None:
    """A breakout reference is a level price is *leaving*, not trading at, so the
    entry is the close and the stop sits behind the reference that was broken."""
    plan = build_trade_plan(
        "BREAKOUT",
        {
            "direction": 1,
            "breakout_bar": 9,
            "reference_price": 103.0,
            "reference_kind": "SWING",
            "outcome": "PENDING",
            "state": "BREAKOUT",
        },
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        anatomy=anatomy_for("BREAKOUT"),
    )

    assert plan.entry == 104.0  # the close of bar 9
    assert plan.entry_basis == ENTRY_BASIS_LAST_CLOSE
    assert plan.stop == 102.5  # 103.0 - 0.5 buffer
    assert plan.stop_basis == STOP_BASIS_BREAKOUT_REFERENCE
    assert plan.signal_bar == 9


def test_a_measured_move_uses_the_projection_target_and_its_own_origin_as_entry() -> None:
    """The origin is preferred over the wider reference, and the projected target
    is a target, not a fallback."""
    plan = build_trade_plan(
        "MEASURED_MOVE",
        {
            "direction": 1,
            "family": "RANGE",
            "target_price": 112.0,
            "reference_price": 100.0,
            "origin": {"bar_index": 4, "price": 105.0, "kind": "SWING"},
        },
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        anatomy=anatomy_for("MEASURED_MOVE"),
    )

    assert plan.entry == 105.0
    assert plan.entry_basis == ENTRY_BASIS_SETUP
    assert plan.target == 112.0
    assert plan.target_basis == TARGET_BASIS_MEASURED_MOVE
    assert plan.signal_bar == 4
    # No structural stop was supplied, so the plan says the stop is invented.
    assert plan.stop_basis == STOP_BASIS_ATR
    assert WARN_VOLATILITY_FALLBACK_STOP in plan.warnings


def test_a_fade_trades_the_fade_direction_not_the_projections() -> None:
    """`FadingSetup.direction` is the *projection's*. Reading it as the trade
    direction would produce a plan in the direction of the move being faded, which
    is the single easiest way to be wrong in this engine."""
    plan = build_trade_plan(
        "FADING_MEASURED_MOVE",
        {
            "direction": 1,  # the projection is bullish ...
            "fade_direction": -1,  # ... so the trade is short
            "state": "POTENTIAL",
            "target_price": 112.0,
            "created_bar": 4,
            "projection": {
                "direction": 1,
                "origin": {"bar_index": 4, "price": 100.0, "kind": "SWING"},
            },
        },
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        anatomy=anatomy_for("FADING_MEASURED_MOVE"),
    )

    assert plan.direction == -1
    assert plan.is_short
    # A fade aims back at where the projected move started, not at the MM target
    # it is fading: 100 is ahead of the 104 close for a short, 112 is not.
    assert plan.target == 100.0
    assert plan.target_basis == TARGET_BASIS_FADE_ORIGIN


def test_a_double_top_is_stopped_above_its_highest_extreme() -> None:
    """For a short the reference is max(price1, price2) = 101.0, so the stop sits
    at 101.5. Taking `price1` because it came first would put the stop *below* the
    second high — inside the pattern — on a bar-order change, which is the reason
    `stop_extreme_keys` is not `stop_keys`."""
    plan = build_trade_plan(
        "DOUBLE_TOP_MAJOR",
        {
            "direction": -1,
            "pattern_type": "MAJOR_DOUBLE_TOP",
            "bar1": 4,
            "bar2": 8,
            "price1": 101.0,
            "price2": 100.5,
            "level": 101.0,
        },
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        anatomy=anatomy_for("DOUBLE_TOP"),
    )

    assert plan.stop == 101.5
    assert plan.stop_basis == STOP_BASIS_PATTERN_EXTREME
    assert plan.signal_bar == 8
    assert NOTE_DOUBLE_TARGET_NOT_MEASURED in plan.warnings


def test_a_double_bottom_is_stopped_below_its_lowest_extreme() -> None:
    """min(price1, price2) = 100.5, less the 0.5 buffer."""
    plan = build_trade_plan(
        "DOUBLE_BOTTOM_MAJOR",
        {
            "direction": 1,
            "bar1": 4,
            "bar2": 8,
            "price1": 100.5,
            "price2": 101.0,
            "level": 100.5,
        },
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        anatomy=anatomy_for("DOUBLE_BOTTOM"),
    )

    assert plan.stop == 100.0
    assert plan.stop_basis == STOP_BASIS_PATTERN_EXTREME


def test_a_reversal_admits_it_has_no_price_structure() -> None:
    """`ReversalResult` is a checklist of satisfied legs. The plan must not dress
    a leg count up as a level."""
    plan = build_trade_plan(
        "REVERSAL_BULL",
        {
            "direction": 1,
            "verdict": "MAJOR",
            "score": 100,
            "cross_bar": 7,
            "satisfied": ["EMA_BREAK", "RETEST", "BO_FOLLOW"],
        },
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        anatomy=anatomy_for("REVERSAL"),
    )

    assert plan.stop_basis == STOP_BASIS_ATR
    assert not plan.has_structural_stop
    assert plan.signal_bar == 7
    assert NOTE_REVERSAL_HAS_NO_LEVELS in plan.warnings


# --------------------------------------------------------------------------
# Basis: the load-bearing property
# --------------------------------------------------------------------------


def test_every_level_states_why_it_is_the_number_it_is() -> None:
    """A price without a stated origin is the kind of number this project refuses
    to emit, and `to_dict()` is where a consumer reads it."""
    payload = plan_bull().to_dict()

    for key in ("entry_basis", "stop_basis", "target_basis"):
        assert payload[key] not in ("", None)


def test_a_volatility_fallback_is_labelled_and_never_reads_as_structure() -> None:
    """A plan without a stop is not a plan, so one is produced — but it says it
    is `plan_fallback_stop_atr` away from the entry, and `has_structural_stop` is
    False."""
    plan = build_trade_plan(
        "SOMETHING_NEW",
        {"direction": 1},
        bars=RALLY,
        bar_index=9,
        atr=ATR,
    )

    assert plan.stop == 102.0  # 104 close - 1.0 * atr
    assert plan.stop_basis == STOP_BASIS_ATR
    assert plan.stop_reference == 0.0  # no level, so no reference
    assert not plan.has_structural_stop
    assert WARN_VOLATILITY_FALLBACK_STOP in plan.warnings
    assert any("volatility multiple" in note for note in plan.management)


def test_a_confirmed_swing_becomes_the_stop_when_the_setup_names_no_level() -> None:
    plan = build_trade_plan(
        "SOMETHING_NEW",
        {"direction": 1},
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        swings=[swing(4, 101.0, -1)],
    )

    assert plan.stop == 100.5  # swing low 101.0 less the 0.5 buffer
    assert plan.stop_basis == STOP_BASIS_SWING
    assert WARN_VOLATILITY_FALLBACK_STOP not in plan.warnings


def test_a_swing_is_the_target_when_none_lies_ahead_of_the_entry() -> None:
    plan = build_trade_plan(
        "SOMETHING_NEW",
        {"direction": 1},
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        swings=[swing(6, 110.0, 1)],
    )

    assert plan.target == 110.0
    assert plan.target_basis == TARGET_BASIS_SWING
    assert WARN_VOLATILITY_FALLBACK_TARGET not in plan.warnings


def test_the_most_recent_qualifying_swing_wins() -> None:
    plan = build_trade_plan(
        "SOMETHING_NEW",
        {"direction": 1},
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        swings=[swing(2, 99.0, -1), swing(6, 101.0, -1)],
    )

    assert plan.stop_reference == 101.0


# --------------------------------------------------------------------------
# Boundaries: the exact threshold values
# --------------------------------------------------------------------------


def test_a_stop_exactly_at_the_entry_is_zero_risk_not_a_wrong_side_stop() -> None:
    """The exact boundary. A reference 0.5 ATR away from the entry lands the stop
    on the entry itself, so the only true statement is that there is no risk in
    it — not that the stop is on the wrong side."""
    plan = plan_bull({**BULL_PULLBACK, "reference_price": 103.5, "stop_price": 104.0})

    assert plan.entry == 103.5
    assert plan.stop == 103.5
    assert ISSUE_STOP_NOT_PROTECTIVE not in plan.issues
    assert ISSUE_RISK_NOT_POSITIVE in plan.issues
    assert not plan.is_valid


def test_a_stop_just_past_the_entry_is_reported_rather_than_corrected() -> None:
    """A reference 0.6 above the entry puts the stop 0.1 above it. Clamping would
    invent a level nobody chose, so the plan reports and refuses to be valid."""
    plan = plan_bull({**BULL_PULLBACK, "reference_price": 103.6, "stop_price": 104.2})

    assert plan.entry == 103.6
    assert plan.stop == 103.7
    assert ISSUE_STOP_NOT_PROTECTIVE in plan.issues
    assert not plan.is_valid


def test_a_wide_stop_warns_exactly_at_the_configured_boundary() -> None:
    """At `plan_max_stop_atr` the risk is 3.0 * atr = 6.0 and there is no warning;
    a hair beyond it and there is. A warning, not a veto: gating is Phase 15's."""
    exact = plan_bull({**BULL_PULLBACK, "stop_price": 98.5})  # stop 98.0, risk 6.0
    beyond = plan_bull({**BULL_PULLBACK, "stop_price": 98.4})  # stop 97.9, risk 6.1

    assert exact.risk == pytest.approx(6.0)
    assert WARN_STOP_WIDE not in exact.warnings
    assert beyond.risk > 6.0
    assert WARN_STOP_WIDE in beyond.warnings
    # Warned, still valid: this layer does not decide what is worth taking.
    assert beyond.is_valid


def test_zero_risk_reports_a_zero_ratio_rather_than_infinity() -> None:
    """`inf` would travel into JSON as a non-standard literal, and a plan with no
    risk is not a good plan — it is not a plan."""
    plan = plan_bull({**BULL_PULLBACK, "reference_price": 103.5, "stop_price": 104.0})

    assert plan.risk == 0.0
    assert plan.reward_to_risk == 0.0
    assert not math.isinf(plan.reward_to_risk)
    assert "Infinity" not in json.dumps(plan.to_dict())


def test_a_projected_target_exactly_at_the_entry_is_dropped() -> None:
    """Strictly ahead, or not a target. Equal is the exact boundary."""
    plan = build_trade_plan(
        "MEASURED_MOVE",
        {
            "direction": 1,
            "target_price": 104.0,
            "origin": {"bar_index": 4, "price": 104.0},
        },
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        anatomy=anatomy_for("MEASURED_MOVE"),
    )

    assert WARN_TARGET_DROPPED in plan.warnings
    assert plan.target_basis == TARGET_BASIS_ATR
    assert plan.target == 108.0


def test_a_projected_target_one_ulp_ahead_is_kept() -> None:
    plan = build_trade_plan(
        "MEASURED_MOVE",
        {
            "direction": 1,
            "target_price": 104.0 + 1e-9,
            "origin": {"bar_index": 4, "price": 104.0},
        },
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        anatomy=anatomy_for("MEASURED_MOVE"),
    )

    assert plan.target_basis == TARGET_BASIS_MEASURED_MOVE
    assert WARN_TARGET_DROPPED not in plan.warnings


def test_a_swing_exactly_at_the_entry_is_not_a_protective_stop() -> None:
    """The swing search is a strict inequality: a swing low at the entry leaves no
    room, and the plan falls back rather than stopping at the trade's own price."""
    plan = build_trade_plan(
        "SOMETHING_NEW",
        {"direction": 1},
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        swings=[swing(6, 104.0, -1)],
    )

    assert plan.stop_basis == STOP_BASIS_ATR
    assert plan.stop == 102.0


# --------------------------------------------------------------------------
# Invalid input
# --------------------------------------------------------------------------


def test_no_atr_leaves_the_volatility_dependent_levels_undefined() -> None:
    """A *structural* stop needs no ATR and survives one, because it came from the
    market. Only the parts that had to be invented fail, and the plan says which
    — which is the difference between "no volatility reference" and "no
    structure"."""
    plan = plan_bull(atr=0.0)

    assert ISSUE_NO_ATR in plan.issues
    assert plan.stop == 100.0
    assert plan.stop_basis == STOP_BASIS_PULLBACK_EXTREME
    assert ISSUE_TARGET_UNDEFINED in plan.issues
    assert not plan.is_valid


def test_no_atr_and_no_structure_leaves_the_stop_undefined_rather_than_zero() -> None:
    plan = build_trade_plan(
        "SOMETHING_NEW", {"direction": 1}, bars=RALLY, bar_index=9, atr=0.0
    )

    assert ISSUE_NO_ATR in plan.issues
    assert ISSUE_STOP_UNDEFINED in plan.issues
    assert ISSUE_TARGET_UNDEFINED in plan.issues
    assert plan.stop_basis == STOP_BASIS_NONE
    assert plan.target_basis == TARGET_BASIS_NONE
    assert plan.stop == 0.0
    assert not plan.is_valid


def test_no_bars_reports_an_undefined_entry_instead_of_raising() -> None:
    plan = build_trade_plan(
        "SOMETHING_NEW", {"direction": 1}, bars=[], bar_index=0, atr=ATR
    )

    assert ISSUE_ENTRY_UNDEFINED in plan.issues
    assert plan.entry_basis == ENTRY_BASIS_NONE
    assert not plan.is_valid


def test_a_setup_level_survives_being_given_no_bars() -> None:
    """The counterpart: a level the setup recorded is a fact about the setup, not
    about the bars, so it does not need a series to be read."""
    plan = build_trade_plan(
        "PULLBACK_H",
        BULL_PULLBACK,
        bars=[],
        bar_index=0,
        atr=ATR,
        anatomy=anatomy_for("PULLBACK"),
    )

    assert plan.entry == 104.0
    assert plan.entry_basis == ENTRY_BASIS_SETUP
    assert ISSUE_ENTRY_UNDEFINED not in plan.issues


def test_a_negative_bar_index_reports_an_undefined_entry() -> None:
    plan = build_trade_plan(
        "SOMETHING_NEW", {"direction": 1}, bars=RALLY, bar_index=-1, atr=ATR
    )

    assert ISSUE_ENTRY_UNDEFINED in plan.issues
    assert plan.bar_index == -1


def test_a_bar_index_past_the_data_is_clamped_not_rejected() -> None:
    """Matching every detector in the engine: asking for the whole series is the
    useful reading, so it is not an error."""
    plan = plan_bull(bar_index=10_000)

    assert plan.bar_index == 9
    assert plan.is_valid


def test_a_setup_with_no_direction_gets_no_levels_invented() -> None:
    """Without a direction there is no protective side to reason about, so a stop
    would be a level derived from a trade that does not exist."""
    plan = build_trade_plan(
        "PULLBACK_H",
        {"reference_price": 104.0, "stop_price": 100.0},
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        anatomy=anatomy_for("PULLBACK"),
    )

    assert ISSUE_NO_DIRECTION in plan.issues
    assert plan.stop == 0.0
    assert plan.target == 0.0
    assert not plan.is_valid


@pytest.mark.parametrize("junk", [0.0, -1.0, float("nan"), float("inf"), "abc", None])
def test_a_price_the_setup_did_not_actually_record_is_never_used(junk: object) -> None:
    """`0.0` is this engine's "not observed" default for a price, so reading it as
    a level would put an entry at zero."""
    plan = plan_bull({**BULL_PULLBACK, "reference_price": junk, "stop_price": junk})

    assert plan.entry == 104.0  # the close, because the setup named no price
    assert plan.entry_basis == ENTRY_BASIS_LAST_CLOSE
    assert plan.stop == 102.0
    assert plan.is_valid  # the levels that were derived are all well placed


def test_direction_is_normalised_to_its_sign() -> None:
    """A detector reporting 100 and one reporting 1 mean the same thing, and the
    geometry must not depend on which."""
    small = plan_bull({**BULL_PULLBACK, "direction": 1})
    large = plan_bull({**BULL_PULLBACK, "direction": 100})

    assert large.direction == 1
    assert (large.entry, large.stop, large.target) == (small.entry, small.stop, small.target)


def test_every_issue_is_declared_blocking() -> None:
    """Guards against a new issue code being added to the module and quietly
    becoming advisory, which would make `is_valid` lie."""
    from albrooks.trade import plan as module

    declared = {
        value
        for name, value in vars(module).items()
        if name.startswith("ISSUE_") and isinstance(value, str)
    }
    assert declared == set(BLOCKING_ISSUES)


# --------------------------------------------------------------------------
# Closed bars only
# --------------------------------------------------------------------------


def test_a_plan_cannot_see_a_bar_after_its_own() -> None:
    """The invariant, restated for this layer: the plan for bar 9 is identical
    whether or not bars 10..40 exist."""
    long_series = RALLY + make_bars([105.0, 90.0, 120.0] * 10)
    swings = [swing(4, 100.0, -1), swing(6, 110.0, 1)]

    short = plan_bull(swings=swings)
    long = plan_bull(bars=long_series, swings=swings)

    assert short.to_dict() == long.to_dict()


def test_a_swing_confirmed_after_the_plan_is_not_used() -> None:
    """The important half of the no-lookahead property. A fractal swing is only
    knowable `k` bars after it happens, so a plan dated at bar 6 must not use a
    swing confirmed at bar 8 — doing so would let a swing's own future decide
    where the stop goes."""
    plan = build_trade_plan(
        "SOMETHING_NEW",
        {"direction": 1},
        bars=RALLY,
        bar_index=6,
        atr=ATR,
        swings=[swing(5, 98.0, -1)],  # confirmed at bar 8, two bars too late
    )

    assert plan.stop_basis == STOP_BASIS_ATR
    assert plan.stop == 100.0  # close 102.0 at bar 6 less 1.0 * atr


def test_the_same_swing_is_used_once_it_is_confirmed() -> None:
    """The other half: the exclusion is about the bar index, not about swings."""
    later = build_trade_plan(
        "SOMETHING_NEW",
        {"direction": 1},
        bars=RALLY,
        bar_index=8,
        atr=ATR,
        swings=[swing(5, 98.0, -1)],
    )

    assert later.stop_basis == STOP_BASIS_SWING
    assert later.stop == 97.5


def test_the_no_lookahead_fixture_is_not_vacuous() -> None:
    """A test comparing two empty plans passes forever. This asserts the fixture
    actually produces a real plan with a real structural stop and target, so the
    comparison cannot quietly become empty."""
    plan = build_trade_plan(
        "SOMETHING_NEW",
        {"direction": 1},
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        swings=[swing(4, 100.0, -1), swing(6, 110.0, 1)],
    )

    assert plan.is_valid
    assert plan.stop_basis == STOP_BASIS_SWING
    assert plan.target_basis == TARGET_BASIS_SWING
    assert plan.risk > 0.0 and plan.reward > 0.0


# --------------------------------------------------------------------------
# Not a recommendation, not a ranking, not an order
# --------------------------------------------------------------------------


def test_the_serialised_plan_says_it_is_not_a_recommendation() -> None:
    assert plan_bull().to_dict()["is_recommendation"] is False


def test_the_plan_carries_no_position_size_lot_or_order_type() -> None:
    """Sizing needs an account risk policy this project does not have, and order
    types belong to the execution layer. Neither belongs in the output."""
    keys = set(plan_bull().to_dict())

    for forbidden in ("lots", "volume", "size", "order_type", "slippage", "sl"):
        assert forbidden not in keys


def test_an_evidence_score_is_passed_through_never_computed_and_never_a_probability() -> None:
    """Phase 13's score is a mean of factor weights. Attaching one to a plan must
    not make it look like a forecast, so the plan says so itself."""
    plan = plan_bull(evidence_score=0.82)

    assert plan.evidence_score == 0.82
    assert WARN_EVIDENCE_NOT_A_PROBABILITY in plan.warnings
    assert "is_probability" not in plan.to_dict()


def test_plans_from_findings_keeps_registration_order_rather_than_ranking() -> None:
    """A better plan later in the list must not be promoted to the front. The
    registry documents its order as deterministic and explicitly not a ranking."""
    good = SetupFinding(
        detector="MEASURED_MOVE",
        kind="MEASURED_MOVE",
        direction=1,
        found=True,
        payload={
            "direction": 1,
            "target_price": 120.0,
            "origin": {"bar_index": 4, "price": 104.0},
        },
    )
    poor = SetupFinding(
        detector="PULLBACK_H",
        kind="DEFAULT",
        direction=1,
        found=True,
        payload={
            "direction": 1,
            "reference_price": 104.0,
            "stop_price": 60.0,
        },
    )

    plans = plans_from_findings([good, poor], bars=RALLY, bar_index=9, atr=ATR)
    worse_first = plans_from_findings([poor, good], bars=RALLY, bar_index=9, atr=ATR)

    assert [p.subject for p in plans] == ["MEASURED_MOVE", "PULLBACK_H"]
    assert [p.subject for p in worse_first] == ["PULLBACK_H", "MEASURED_MOVE"]
    assert plans[0].reward_to_risk > plans[1].reward_to_risk
    assert plans[0].subject == "MEASURED_MOVE"  # not promoted to the front


def test_a_finding_whose_payload_is_not_a_mapping_is_skipped() -> None:
    """One malformed detector must not take the rest of the plans down."""
    broken = SetupFinding(
        detector="MYSTERY", kind="DEFAULT", direction=1, found=True, payload=None
    )

    assert plans_from_findings([broken], bars=RALLY, bar_index=9, atr=ATR) == []


def test_an_unknown_detector_still_gets_a_plannable_result() -> None:
    """A third-party detector should be plannable; a plan built from
    `DEFAULT_ANATOMY` says which levels are invented."""
    finding = SetupFinding(
        detector="MYSTERY", kind="DEFAULT", direction=1, found=True, payload={"direction": 1}
    )

    plans = plans_from_findings([finding], bars=RALLY, bar_index=9, atr=ATR)

    assert len(plans) == 1
    assert plans[0].entry_basis == ENTRY_BASIS_LAST_CLOSE
    assert plans[0].stop_basis == STOP_BASIS_ATR


def test_a_failed_breakout_is_reported_rather_than_silently_traded() -> None:
    """A failed breakout's geometry is still coherent arithmetic. Whether it
    deserves a plan is the decision engine's question — but the caller is told."""
    plan = build_trade_plan(
        "BREAKOUT",
        {"direction": 1, "reference_price": 103.0, "outcome": "FAILED", "state": "FAILED"},
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        anatomy=anatomy_for("BREAKOUT"),
    )

    assert WARN_TERMINAL_SETUP in plan.warnings
    assert plan.is_valid  # geometry is fine; the warning is what the reader needs


# --------------------------------------------------------------------------
# Extensibility and serialisation
# --------------------------------------------------------------------------


def test_a_new_family_is_a_table_row_not_a_new_builder() -> None:
    """`ARCHITECTURE.md` §9 makes this claim for setup detectors; the trade layer
    holds to the same rule."""
    anatomy = SetupAnatomy(
        family="MY_SETUP",
        direction_keys=("bias",),
        entry_keys=("mid",),
        stop_keys=("floor",),
        stop_basis=STOP_BASIS_PULLBACK_EXTREME,
    )
    ANATOMY_BY_FAMILY["MY_SETUP"] = anatomy
    try:
        assert anatomy_for("MY_SETUP") is anatomy
        plan = build_trade_plan(
            "MY_SETUP",
            {"bias": -1, "mid": 100.0, "floor": 104.0},
            bars=RALLY,
            bar_index=9,
            atr=ATR,
            anatomy=anatomy_for("MY_SETUP"),
        )
        assert plan.is_short
        assert plan.entry == 100.0
        assert plan.stop == 104.5
    finally:
        del ANATOMY_BY_FAMILY["MY_SETUP"]


def test_an_unknown_family_falls_back_to_derived_levels_rather_than_raising() -> None:
    assert anatomy_for("NO_SUCH_FAMILY") is DEFAULT_ANATOMY


def test_the_plan_round_trips_through_json_with_its_caveats_intact() -> None:
    plan = plan_bull({**BULL_PULLBACK, "state": "INVALIDATED"}, evidence_score=0.5)
    restored = json.loads(json.dumps(plan.to_dict()))

    assert restored["stop_basis"] == STOP_BASIS_PULLBACK_EXTREME
    assert restored["warnings"] == list(plan.warnings)
    assert restored["is_recommendation"] is False
    assert restored["reward_to_risk"] == pytest.approx(plan.reward_to_risk)
    assert WARN_TERMINAL_SETUP in restored["warnings"]


def test_the_invalidation_text_names_the_level_it_means() -> None:
    plan = plan_bull()

    assert "100" in plan.invalidation
    assert "extreme_price" in plan.invalidation


def test_a_volatility_only_plan_says_it_has_no_invalidation_level() -> None:
    plan = build_trade_plan(
        "SOMETHING_NEW", {"direction": 1}, bars=RALLY, bar_index=9, atr=ATR
    )

    assert "No structural level is available" in plan.invalidation


def test_a_hand_built_plan_cannot_claim_geometry_it_does_not_have() -> None:
    """The three geometric issues are read off the numbers by the model, not
    asserted by the builder, so a `TradePlan` assembled by a caller, a future
    layer, or a test cannot be `is_valid` with a target behind the entry."""
    plan = TradePlan(subject="HAND_WRITTEN", direction=1, entry=100.0, stop=99.0, target=98.0)

    assert ISSUE_TARGET_NOT_AHEAD in plan.issues
    assert not plan.is_valid


def test_a_target_distance_configured_to_zero_is_reported_as_not_ahead() -> None:
    """The only way the builder can produce a target that is not ahead: a user
    setting the fallback distance to zero. An unreachable issue code would be
    worse than none, so the misconfiguration is reported rather than swallowed."""
    flat = build_trade_plan(
        "SOMETHING_NEW",
        {"direction": 1},
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        config=AnalyzerConfig(plan_fallback_target_atr=0.0),
    )
    any_distance = build_trade_plan(
        "SOMETHING_NEW",
        {"direction": 1},
        bars=RALLY,
        bar_index=9,
        atr=ATR,
        config=AnalyzerConfig(plan_fallback_target_atr=0.1),
    )

    assert flat.target == 104.0
    assert ISSUE_TARGET_NOT_AHEAD in flat.issues
    assert not flat.is_valid
    assert any_distance.is_valid
    assert ISSUE_TARGET_NOT_AHEAD not in any_distance.issues


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_the_new_plan_thresholds_round_trip_through_config() -> None:
    """ARCHITECTURE.md §11: every threshold is configurable rather than a literal
    in a detector, and configuration round-trips."""
    config = AnalyzerConfig(
        plan_stop_buffer_atr=0.4,
        plan_fallback_stop_atr=1.5,
        plan_fallback_target_atr=3.0,
        plan_max_stop_atr=4.0,
    )
    payload = config.to_dict()

    assert AnalyzerConfig.from_dict(payload) == config
    assert payload["plan_stop_buffer_atr"] == 0.4


def test_the_config_thresholds_actually_move_the_levels() -> None:
    generous = AnalyzerConfig(plan_stop_buffer_atr=1.0)
    plan = plan_bull(config=generous)

    # 100.0 less 1.0 * 2.0 = 98.0
    assert plan.stop == 98.0
    assert plan.risk == pytest.approx(6.0)
