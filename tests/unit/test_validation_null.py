"""Tests for the stated null (`VALIDATION.md` §9.4).

`events.py` is careful to refuse to call its counts an edge, and it gives the
reason: a share of target-first events says nothing without the count the same
sample would produce if the engine's claim were removed. `null.py` supplies that
count. These tests pin three things in order of how much damage getting them wrong
would do:

1. **The null destroys the direction and nothing else.** If it also moved the fill
   bar, the risk, or the reward, it would be comparing two different trades and the
   resulting number would be meaningless while still looking like a number. So the
   mirroring is tested to be *exact* rather than approximately right.
2. **It refuses to conclude.** `verdict` is a constant with no inputs, and the
   comparison statistic is a count of draws rather than a p-value. A test asserts
   `verdict` is `UNDECIDED` for inputs chosen to make an engine look as good as
   possible, because the whole value of the module is that this answer cannot be
   bought with a favourable sample.
3. **It refuses to run on a sample whose shape would break the argument.** The
   independence the null depends on is a property of `ConflictPolicy.SKIP`, so
   `PARALLEL` and `CLOSE_AND_REVERSE` are rejected rather than approximated.

The counterfactual is tested against **hand-built windows**, not against whatever
`replay` produces. `test_phase18_backtesting.py` explains why: the first version of
the path classifier read the favourable extreme for both levels, so a long's stop
was never checked, and a fixture-level test hid it. The same trap applies here --
a null scored only through `replay` would pass against a counterfactual that had
inverted the wrong level.
"""

from __future__ import annotations

import pytest

from albrooks.backtest.events import (
    AmbiguityPolicy,
    BacktestResult,
    ConflictPolicy,
    Outcome,
    TradeEvent,
    replay,
)
from albrooks.backtest.null import (
    BLOCKED_ON,
    VERDICT,
    NullDesign,
    NullResult,
    NullUnavailable,
    counterfactual,
    mirror_levels,
    null_distribution,
)
from albrooks.core.bars import BarSeries
from albrooks.engine.configuration import AnalyzerConfig

CFG = AnalyzerConfig(range_lookback=20)


def window(*ohlc: tuple[float, float, float, float]) -> BarSeries:
    return BarSeries(
        [
            {"time": float(i), "o": o, "h": h, "l": low, "c": c}
            for i, (o, h, low, c) in enumerate(ohlc)
        ]
    )


def event(**changes: object) -> TradeEvent:
    base: dict[str, object] = {
        "signal_bar": 0,
        "subject": "CANDIDATE#0",
        "direction": 1,
        "fill_bar": 0,
        "entry": 100.0,
        "stop": 95.0,
        "target": 110.0,
        "plan_entry": 100.0,
        "outcome": Outcome.TARGET_FIRST,
        "atr": 2.0,
    }
    base.update(changes)
    return TradeEvent(**base)  # type: ignore[arg-type]


def result_with(*events: TradeEvent, **changes: object) -> BacktestResult:
    base: dict[str, object] = {"events": events, "horizon": 4}
    base.update(changes)
    return BacktestResult(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# The mirroring is exact
# --------------------------------------------------------------------------


def test_mirroring_preserves_risk_and_reward_exactly() -> None:
    """The counterfactual has to be the same trade, pointing the other way.

    An approximate mirror -- rebuilt from ATR, say -- would be a *different* trade,
    and the comparison would then be between two geometries rather than between two
    directions. The number would still print.
    """
    stop, target = mirror_levels(100.0, 95.0, 110.0)

    assert stop == pytest.approx(105.0)
    assert target == pytest.approx(90.0)
    # Distances preserved to the last bit, not to a tolerance that hides drift.
    assert abs(100.0 - stop) == abs(100.0 - 95.0)
    assert abs(target - 100.0) == abs(110.0 - 100.0)


def test_mirroring_a_short_reflects_to_the_same_pair() -> None:
    """The transform does not assume the event was a long."""
    stop, target = mirror_levels(100.0, 105.0, 90.0)

    assert stop == pytest.approx(95.0)
    assert target == pytest.approx(110.0)
    assert abs(100.0 - stop) == abs(100.0 - 105.0)


def test_a_mirrored_fill_stays_untradable() -> None:
    """`INVALID_ENTRY` has to survive the transformation, not be re-derived.

    A fill already through the stop is through the mirrored stop too, because the
    distance is unchanged. Re-classifying it from scratch would mean trusting a
    second copy of the tradability rule to agree with `events.py`, and a
    disagreement would show up as a changed sample size rather than as an error.
    """
    dead = event(direction=1, entry=94.0, stop=95.0, target=110.0, outcome=Outcome.INVALID_ENTRY)

    assert counterfactual(dead, flip=True, window=window((94.0, 94.5, 93.0, 93.5))) is (
        Outcome.INVALID_ENTRY
    )


# --------------------------------------------------------------------------
# The counterfactual inverts the right level
# --------------------------------------------------------------------------


def test_a_flipped_long_that_rose_is_now_a_short_that_did_not() -> None:
    """Price reached the long's target. The mirror must not also claim a win.

    This is the direction of the whole module. If the flip returned `TARGET_FIRST`
    here, the null would be reporting the engine's own outcome back to it and the
    comparison would be vacuous.
    """
    rising = window((100.0, 101.0, 99.5, 100.8), (100.8, 105.0, 100.0, 104.0))

    assert counterfactual(event(), flip=False, window=rising) is Outcome.TARGET_FIRST
    assert counterfactual(event(), flip=True, window=rising) is Outcome.STOP_FIRST


def test_a_flipped_long_that_failed_is_now_a_short_that_won() -> None:
    """The mirror is symmetric, not merely biased against the engine.

    A null that only ever turned wins into losses would push the null share down
    and manufacture an apparent edge out of the transformation itself. So the low
    that takes out the long's stop at 95 is also below the mirrored short's target
    at 90, and the same bar wins the other trade.
    """
    falling = window((100.0, 100.5, 96.0, 96.5), (96.5, 97.0, 89.0, 90.0))

    assert counterfactual(event(outcome=Outcome.STOP_FIRST), flip=False, window=falling) is (
        Outcome.STOP_FIRST
    )
    assert counterfactual(event(outcome=Outcome.STOP_FIRST), flip=True, window=falling) is (
        Outcome.TARGET_FIRST
    )


def test_an_unflipped_event_is_left_exactly_as_it_was() -> None:
    """Half the events are not flipped, so the draw is a real coin and not a step.

    This also pins that the null re-uses the engine's own classification when the
    direction is untouched, rather than recomputing it and hoping the two agree.
    """
    rising = window((100.0, 111.0, 99.0, 110.0))

    assert counterfactual(event(), flip=False, window=rising) is Outcome.TARGET_FIRST


def test_the_mirrored_short_stop_is_reached_by_a_high() -> None:
    """The inverted classification uses the correct extreme for the new direction.

    A short's stop is hit by a high. Reading the low instead -- the bug
    `test_phase18_backtesting.py` was written after -- would report a stop the
    market never reached, in the counterfactual as well as the observation.
    """
    # Highs reach the mirrored stop at 105; lows never approach it, and the high
    # never reaches the long's own target at 110 either.
    highs_only = window((100.0, 106.0, 99.5, 105.5))

    assert counterfactual(event(outcome=Outcome.NEITHER), flip=True, window=highs_only) is (
        Outcome.STOP_FIRST
    )
    # The same window leaves the long's stop at 95 untouched and its target
    # unreached, so the unflipped event times out. If the mirror had read the low
    # for the stop -- the bug this project's classifier was written after -- the
    # flipped reading here would be NEITHER instead.
    assert counterfactual(event(outcome=Outcome.NEITHER), flip=False, window=highs_only) is (
        Outcome.NEITHER
    )


# --------------------------------------------------------------------------
# The distribution
# --------------------------------------------------------------------------


def _bars(n: int = 120) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    price = 100.0
    for i in range(n):
        if i < 40:
            o, h, low, c = price, price + 1.0, price - 1.0, price + 0.8
        elif i < 80:
            o, h, low, c = price, price + 0.5, price - 1.5, price - 1.0
        else:
            o, h, low, c = price, price + 1.2, price - 0.6, price + 1.0
        out.append({"time": float(i * 60), "o": o, "h": h, "l": low, "c": c})
        price = c
    return out


def test_the_observed_counts_are_the_runs_own_and_not_a_recomputation() -> None:
    """The null must be compared against what the engine actually reported.

    Recomputing the observed tally inside this module would let a bug here change
    both sides of the comparison at once, which is the one error a matched
    comparison cannot survive.
    """
    bars = _bars()
    run = replay(bars, config=CFG, horizon=6)
    if not run.events:
        pytest.skip("the fixture produced no events on this engine configuration")

    null = null_distribution(bars, run, NullDesign(randomizations=5))

    assert null.observed_counts == run.counts(AmbiguityPolicy.STOP_FIRST)
    assert null.events == len(run.events)


def test_the_same_seed_gives_the_same_distribution() -> None:
    """A null that cannot be reproduced is an anecdote, not a result."""
    bars = _bars()
    run = replay(bars, config=CFG, horizon=6)
    if not run.events:
        pytest.skip("the fixture produced no events on this engine configuration")

    first = null_distribution(bars, run, NullDesign(randomizations=25, seed=7))
    second = null_distribution(bars, run, NullDesign(randomizations=25, seed=7))

    assert first.null_shares == second.null_shares
    assert first.to_dict() == second.to_dict()


def test_the_seed_and_the_policies_are_carried_into_the_output() -> None:
    """A number in a document can only be re-derived if the choices are recorded."""
    design = NullDesign(randomizations=3, seed=99, ambiguity_policy=AmbiguityPolicy.EXCLUDE)
    payload = NullResult(
        design=design,
        events=1,
        observed_counts={},
        observed_share=None,
        null_shares=(),
        null_mean=None,
        null_std=None,
        null_draws_at_or_above_observed=None,
    ).to_dict()

    assert payload["design"] == {
        "randomizations": 3,
        "seed": 99,
        "ambiguity_policy": "EXCLUDE",
    }


def test_a_null_that_matches_everything_everywhere_is_still_undecided() -> None:
    """The verdict cannot be bought with a favourable sample.

    A module that returned `BEATS_NULL` for a perfect engine would be a module
    whose output is a function of the sample rather than of the evidence. This is
    the test that makes the constant a constant.
    """
    perfect = NullResult(
        design=NullDesign(),
        events=1000,
        observed_counts={Outcome.TARGET_FIRST.to_dict(): 1000},
        observed_share=1.0,
        null_shares=(1.0, 0.99, 0.98),
        null_mean=0.99,
        null_std=0.01,
        null_draws_at_or_above_observed=0,
    )

    assert perfect.verdict == VERDICT == "UNDECIDED"
    payload = perfect.to_dict()
    assert payload["verdict"] == "UNDECIDED"
    assert payload["is_probability"] is False
    # The tail count is present but named as a count, and the caveats say why it is
    # not a p-value.
    assert payload["null_draws_at_or_above_observed"] == 0
    assert any("NOT a p-value" in c for c in payload["caveats"])
    assert any(b in " ".join(payload["caveats"]) for b in ("Real data", "provenance"))


def test_an_empty_sample_is_refused_rather_than_scored_as_zero() -> None:
    """No events means no share, and 0.0 would be a fabricated number."""
    with pytest.raises(NullUnavailable, match="no events"):
        null_distribution(_bars(), result_with(), NullDesign(randomizations=3))


# --------------------------------------------------------------------------
# The preconditions
# --------------------------------------------------------------------------


@pytest.mark.parametrize("policy", [ConflictPolicy.PARALLEL, ConflictPolicy.CLOSE_AND_REVERSE])
def test_a_null_is_refused_when_the_events_are_not_independent(policy: ConflictPolicy) -> None:
    """The independence the argument rests on comes from `SKIP`, not from hope.

    `PARALLEL` overlaps the events, so two independently flipped positions can
    become the same position counted twice. `CLOSE_AND_REVERSE` truncates a path at
    a bar the event does not record, so the counterfactual's window would not be
    the observed one. Both would still produce a number, which is the problem.
    """
    run = result_with(event(), conflict_policy=policy)

    with pytest.raises(NullUnavailable, match="ConflictPolicy.SKIP"):
        null_distribution(_bars(), run, NullDesign(randomizations=3))


def test_the_observed_and_null_tallies_must_use_the_same_ambiguity_rule() -> None:
    """Comparing a tally read one way against a tally read another is not a comparison."""
    run = result_with(
        event(outcome=Outcome.AMBIGUOUS), ambiguity_policy=AmbiguityPolicy.STOP_FIRST
    )

    with pytest.raises(NullUnavailable, match="ambiguity"):
        null_distribution(
            _bars(),
            run,
            NullDesign(randomizations=3, ambiguity_policy=AmbiguityPolicy.TARGET_FIRST),
        )


def test_the_design_refuses_a_run_of_zero_draws() -> None:
    """Zero randomizations would report an empty distribution as a result."""
    with pytest.raises(ValueError, match="at least 1"):
        NullDesign(randomizations=0)


def test_the_blocked_on_list_names_the_missing_ingredients() -> None:
    """The reasons the verdict cannot move are carried, not merely implied."""
    joined = " ".join(BLOCKED_ON)

    assert "Real data" in joined
    assert "provenance" in joined
    assert "out-of-sample" in joined
    assert "p-value" in joined


# --------------------------------------------------------------------------
# What the null is not
# --------------------------------------------------------------------------


def test_the_null_re_reads_the_bars_instead_of_echoing_the_recorded_outcome() -> None:
    """A flipped draw is scored on the price, not on what the event claims.

    The event below *claims* `TARGET_FIRST` while the bars it points at actually
    took out the mirrored short. If the null echoed the recorded outcome, every
    flipped draw would also be a win, the null mean would be `1.0`, and the
    comparison would be the engine's own arithmetic scored against itself -- while
    still printing a number that looked like a distribution.
    """
    rising = window((100.0, 101.0, 99.5, 100.8), (100.8, 106.0, 100.0, 105.0))
    # The claim on the event is deliberately wrong about these bars.
    run = result_with(event(outcome=Outcome.TARGET_FIRST), horizon=2)

    null = null_distribution(rising, run, NullDesign(randomizations=400, seed=3))

    assert null.observed_share == 1.0
    # Half the draws flip and each of those is a stop-out, so the null mean lands
    # near one half rather than at the observed one.
    assert null.null_mean is not None
    assert 0.35 < null.null_mean < 0.65
    # A single-event null is a coin by construction, so roughly half the draws
    # match the engine's share. That is the honest situation and the reason the
    # verdict is a constant: with one observation, "matching the null" and
    # "doubling it" are the same event.
    assert null.null_draws_at_or_above_observed is not None
    assert 120 < null.null_draws_at_or_above_observed < 280
    assert null.verdict == VERDICT
