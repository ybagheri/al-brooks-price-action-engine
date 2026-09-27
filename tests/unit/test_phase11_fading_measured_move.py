"""Tests for the Fading Measured Move lifecycle (Phase 11).

The measured-move suite pins the projection *geometry*. These tests pin the
*lifecycle* built on top of it, and the discipline the lifecycle encodes:

> Touch is not a fade. Approaching a target means nothing; arriving at it with
> exhaustion is the observation; a signal bar is the confirmation.

Three properties are load-bearing and are asserted structurally rather than by
comparing against hand-computed numbers:

1. **At most one transition per bar.** The lifecycle is auditable bar by bar, so
   a single bar can never skip from `PROJECTED` to `CONFIRMED`.
2. **Terminal states are terminal.** `COMPLETED` and `INVALIDATED` freeze, so a
   projection that has played out cannot be revived by a later bar.
3. **Invalidation is state-independent.** A close blowing through the target
   disqualifies the projection whichever state it was in.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from albrooks.engine.configuration import AnalyzerConfig
from albrooks.price_action.bars import calculate_atr_series
from albrooks.price_action.exhaustion import ExhaustionStructure
from albrooks.setups.fading_measured_move import (
    FadingSetup,
    FMState,
    create_setups,
    has_follow_through,
    is_signal_bar,
    track_fading_measured_moves,
    update_setups,
)

CFG = AnalyzerConfig()
#: Every state, in the order the lifecycle can reach it.
ORDER = [
    FMState.PROJECTED,
    FMState.POTENTIAL,
    FMState.DEVELOPING,
    FMState.CONFIRMED,
    FMState.COMPLETED,
]


def mk(o: float, h: float, low: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low, "c": c}


#: A 90 -> 100 leg (3 bars, so it clears `min_leg_bars`), a pullback to 95, so
#: the projection is 90 + 10 = 105. Shared by every scenario below.
LEG = [
    mk(90, 91, 89, 90.2),
    mk(93, 95, 92, 94.0),
    mk(97, 99, 96, 98.0),
    mk(99, 101, 98, 100.0),
    mk(97, 98, 95, 95.5),
]
SWINGS = [
    {"bar": 20, "price": 90.0, "dir": -1, "confirmed_bar": 23},
    {"bar": 23, "price": 100.0, "dir": 1, "confirmed_bar": 26},
    {"bar": 24, "price": 95.0, "dir": -1, "confirmed_bar": 27},
]
TARGET = 105.0


def _filler(n: int = 20) -> list[dict[str, float]]:
    """Flat bars so ATR settles; without them the ATR-relative gates misbehave."""
    return [mk(96, 97, 95, 96) for _ in range(n)]


def _atr(bars: list[dict[str, float]]) -> float:
    atrs = calculate_atr_series(bars, 14)
    return atrs[len(bars) - 1]


def _no_exhaustion(idx: int, direction: int) -> ExhaustionStructure:
    """An exhaustion reading of zero, for pinning the gate."""
    return ExhaustionStructure(bar_index=idx, direction=direction, breadth=0)


def _some_exhaustion(idx: int, direction: int) -> ExhaustionStructure:
    """A single exhaustion condition, for pinning the gate."""
    return ExhaustionStructure(
        bar_index=idx, direction=direction, climax=True, breadth=1
    )


def _lifecycle(bars: list[dict[str, float]], config: AnalyzerConfig | None = None):
    """Run the full lifecycle bar by bar, returning the per-bar state trace."""
    cfg = config or CFG
    atr = _atr(bars)
    closed = len(bars) - 1
    setups = create_setups(bars, last_closed=closed, atr=atr, swings=SWINGS, config=cfg)
    trace: list[str] = []
    for step in range(closed + 1):
        setups = update_setups(setups, bars, step, closed, atr, config=cfg)
        trace.append(setups[0].state if setups else "NONE")
    return setups, trace, atr, closed



# --------------------------------------------------------------------------
# Reaching the states
# --------------------------------------------------------------------------


def test_a_projection_starts_projected_with_its_fade_direction_opposed() -> None:
    # The fixture must be long enough for every swing to be *confirmed*: the swing
    # that ends the leg is confirmed 3 bars later, so a fixture that stops at the
    # pullback has no usable swing triple and produces nothing at all.
    bars = _filler() + LEG + [
        mk(96, 97, 95.6, 96.5),
        mk(98, 100, 97.6, 99.5),
        mk(101, 104, 100.6, 103.5),
    ]
    setups = create_setups(
        bars, last_closed=len(bars) - 1, atr=_atr(bars), swings=SWINGS, config=CFG
    )
    assert setups
    first = setups[0]
    assert first.state == FMState.PROJECTED.value
    # A bull projection is *faded* short. Storing both directions separately is
    # what stops a consumer reading the projection direction as the trade direction.
    assert first.direction == 1
    assert first.fade_direction == -1
    assert first.direction == -first.fade_direction
    assert first.target_price == TARGET
    assert first.family == "REGULAR"
    assert first.state_bar == -1
    assert first.age == 0


def test_the_full_lifecycle_runs_in_order_and_ends_completed() -> None:
    """PROJECTED -> POTENTIAL -> DEVELOPING -> CONFIRMED -> COMPLETED."""
    bars = _filler() + LEG + [
        mk(96, 97, 95.6, 96.5),
        mk(98, 100, 97.6, 99.5),
        mk(101, 104, 100.6, 103.5),   # approaches the target
        mk(103, 105, 102.6, 104.8),   # touches it
        mk(104.5, 105.4, 103.8, 104.0),  # big bar at the target -> exhaustion
        mk(104.2, 105.2, 102.6, 102.8),  # signal bar down, at the target
        mk(102, 102.5, 100.0, 100.2),   # follow-through
    ]
    setups, trace, _, _ = _lifecycle(bars)

    # every state is visited, in order, and never out of order
    visited = [s for i, s in enumerate(trace) if i == 0 or trace[i - 1] != s]
    assert visited == ["PROJECTED", "POTENTIAL", "DEVELOPING", "CONFIRMED", "COMPLETED"]
    assert [ORDER.index(FMState(s)) for s in visited] == sorted(
        ORDER.index(FMState(s)) for s in visited
    )
    assert setups[0].state == FMState.COMPLETED.value


def test_potential_means_approached_not_reached() -> None:
    """The distinction the whole discipline rests on.

    `POTENTIAL` requires only that the bar's extreme comes within
    `fm_approach_atr`; the target itself need not be touched. A projection that
    approached and turned away must never have reported `DEVELOPING`.
    """
    bars = _filler() + LEG + [
        mk(96, 97, 95.6, 96.5),
        mk(98, 100, 97.6, 99.5),
        mk(101, 104, 100.6, 103.5),  # within 1 ATR of 105, high is 104
    ]
    _, trace, _, _ = _lifecycle(bars)
    assert FMState.POTENTIAL.value in trace
    assert FMState.DEVELOPING.value not in trace
    assert FMState.CONFIRMED.value not in trace


def test_a_touch_is_almost_always_accompanied_by_exhaustion_here() -> None:
    """A finding about the specification, recorded rather than worked around.

    The specification says "touch alone stays `POTENTIAL`", implying a touch with
    *no* exhaustion is reachable. With this engine's exhaustion conditions it
    essentially is not: the `overshoot` condition fires when the bar's extreme
    sits `> 0.3 ATR` past a 20-bar band **and is the extreme of that window**, and
    a bar that touches the measured-move target is by construction the extreme of
    the recent range. So `POTENTIAL -> DEVELOPING` almost always happens on the
    touching bar, and the exhaustion gate is nearly always satisfied by `overshoot`
    alone.

    The gate is still correct and still worth keeping — it is what stops a touch
    with no exhaustion at all from advancing, it is the specification's rule, and
    a future change to the exhaustion conditions would make it bind harder. But
    anyone reading the docs should know it binds more loosely than "touch alone
    stays POTENTIAL" suggests.

    This test pins the observation so that a change to `detect_overshoot` that
    alters it is noticed, rather than discovered later through a lifecycle that
    stopped behaving.
    """
    bars = _filler() + LEG + [
        mk(96, 97, 95.6, 96.5),
        mk(98, 100, 97.6, 99.5),
        mk(101, 104, 100.6, 103.5),
        mk(103, 105, 102.6, 104.8),  # touches the 105 target
    ]
    from albrooks.price_action.exhaustion import detect_exhaustion

    atr = _atr(bars)
    touch = detect_exhaustion(bars, len(bars) - 1, len(bars) - 1, 1, atr)
    assert bars[-1]["h"] == TARGET
    # the touching bar is the 20-bar extreme, so overshoot is satisfied
    assert touch.overshoot is True
    assert touch.breadth >= 1

    _, trace, _, _ = _lifecycle(bars)
    # ...and the lifecycle therefore reaches DEVELOPING on the touching bar
    assert FMState.DEVELOPING.value in trace


def test_developing_is_not_reached_when_the_target_is_never_touched() -> None:
    """The gate that does bind: approach without arrival is not enough."""
    bars = _filler() + LEG + [
        mk(96, 97, 95.6, 96.5),
        mk(98, 100, 97.6, 99.5),
        mk(101, 104, 100.6, 103.5),  # comes within 1 ATR but stops short
    ]
    _, trace, _, _ = _lifecycle(bars)
    assert FMState.POTENTIAL.value in trace
    assert FMState.DEVELOPING.value not in trace
    assert FMState.CONFIRMED.value not in trace


def test_the_exhaustion_gate_is_consulted_on_every_touch() -> None:
    """The gate is wired in, and the test does not rely on a fixture triggering it.

    Deleting the `structure.breadth >= 1` condition from the `POTENTIAL` branch
    left every other test in this file passing, because a bar that touches the
    target is almost always a 20-bar extreme and so trips `overshoot` anyway (see
    the observation test above). This one forces the branch to see an exhaustion
    reading of zero and asserts the transition is withheld, so the gate cannot be
    removed silently.

    `_advance` is called directly with a bar that touches the target, and the
    exhaustion measurement is replaced with a stub. Stubbing is justified here
    precisely because the real measurement cannot produce a zero reading on a
    touching bar — that is the very thing being pinned.
    """
    import albrooks.setups.fading_measured_move as module

    bars = _filler() + LEG + [
        mk(96, 97, 95.6, 96.5),
        mk(98, 100, 97.6, 99.5),
        mk(101, 105, 100.6, 104.9),  # high touches the 105 target
    ]
    atr = _atr(bars)
    idx = len(bars) - 1
    assert bars[idx]["h"] == TARGET

    # A setup already in POTENTIAL, aged once, positioned to test the branch.
    potential = FadingSetup(
        id=1, family="REGULAR", direction=1, target_price=TARGET, mm_range=10.0,
        created_bar=20, state=FMState.POTENTIAL.value, fade_direction=-1,
        age=1, state_age=1,
    )
    potential = potential.to_state(age=2, state_age=2)

    real = module.detect_exhaustion
    try:
        # zero exhaustion: the transition must be withheld
        module.detect_exhaustion = lambda *a, **k: _no_exhaustion(idx, 1)
        withheld = module._advance(potential, bars, idx, idx, atr, CFG)
        assert withheld.state == FMState.POTENTIAL.value
        assert "without exhaustion" in withheld.reason

        # any exhaustion: the transition must fire
        module.detect_exhaustion = lambda *a, **k: _some_exhaustion(idx, 1)
        advanced = module._advance(potential, bars, idx, idx, atr, CFG)
        assert advanced.state == FMState.DEVELOPING.value
        assert advanced.exhaustion_breadth == 1
    finally:
        module.detect_exhaustion = real



# --------------------------------------------------------------------------
# Invalidation
# --------------------------------------------------------------------------


def test_a_close_beyond_the_target_invalidates_the_projection() -> None:
    bars = _filler() + LEG + [
        mk(96, 97, 95.6, 96.5),
        mk(98, 100, 97.6, 99.5),
        mk(101, 104, 100.6, 103.5),
        mk(103, 108, 102.6, 107.0),  # closes 2.0 past the 105 target
    ]
    setups, trace, _, _ = _lifecycle(bars)
    assert FMState.INVALIDATED.value in trace
    assert setups[0].state == FMState.INVALIDATED.value
    assert setups[0].is_active is False
    assert "past the target" in setups[0].reason


def test_invalidation_applies_from_any_active_state() -> None:
    """The thesis is broken the moment price overshoots, whichever state it was in.

    Testing only from `PROJECTED` would allow a regression where, say, the
    `DEVELOPING` branch stopped checking and a blown-through projection kept
    reporting itself as a developing fade.
    """
    base = _filler() + LEG + [mk(96, 97, 95.6, 96.5)]
    bars = base + [
        mk(98, 100, 97.6, 99.5),
        mk(101, 104, 100.6, 103.5),
        mk(103, 108, 102.6, 107.0),   # closes past the target
    ]
    _, trace, _, _ = _lifecycle(bars)
    assert FMState.INVALIDATED.value in trace

    # and once invalidated, it stays invalidated no matter what follows
    bars = base + [
        mk(98, 100, 97.6, 99.5),
        mk(101, 104, 100.6, 103.5),
        mk(103, 108, 102.6, 107.0),   # invalidated here
        mk(107, 108, 103.0, 103.2),  # a large reversal signal bar
        mk(103, 103.5, 100.0, 100.2),
    ]
    setups, trace, _, _ = _lifecycle(bars)
    assert trace[-1] == FMState.INVALIDATED.value
    assert FMState.CONFIRMED.value not in trace
    assert FMState.COMPLETED.value not in trace
    assert setups[0].is_active is False


def test_a_projection_expires_instead_of_tracking_forever() -> None:
    """`fm_max_bars_forward` bounds how long a projection stays alive."""
    cfg = AnalyzerConfig(fm_max_bars_forward=5)
    bars = _filler() + LEG + [mk(96, 97, 95.6, 96.5) for _ in range(12)]
    setups, trace, _, _ = _lifecycle(bars, cfg)
    assert FMState.INVALIDATED.value in trace
    assert "expired" in setups[0].reason


def test_a_completed_projection_is_never_revived() -> None:
    """Terminal means terminal, in both directions."""
    bars = _filler() + LEG + [
        mk(96, 97, 95.6, 96.5),
        mk(98, 100, 97.6, 99.5),
        mk(101, 104, 100.6, 103.5),
        mk(103, 105, 102.6, 104.8),
        mk(104.5, 105.4, 103.8, 104.0),
        mk(104.2, 105.2, 102.6, 102.8),  # signal -> CONFIRMED
        mk(102, 102.5, 100.0, 100.2),    # -> COMPLETED
        mk(100, 100.5, 98.0, 98.2),      # would be another signal bar
        mk(98, 98.5, 96.0, 96.2),
    ]
    setups, trace, _, _ = _lifecycle(bars)
    assert FMState.COMPLETED.value in trace
    assert trace[-1] == FMState.COMPLETED.value
    assert setups[0].is_active is False


# --------------------------------------------------------------------------
# One transition per bar
# --------------------------------------------------------------------------


def test_at_most_one_state_change_per_bar() -> None:
    """The lifecycle is auditable bar by bar, so it may never skip ahead.

    Without this rule a single bar could carry a projection from `PROJECTED` to
    `CONFIRMED`, and the trace would no longer record what actually happened on the
    bars in between.
    """
    bars = _filler() + LEG + [
        mk(96, 97, 95.6, 96.5),
        mk(98, 100, 97.6, 99.5),
        mk(101, 104, 100.6, 103.5),
        mk(103, 105, 102.6, 104.8),
        mk(104.5, 105.4, 103.8, 104.0),
        mk(104.2, 105.2, 102.6, 102.8),
        mk(102, 102.5, 100.0, 100.2),
    ]
    _, trace, _, _ = _lifecycle(bars)

    rank = {s.value: i for i, s in enumerate(ORDER)}
    rank[FMState.INVALIDATED.value] = -1
    for previous, current in zip(trace, trace[1:]):
        if previous == current:
            continue
        step = rank[current] - rank[previous]
        assert step in (1, -1, -4), f"{previous} -> {current} skipped states"




# --------------------------------------------------------------------------
# The signal bar
# --------------------------------------------------------------------------


def test_a_signal_bar_needs_body_direction_close_and_a_small_adverse_wick() -> None:
    """Each of the four requirements, isolated so each is independently necessary.

    A bearish signal bar: a range where the body is large, the close sits at the
    bottom, and the wick left above the close (the adverse side) is small.
    """
    base = _filler() + LEG
    cfg = AnalyzerConfig()

    def bearish(o, h, low, c) -> list[dict[str, float]]:
        return base + [mk(o, h, low, c)]

    # a clean bearish signal bar: body 4.2 of 5.2, close at the low
    assert is_signal_bar(bearish(105, 105.2, 100.0, 100.2), len(base), -1, cfg)

    # wrong direction: this bar closes *up*, so it is not a fade signal for a
    # projection that runs up
    assert not is_signal_bar(bearish(100, 105.2, 99.8, 105.0), len(base), -1, cfg)

    # body too small relative to the range: a 0.5 body inside a 5.0 range
    assert not is_signal_bar(bearish(101.5, 105.0, 100.0, 101.0), len(base), -1, cfg)

    # adverse wick too large: a small body but the close is far from the low, so
    # the bar was sold into all the way down and recovered
    assert not is_signal_bar(bearish(101.0, 105.0, 96.0, 100.2), len(base), -1, cfg)

    # a bar with no range at all cannot be a signal
    assert not is_signal_bar(bearish(100, 100, 100, 100), len(base), -1, cfg)


def test_engulfing_is_optional_and_stricter_when_required() -> None:
    base = _filler() + LEG
    relaxed = AnalyzerConfig(fm_require_engulf=False)
    strict = AnalyzerConfig(fm_require_engulf=True)

    def series_with_prior(prior, candidate) -> list[dict[str, float]]:
        return base + [mk(*prior), mk(*candidate)]

    # A small prior bull bar, open 101 / close 102.
    prior = (101, 102, 100.8, 102.0)
    # A candidate that closes below the prior *open* but not below its close, so
    # it is directionally right yet does not engulf.
    series = series_with_prior(prior, (102, 102.2, 100.0, 100.2))
    assert is_signal_bar(series, len(series) - 1, -1, relaxed)
    assert not is_signal_bar(series, len(series) - 1, -1, strict)

    # A candidate that does engulf the prior body, with a body at least as large
    # (the second half of the test), passes under both settings.
    engulfing = series_with_prior(prior, (102.5, 102.7, 99.0, 99.1))
    assert is_signal_bar(engulfing, len(engulfing) - 1, -1, relaxed)
    assert is_signal_bar(engulfing, len(engulfing) - 1, -1, strict)

    # An engulfing bar whose body is *smaller* than the prior bar's is rejected
    # under the strict setting only.
    small = series_with_prior(prior, (102.5, 102.6, 101.4, 101.5))
    assert is_signal_bar(small, len(small) - 1, -1, relaxed)
    assert not is_signal_bar(small, len(small) - 1, -1, strict)


def test_follow_through_is_the_bar_after_the_signal() -> None:
    base = _filler() + LEG
    signal = mk(104, 105.2, 102.6, 102.8)   # a bearish signal bar
    assert has_follow_through(base + [signal, mk(102, 102.5, 100.0, 100.2)],
                              len(base), -1)
    # the next bar closes back above the signal's high: no follow-through
    assert not has_follow_through(
        base + [signal, mk(102, 106.0, 101.5, 105.5)], len(base), -1
    )
    # no bar after the signal at all
    assert not has_follow_through(base + [signal], len(base), -1)


def test_require_follow_through_defers_confirmation_by_one_bar() -> None:
    """With follow-through required, confirmation cannot land on the signal bar.

    A fade confirmed by a bar that has not yet had the chance to fail is not
    confirmed, so `fm_require_ft` moves the transition one closed bar later.
    """
    tail = [
        mk(96, 97, 95.6, 96.5),
        mk(98, 100, 97.6, 99.5),
        mk(101, 104, 100.6, 103.5),
        mk(103, 105, 102.6, 104.8),
        mk(104.5, 105.4, 103.8, 104.0),
        mk(104.2, 105.2, 102.6, 102.8),  # the signal bar
        mk(102, 102.5, 100.0, 100.2),    # follow-through
    ]
    without = _lifecycle(_filler() + LEG + tail)[1]
    with_ft = _lifecycle(
        _filler() + LEG + tail, AnalyzerConfig(fm_require_ft=True)
    )[1]

    assert FMState.CONFIRMED.value in without
    if FMState.CONFIRMED.value in with_ft:
        # confirmation, if it happens at all, happens strictly later
        assert with_ft.index(FMState.CONFIRMED.value) > without.index(
            FMState.CONFIRMED.value
        )


def test_developing_requires_exhaustion_and_records_its_breadth() -> None:
    bars = _filler() + LEG + [
        mk(96, 97, 95.6, 96.5),
        mk(98, 100, 97.6, 99.5),
        mk(101, 104, 100.6, 103.5),
        mk(103, 105, 102.6, 104.8),
        mk(104.5, 105.4, 103.8, 104.0),
    ]
    _, trace, _, _ = _lifecycle(bars)
    assert FMState.DEVELOPING.value in trace

    # the breadth is read at the transition, so read it off the setup as it develops
    atr = _atr(bars)
    closed = len(bars) - 1
    setups = create_setups(bars, last_closed=closed, atr=atr, swings=SWINGS, config=CFG)
    seen_developing = False
    for step in range(closed + 1):
        setups = update_setups(setups, bars, step, closed, atr, config=CFG)
        if setups and setups[0].state == FMState.DEVELOPING.value:
            seen_developing = True
            assert setups[0].exhaustion_breadth >= 1
            assert setups[0].touched is True
            assert "exhaustion" in setups[0].reason
            break
    assert seen_developing


# --------------------------------------------------------------------------
# Closed-bar contract and degenerate input
# --------------------------------------------------------------------------


def test_the_lifecycle_does_not_read_bars_after_last_closed() -> None:
    """The architecture's invariant, applied to the fade lifecycle."""
    bars = _filler() + LEG + [
        mk(96, 97, 95.6, 96.5),
        mk(98, 100, 97.6, 99.5),
        mk(101, 104, 100.6, 103.5),
    ]
    atr = _atr(bars)
    closed = len(bars) - 1

    def run(series: list[dict[str, float]]) -> list[str]:
        setups = create_setups(series, last_closed=closed, atr=atr, config=CFG)
        for step in range(closed + 1):
            setups = update_setups(setups, series, step, closed, atr, config=CFG)
        return [s.state for s in setups]

    base = run(bars)
    # append bars that would change the answer if they were read
    future = run(bars + [mk(103, 105, 102.6, 104.8), mk(100, 100.5, 98, 98.2)])
    assert base == future


def test_update_clamps_an_index_beyond_the_analysed_window() -> None:
    """A caller cannot advance the lifecycle using bars it said were unavailable."""
    bars = _filler() + LEG + [mk(96, 97, 95.6, 96.5)]
    atr = _atr(bars)
    closed = len(bars) - 2  # one bar short of the end
    setups = create_setups(bars, last_closed=closed, atr=atr, swings=SWINGS, config=CFG)
    at_limit = update_setups(setups, bars, closed, closed, atr, config=CFG)
    past_end = update_setups(setups, bars, closed + 50, closed, atr, config=CFG)
    assert [s.state for s in at_limit] == [s.state for s in past_end]


def test_degenerate_input_returns_nothing_rather_than_raising() -> None:
    assert create_setups([], atr=1.0) == []
    assert create_setups(_filler(), atr=0.0) == []
    assert create_setups(_filler() + LEG, atr=1.0, last_closed=-1) == []
    assert update_setups([], _filler(), 5, 19, 1.0) == []
    assert track_fading_measured_moves([], atr=1.0) == []
    # an update with no volatility is a no-op, not a crash
    bars = _filler() + LEG + [mk(96, 97, 95.6, 96.5)]
    setups = create_setups(bars, last_closed=len(bars) - 1, atr=1.0, swings=SWINGS)
    assert update_setups(setups, bars, 25, 25, 0.0) == setups


def test_inverse_projections_are_gated_by_fm_enable_inverse() -> None:
    """The weakest input is separable, per the measured-move documentation."""
    on = AnalyzerConfig(fm_enable_inverse=True)
    off = AnalyzerConfig(fm_enable_inverse=False)
    bars = _filler() + LEG + [mk(96, 97, 95.6, 96.5)]
    atr = _atr(bars)
    # whichever families the fixture produces, the flag may only remove INVERSE
    enabled = create_setups(bars, last_closed=len(bars) - 1, atr=atr,
                            swings=SWINGS, config=on)
    disabled = create_setups(bars, last_closed=len(bars) - 1, atr=atr,
                             swings=SWINGS, config=off)
    assert len(disabled) <= len(enabled)
    assert all(s.family != "INVERSE" for s in disabled)


# --------------------------------------------------------------------------
# Serialization and immutability
# --------------------------------------------------------------------------


def test_a_setup_serializes_to_json_with_its_projection_evidence() -> None:
    """Phase 22 hands these to an LLM, so nothing may leak as a non-JSON value."""
    bars = _filler() + LEG + [
        mk(96, 97, 95.6, 96.5),
        mk(98, 100, 97.6, 99.5),
        mk(101, 104, 100.6, 103.5),
        mk(103, 105, 102.6, 104.8),
    ]
    setups = track_fading_measured_moves(
        bars, last_closed=len(bars) - 1, atr=_atr(bars), swings=SWINGS, config=CFG
    )
    assert setups
    payload = json.loads(json.dumps([s.to_dict() for s in setups]))
    for entry in payload:
        assert entry["state"] in [s.value for s in FMState]
        assert entry["direction"] == -entry["fade_direction"]
        assert isinstance(entry["exhaustion_breadth"], int)
        assert entry["reason"], "every state records why it was reached"
        # the projection's own evidence travels with the state
        assert entry["projection"] is not None
        assert entry["projection"]["evidence"]


def test_setups_are_immutable_so_a_snapshot_cannot_be_corrupted() -> None:
    # long enough for the leg's swings to be confirmed (see the note in
    # test_a_projection_starts_projected_with_its_fade_direction_opposed)
    bars = _filler() + LEG + [
        mk(96, 97, 95.6, 96.5),
        mk(98, 100, 97.6, 99.5),
        mk(101, 104, 100.6, 103.5),
    ]
    setups = create_setups(
        bars, last_closed=len(bars) - 1, atr=_atr(bars), swings=SWINGS, config=CFG
    )
    assert setups
    original = setups[0].state
    with pytest.raises(dataclasses.FrozenInstanceError):
        setups[0].state = FMState.CONFIRMED.value  # type: ignore[misc]
    assert setups[0].state == original


def test_touch_and_active_are_distinct_questions() -> None:
    """`POTENTIAL` approaches; only `DEVELOPING` onward has actually arrived."""
    setup = FadingSetup(
        id=1, family="REGULAR", direction=1, target_price=105.0,
        mm_range=10.0, created_bar=20, fade_direction=-1,
    )
    assert setup.state == FMState.PROJECTED.value
    assert setup.is_active is True
    assert setup.touched is False

    potential = setup.to_state(state=FMState.POTENTIAL.value)
    assert potential.is_active is True
    assert potential.touched is False, "approaching is not touching"

    developing = potential.to_state(state=FMState.DEVELOPING.value)
    assert developing.touched is True

    for terminal in (FMState.COMPLETED, FMState.INVALIDATED):
        done = developing.to_state(state=terminal.value)
        assert done.is_active is False
