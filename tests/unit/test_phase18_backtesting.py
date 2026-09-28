"""Tests for the backtesting interface (Phase 18).

This is the phase where numbers about outcomes first appear, and the risk is
highest exactly here: a backtest that reports a green curve is the most
convincing and least supported artefact a trading library can ship. These tests
therefore pin **what the module refuses to do** as much as what it computes:

1. **The intra-bar order is unknowable, and is not guessed.** One bar containing
   both the target and the stop is `AMBIGUOUS`, recorded on the event and never
   overwritten. The default resolution is the pessimistic one, and it is a
   *separate*, explicit step applied at reporting time.
2. **The fill is an assumption, named as one.** The default is the next bar's open
   — the first price that existed once the decision could be acted on — and a fill
   that arrives already dead is `INVALID_ENTRY` and is counted, not dropped.
3. **The decision and the outcome are separate statements.** An event's plan must
   equal the plan from `analyze(bars, last_closed=k)`, and an outcome is a function
   of the *horizon*, not of the future.
4. **No P&L.** There is no equity curve, no expectancy, no profit factor and no
   win rate, and a test asserts their absence.

Path classification is tested against hand-built windows rather than against
whatever the loop happens to produce on a fixture. That matters: the first version
of `_first_touch` read the *favourable* extreme for both levels, so a long's stop
was never actually checked and every stop-hit reading in this module was fabricated.
A fixture-level test would have hidden it; a window-level test cannot.
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from albrooks.backtest.events import (
    CAVEATS,
    SKIP_INVALID_PLAN,
    SKIP_NO_FORWARD_BARS,
    SKIP_NO_PLAN,
    SKIP_NOT_ACTIONABLE,
    SKIP_OPEN,
    AmbiguityPolicy,
    BacktestResult,
    ConflictPolicy,
    FillPolicy,
    Outcome,
    TradeEvent,
    replay,
)
from albrooks.core.bars import BarSeries
from albrooks.engine.analyzer import Analyzer
from albrooks.engine.configuration import AnalyzerConfig

CFG = AnalyzerConfig(range_lookback=20)


def window(*ohlc: tuple[float, float, float, float]) -> BarSeries:
    """A forward window from `(open, high, low, close)` tuples."""
    return BarSeries(
        [
            {"time": float(i), "o": o, "h": h, "l": low, "c": c}
            for i, (o, h, low, c) in enumerate(ohlc)
        ]
    )


def event(**changes: Any) -> TradeEvent:
    base: dict[str, Any] = {
        "signal_bar": 5,
        "subject": "CANDIDATE#0",
        "direction": 1,
        "fill_bar": 6,
        "entry": 100.0,
        "stop": 95.0,
        "target": 110.0,
        "plan_entry": 100.0,
        "outcome": Outcome.TARGET_FIRST,
        "atr": 2.0,
    }
    base.update(changes)
    return TradeEvent(**base)


def _bars(n: int = 120) -> list[dict[str, float]]:
    """A deterministic rally / pullback / rally series, oldest first.

    The segment boundaries are **absolute**, not fractions of `n`, so that a 120-bar
    slice is a true prefix of a 200-bar one. A fraction-based fixture would make
    "the same bars" a different series depending on how much data was supplied,
    which would quietly invalidate every append-and-compare test in this file.
    """
    out: list[dict[str, float]] = []
    price = 100.0
    for i in range(n):
        if i < 40:
            o, h, low, c = price, price + 1.0, price - 1.0, price + 0.8
        elif i < 60:
            o, h, low, c = price, price + 1.0, price - 1.0, price - 0.4
        else:
            o, h, low, c = price, price + 1.2, price - 0.6, price + 1.0
        price = c
        out.append({"o": o, "h": h, "l": low, "c": c})
    return out


# --------------------------------------------------------------------------
# Level touching: the extreme depends on which side the level is on
# --------------------------------------------------------------------------


def test_a_long_target_is_reached_by_a_high_and_its_stop_by_a_low() -> None:
    """The bug this test exists for. The first `_first_touch` checked the
    *favourable* extreme for both levels, so a long's stop was never tested and
    every "stop hit" reading in this module was fabricated."""
    from albrooks.backtest.events import _classify

    # Bar 0 dips to 96 without reaching the 95 stop; bar 1 reaches 111.
    path = window((100, 101, 96, 100), (100, 111, 100, 110))
    outcome, to_target, to_stop, _ = _classify(1, list(path), 100.0, 95.0, 110.0)

    assert (outcome, to_target, to_stop) == (Outcome.TARGET_FIRST, 1, -1)


def test_a_short_target_is_reached_by_a_low_and_its_stop_by_a_high() -> None:
    from albrooks.backtest.events import _classify

    path = window((100, 104, 100, 100), (100, 100, 89, 90))
    outcome, to_target, to_stop, _ = _classify(-1, list(path), 100.0, 105.0, 90.0)

    assert (outcome, to_target, to_stop) == (Outcome.TARGET_FIRST, 1, -1)


def test_a_long_stop_is_hit_by_a_low_even_when_a_high_passes_it_first() -> None:
    """The bar's high is above the stop on the very first bar, which is exactly the
    confusion the split into two functions removes."""
    from albrooks.backtest.events import _classify

    path = window((100, 106, 94, 100))
    outcome, to_target, to_stop, _ = _classify(1, list(path), 100.0, 95.0, 110.0)

    assert (outcome, to_target, to_stop) == (Outcome.STOP_FIRST, -1, 0)


def test_a_short_stop_is_hit_by_a_high() -> None:
    from albrooks.backtest.events import _classify

    path = window((100, 106, 99, 100))
    outcome, _, to_stop, _ = _classify(-1, list(path), 100.0, 105.0, 90.0)

    assert outcome is Outcome.STOP_FIRST
    assert to_stop == 0


def test_a_level_that_is_exactly_touched_counts_as_reached() -> None:
    """A level is a price, and a price that was traded is a price that was reached."""
    from albrooks.backtest.events import _classify

    path = window((100, 110, 100, 100))
    outcome, to_target, _, _ = _classify(1, list(path), 100.0, 95.0, 110.0)

    assert outcome is Outcome.TARGET_FIRST
    assert to_target == 0


def test_neither_level_reached_is_a_timeout_not_a_loss() -> None:
    from albrooks.backtest.events import _classify

    path = window((100, 101, 99, 100), (100, 102, 99, 101))
    outcome, to_target, to_stop, detail = _classify(1, list(path), 100.0, 95.0, 110.0)

    assert (outcome, to_target, to_stop, detail) == (Outcome.NEITHER, -1, -1, "")


# --------------------------------------------------------------------------
# Ambiguity
# --------------------------------------------------------------------------


def test_one_bar_containing_both_levels_is_ambiguous_not_the_favourable_reading() -> None:
    """The single most important rule in this module. A bar whose high is past the
    target and whose low is through the stop cannot be ordered from OHLC, and
    assuming the better order is not measuring a market."""
    from albrooks.backtest.events import _classify

    path = window((100, 111, 94, 100))
    outcome, to_target, to_stop, detail = _classify(1, list(path), 100.0, 95.0, 110.0)

    assert outcome is Outcome.AMBIGUOUS
    assert (to_target, to_stop) == (0, 0)
    assert "both levels" in detail


def test_an_ambiguous_event_is_left_ambiguous_on_the_event_itself() -> None:
    """Resolution is a reporting step, so the raw fact survives in the record."""
    ambiguous = event(outcome=Outcome.AMBIGUOUS)

    assert ambiguous.resolved(AmbiguityPolicy.STOP_FIRST) is Outcome.STOP_FIRST
    assert ambiguous.resolved(AmbiguityPolicy.TARGET_FIRST) is Outcome.TARGET_FIRST
    assert ambiguous.resolved(AmbiguityPolicy.EXCLUDE) is Outcome.AMBIGUOUS
    assert ambiguous.outcome is Outcome.AMBIGUOUS, "the event must not be rewritten"


def test_only_an_ambiguous_outcome_is_affected_by_the_policy() -> None:
    for outcome in (Outcome.TARGET_FIRST, Outcome.STOP_FIRST, Outcome.NEITHER):
        same = event(outcome=outcome)
        for policy in AmbiguityPolicy:
            assert same.resolved(policy) is outcome


def test_the_default_ambiguity_policy_is_the_pessimistic_one() -> None:
    assert AmbiguityPolicy.STOP_FIRST is not AmbiguityPolicy.TARGET_FIRST
    result = BacktestResult(
        events=(event(outcome=Outcome.AMBIGUOUS),),
        ambiguity_policy=AmbiguityPolicy.STOP_FIRST,
    )

    assert result.counts()["STOP_FIRST"] == 1
    assert result.counts(AmbiguityPolicy.TARGET_FIRST)["TARGET_FIRST"] == 1
    assert result.counts(AmbiguityPolicy.EXCLUDE)["AMBIGUOUS"] == 0


# --------------------------------------------------------------------------
# Excursions
# --------------------------------------------------------------------------


def test_excursions_are_measured_from_the_fill_and_never_negative() -> None:
    from albrooks.backtest.events import _excursions

    path = list(window((100, 106, 99, 105), (105, 112, 104, 110)))

    mfe, mae = _excursions(1, 100.0, path)
    assert mfe == pytest.approx(12.0)  # high 112
    assert mae == pytest.approx(1.0)  # low 99

    # A path that only ever moved against the trade has no favourable excursion.
    mfe, mae = _excursions(1, 120.0, path)
    assert mfe == 0.0
    assert mae == pytest.approx(21.0)  # low 99


def test_a_short_excursion_is_mirrored() -> None:
    from albrooks.backtest.events import _excursions

    path = list(window((100, 101, 88, 90)))

    mfe, mae = _excursions(-1, 100.0, path)
    assert mfe == pytest.approx(12.0)  # low 88
    assert mae == pytest.approx(1.0)  # high 101


def test_an_event_excursion_stops_at_the_exit_not_at_the_end_of_the_window() -> None:
    """Measuring to the end of the window credits a stopped-out trade with
    everything the market did afterwards, which inflates MFE by an amount that has
    nothing to do with the trade."""
    bars = _bars()
    series = BarSeries(bars)
    result = replay(bars, config=CFG, horizon=6)

    assert len(result) > 0
    for one in result:
        if one.outcome is Outcome.INVALID_ENTRY:
            continue
        path = [series[one.fill_bar + i] for i in range(one.bars_held + 1)]
        assert path, "a filled event always has at least the fill bar"
        high = max(b.high for b in path)
        low = min(b.low for b in path)
        if one.direction > 0:
            assert one.mfe == pytest.approx(max(0.0, high - one.entry))
            assert one.mae == pytest.approx(max(0.0, one.entry - low))
        else:
            assert one.mfe == pytest.approx(max(0.0, one.entry - low))
            assert one.mae == pytest.approx(max(0.0, high - one.entry))
        # A path that ran past the exit would be strictly longer than the horizon
        # only if the level was never reached, which is what NEITHER means.
        assert one.bars_held <= 5 or one.outcome is Outcome.NEITHER


def test_excursions_are_also_reported_in_atr() -> None:
    result = replay(_bars(), config=CFG, horizon=6)

    for one in result:
        if one.atr > 0.0 and one.outcome is not Outcome.INVALID_ENTRY:
            assert one.mfe_atr == pytest.approx(one.mfe / one.atr)
            assert one.mae_atr == pytest.approx(one.mae / one.atr)


# --------------------------------------------------------------------------
# Fill policy and invalid entries
# --------------------------------------------------------------------------


def test_the_default_fill_is_the_next_bar_open() -> None:
    """The earliest price that existed once a closed-bar decision could be acted
    on. Filling at the signal bar's close means filling at a price the engine had
    when it could not yet act."""
    assert FillPolicy.NEXT_OPEN is not FillPolicy.SIGNAL_CLOSE
    result = replay(_bars(), config=CFG, horizon=6)

    assert result.fill_policy is FillPolicy.NEXT_OPEN
    for one in result:
        assert one.fill_bar == one.signal_bar + 1
        assert one.entry == pytest.approx(BarSeries(_bars())[one.fill_bar].open)


def test_the_signal_close_policy_fills_where_the_plan_said() -> None:
    result = replay(_bars(), config=CFG, horizon=6, fill_policy=FillPolicy.SIGNAL_CLOSE)

    for one in result:
        assert one.fill_bar == one.signal_bar
        assert one.entry == pytest.approx(one.plan_entry)


def test_a_signal_on_the_last_bar_has_no_forward_bar_and_produces_no_event() -> None:
    series = BarSeries(_bars())
    result = replay(_bars(), config=CFG, conflict_policy=ConflictPolicy.PARALLEL)

    assert result.skipped.get(SKIP_NO_FORWARD_BARS, 0) >= 1
    assert all(one.signal_bar < len(series) for one in result)


@pytest.mark.parametrize(
    ("direction", "entry", "stop", "target", "reason"),
    [
        (1, 94.0, 95.0, 110.0, "FILL_ALREADY_THROUGH_STOP"),
        (1, 111.0, 95.0, 110.0, "FILL_ALREADY_PAST_TARGET"),
        (-1, 106.0, 105.0, 90.0, "FILL_ALREADY_THROUGH_STOP"),
        (-1, 89.0, 105.0, 90.0, "FILL_ALREADY_PAST_TARGET"),
    ],
)
def test_a_fill_that_is_already_dead_is_counted_rather_than_dropped(
    direction: int, entry: float, stop: float, target: float, reason: str
) -> None:
    """A fill that arrived through the stop never existed as a trade. Dropping it
    silently would edit the sample in its own favour."""
    from albrooks.backtest.events import _invalid_entry

    assert _invalid_entry(direction, entry, stop, target) == reason
    assert _invalid_entry(direction, 100.0, stop, target) == ""


def test_an_invalid_fill_is_an_event_with_its_own_outcome() -> None:
    result = BacktestResult(
        events=(
            event(
                outcome=Outcome.INVALID_ENTRY,
                detail="FILL_ALREADY_THROUGH_STOP",
                mfe=0.0,
                mae=0.0,
            ),
        )
    )

    assert result.counts()["INVALID_ENTRY"] == 1
    assert result.mean_mfe_atr() is None, "an invalid fill has no path to average"
    assert result.mean_mae_atr() is None


# --------------------------------------------------------------------------
# The decision / outcome boundary
# --------------------------------------------------------------------------


def test_an_events_plan_is_exactly_the_closed_bar_decision_at_that_index() -> None:
    """The load-bearing separation. The event's levels must be the plan from
    `analyze(bars, last_closed=k)` — if they were anything else, the outcome would
    be scored against a trade the engine never proposed."""
    bars = _bars()
    result = replay(bars, config=CFG, horizon=6)
    analyzer = Analyzer(CFG)
    series = BarSeries(bars)

    assert len(result) > 0, "fixture must produce at least one event"
    for one in result:
        decision = analyzer.analyze(series, last_closed=one.signal_bar).decision
        plan = decision["plan"]
        assert plan is not None
        assert decision["action"] in ("BUY", "SELL")
        assert one.subject == decision["subject"]
        assert one.direction == plan["direction"]
        assert one.plan_entry == pytest.approx(plan["entry"])
        assert one.stop == pytest.approx(plan["stop"])
        assert one.target == pytest.approx(plan["target"])


def test_appending_bars_cannot_change_an_event_within_its_horizon() -> None:
    """`RPC-15` applied to this module. The plan *and* the outcome are functions of
    the horizon, not of the data after it."""
    longer = _bars(240)
    short = longer[:120]
    at = 60

    before = replay(short, config=CFG, horizon=6)
    after = replay(longer, config=CFG, horizon=6)

    trimmed_before = [e.to_dict() for e in before if e.signal_bar < at]
    trimmed_after = [e.to_dict() for e in after if e.signal_bar < at]

    assert trimmed_before == trimmed_after


def test_without_a_horizon_the_outcome_legitimately_changes_and_that_is_not_a_leak() -> None:
    """The honest counter-statement.

    With `horizon=None` a path runs to the end of the series, so a `NEITHER` at bar
    `k` can become a `TARGET_FIRST` once more bars arrive. That is not a look-ahead
    bug; it is what "no horizon" *means*, and claiming otherwise would be the kind
    of overstatement this project refuses to make. So this test asserts the change
    happens, and says why it is allowed.
    """
    longer = _bars(240)
    short = longer[:120]

    before = replay(short, config=CFG, conflict_policy=ConflictPolicy.PARALLEL)
    after = replay(longer, config=CFG, conflict_policy=ConflictPolicy.PARALLEL)

    before_by_bar = {e.signal_bar: e.outcome for e in before}
    after_by_bar = {e.signal_bar: e.outcome for e in after}
    moved = {
        bar: outcome
        for bar, outcome in before_by_bar.items()
        if bar in after_by_bar and after_by_bar[bar] is not outcome
    }

    assert moved, "extending the data must change some unbounded outcomes"
    # And the plans are still identical, which is the part that must not move.
    before_plans = {e.signal_bar: (e.plan_entry, e.stop, e.target) for e in before}
    after_plans = {e.signal_bar: (e.plan_entry, e.stop, e.target) for e in after}
    for bar, plan in before_plans.items():
        assert after_plans[bar] == plan


# --------------------------------------------------------------------------
# Conflict policy
# --------------------------------------------------------------------------


def test_the_default_takes_at_most_one_position_at_a_time() -> None:
    """Three signals in twelve bars are not three independent observations, and a
    sample inflated by one piece of price movement measures nothing."""
    bars = _bars()
    skipped = replay(bars, config=CFG, horizon=6)
    parallel = replay(bars, config=CFG, horizon=6, conflict_policy=ConflictPolicy.PARALLEL)

    assert len(parallel) > len(skipped)
    assert skipped.skipped.get(SKIP_OPEN, 0) > 0
    assert SKIP_OPEN not in parallel.skipped
    assert parallel.conflict_policy is ConflictPolicy.PARALLEL


def test_an_open_position_that_already_exited_does_not_block_a_later_signal() -> None:
    """Whether a signal conflicts is answered by the open position's own outcome,
    not by the horizon it happened to be given.

    Blocking for the whole horizon would be the easy implementation, and it would
    silently discard every signal that followed a quick exit — a sample edited
    before anyone looked at it.
    """
    bars = _bars()
    result = replay(bars, config=CFG, horizon=40, conflict_policy=ConflictPolicy.SKIP)

    # Every consecutive pair of taken events must be non-overlapping in time, and
    # a position that exited early must not have held the floor until the horizon.
    for earlier, later in zip(result.events, result.events[1:]):
        assert later.fill_bar > earlier.fill_bar + earlier.bars_held


def test_close_and_reverse_differs_from_skip_and_from_parallel() -> None:
    """The three policies must be three behaviours, not one behaviour with two
    names. An earlier version of this loop never consulted the policy for anything
    but `SKIP`, which left `CLOSE_AND_REVERSE` behaving exactly like `PARALLEL`."""
    bars = _bars()
    skip = replay(bars, config=CFG, horizon=6, conflict_policy=ConflictPolicy.SKIP)
    reverse = replay(
        bars, config=CFG, horizon=6, conflict_policy=ConflictPolicy.CLOSE_AND_REVERSE
    )
    parallel = replay(
        bars, config=CFG, horizon=6, conflict_policy=ConflictPolicy.PARALLEL
    )

    assert len(parallel) >= len(reverse) >= len(skip)
    assert len(parallel) > len(skip)


def test_a_reversed_position_cannot_claim_the_move_that_followed_it() -> None:
    """The replaced position's path is cut at the bar the new one fills on."""
    result = replay(
        _bars(), config=CFG, horizon=6, conflict_policy=ConflictPolicy.CLOSE_AND_REVERSE
    )
    reversed_out = [e for e in result if "opposite signal" in e.detail]

    assert reversed_out, "fixture should produce at least one reversal"
    for one in reversed_out:
        assert "closed by an opposite signal" in one.detail
        assert one.outcome in (
            Outcome.NEITHER,
            Outcome.TARGET_FIRST,
            Outcome.STOP_FIRST,
            Outcome.AMBIGUOUS,
        )
    # A reversal is a close, so the next position may start on or after it.
    for earlier, later in zip(result.events, result.events[1:]):
        if "opposite signal" in earlier.detail:
            assert later.signal_bar > earlier.signal_bar
            assert earlier.direction == -later.direction


def test_bars_with_no_actionable_decision_are_counted_as_such() -> None:
    result = replay(_bars(), config=CFG, horizon=6)

    assert result.skipped.get(SKIP_NOT_ACTIONABLE, 0) > 0
    assert (
        result.skipped[SKIP_NOT_ACTIONABLE]
        + sum(result.skipped.values())
        - result.skipped[SKIP_NOT_ACTIONABLE]
        + len(result)
        == result.scanned
    )


# --------------------------------------------------------------------------
# Reporting, and what this module refuses to produce
# --------------------------------------------------------------------------


def test_sample_share_is_a_proportion_of_the_sample_not_a_rate_about_the_market() -> None:
    result = BacktestResult(
        events=(
            event(outcome=Outcome.TARGET_FIRST),
            event(outcome=Outcome.STOP_FIRST),
            event(outcome=Outcome.STOP_FIRST),
        )
    )

    assert result.sample_share(Outcome.TARGET_FIRST) == pytest.approx(1 / 3)
    assert result.sample_share(Outcome.STOP_FIRST) == pytest.approx(2 / 3)
    assert BacktestResult().sample_share(Outcome.TARGET_FIRST) is None


def test_the_result_refuses_to_produce_money() -> None:
    """No equity curve, no expectancy, no profit factor, no win rate. Those are
    claims about the future, and a green one built from unvalidated heuristics is
    the most misleading artefact this project could ship."""
    result = BacktestResult(events=(event(),))
    payload = json.loads(json.dumps(result.to_dict()))

    for forbidden in (
        "pnl",
        "equity",
        "expectancy",
        "profit_factor",
        "win_rate",
        "sharpe",
        "balance",
    ):
        assert not hasattr(result, forbidden), forbidden
        assert forbidden not in payload, forbidden


def test_caveats_travel_with_the_result_and_adapt_to_its_settings() -> None:
    """Including the interactions a reader would otherwise get wrong."""
    unbounded = BacktestResult(events=(event(),))
    assert list(CAVEATS) == list(unbounded.caveats)[: len(CAVEATS)]
    assert any("No horizon" in line for line in unbounded.caveats)
    assert any("keeps skipping signals" in line for line in unbounded.caveats)

    bounded = BacktestResult(
        events=(event(),),
        horizon=6,
        conflict_policy=ConflictPolicy.PARALLEL,
    )
    assert not any("No horizon" in line for line in bounded.caveats)
    assert not any("keeps skipping signals" in line for line in bounded.caveats)
    assert any("PARALLEL" in line for line in bounded.caveats)


def test_the_result_round_trips_through_json() -> None:
    result = replay(_bars(), config=CFG, horizon=6)
    restored = json.loads(json.dumps(result.to_dict()))

    assert restored["events"] == len(result)
    assert restored["horizon"] == 6
    assert restored["fill_policy"] == "NEXT_OPEN"
    assert restored["caveats"]
    assert restored["events_detail"][0]["outcome"] in {o.value for o in Outcome}
    assert all(
        row["outcome"] in {o.value for o in Outcome}
        for row in restored["events_detail"]
    )


def test_counts_always_include_every_outcome_so_a_reader_sees_the_whole_picture() -> None:
    result = BacktestResult(events=(event(outcome=Outcome.TARGET_FIRST),))

    assert set(result.counts()) == {o.value for o in Outcome}
    assert sum(result.counts().values()) == len(result)


def test_risk_and_reward_are_never_negative() -> None:
    short = event(direction=-1, entry=100.0, stop=105.0, target=90.0)

    assert short.risk == pytest.approx(5.0)
    assert short.reward == pytest.approx(10.0)
    assert not math.copysign(1, short.risk) < 0


def test_a_malformed_plan_is_skipped_rather_than_crashing_the_run() -> None:
    """One unusable decision must not take the whole replay down."""
    from dataclasses import replace

    class BrokenAnalyzer(Analyzer):
        def analyze(self, bars, **kwargs):  # noqa: ANN001, ANN003, ANN201
            base = super().analyze(bars, **kwargs)
            return replace(base, decision={**base.decision, "plan": {"direction": 0}})

    result = replay(_bars(), config=CFG, analyzer=BrokenAnalyzer(CFG), horizon=6)

    assert len(result) == 0
    assert result.skipped.get(SKIP_INVALID_PLAN, 0) > 0


def test_a_decision_with_no_plan_is_skipped_and_named() -> None:
    from dataclasses import replace

    class NoPlanAnalyzer(Analyzer):
        def analyze(self, bars, **kwargs):  # noqa: ANN001, ANN003, ANN201
            base = super().analyze(bars, **kwargs)
            return replace(base, decision={**base.decision, "plan": None})

    result = replay(_bars(), config=CFG, analyzer=NoPlanAnalyzer(CFG), horizon=6)

    assert len(result) == 0
    assert result.skipped.get(SKIP_NO_PLAN, 0) > 0
