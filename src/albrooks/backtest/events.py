"""Backtesting: what happened to the paths this engine's decisions pointed at.

## What this module measures, and what it refuses to measure

It measures **path geometry and outcome classification**: given a decision the
engine made at a closed bar, how far did price travel in the trade's favour, how
far against it, which level came first, and how many bars it took.

It does **not** produce a P&L series, an equity curve, an expectancy, a profit
factor, or a win rate. Those are the numbers a backtest exists to offer, and every
one of them is a *claim about the future* that this project cannot support:
nothing here has been validated against anything but itself. A green equity curve
built from unvalidated heuristics is the single most misleading artefact a trading
library can ship, and the fact that it is *arithmetically easy* to produce is
exactly why it is refused rather than merely labelled. Phase 19 supplies the
validation dataset; until then this module reports counts over the sample it was
given, and says so in its own output.

`sample_share()` exists and is deliberately not called a win rate.

## The three lies a backtest tells, and what this one does instead

### 1. The intra-bar order is unknowable

From OHLC you cannot know whether a bar's high or its low came first. A backtest
that resolves a bar containing both the target and the stop by picking the
favourable one is not measuring anything; it is choosing its own result.

So `AMBIGUOUS` is a first-class outcome, recorded on the event **and never
overwritten**. The resolution is a separate, explicit, configurable step
(`AmbiguityPolicy`) applied at *reporting* time, and its default is the
pessimistic reading. `OPTIMISTIC` is available because a caller who wants to see
the best case deserves to be able to ask for it explicitly — not because it is the
default.

### 2. The fill price is an assumption, not a fact

A decision is made from a closed bar, so the earliest price that was actually
available afterwards is the **next bar's open**. `FillPolicy.NEXT_OPEN` is the
default. Filling at the signal bar's close means filling at a price the engine had
when it could not yet have acted.

And a fill can arrive already dead: if the next open is already through the stop,
the trade never existed. That is `INVALID_ENTRY`, counted rather than quietly
dropped — a dropped invalid fill is a sample quietly edited in its own favour.

### 3. Overlapping signals inflate the sample

Three decisions in twelve bars is not three independent observations. The default
`ConflictPolicy.SKIP` takes at most one position at a time, so a burst of signals
cannot manufacture a sample out of one piece of price movement. `PARALLEL` is
available and names itself.

## Where the line between decision and outcome is

The event loop calls `analyze(bars, last_closed=k)` and then reads bars `k+1..` for
the **outcome only**. Those are separate statements, and the test suite asserts
both halves:

- **The plan is invariant.** The entry, stop and target on an event equal the plan
  from `analyze(bars, last_closed=k)` exactly, and are unchanged when bars are
  appended after `k`.
- **The outcome is a function of the horizon, not of the future.** Append bars
  beyond `k + horizon` and nothing on the event moves. With `horizon=None` a
  `NEITHER` at `k` can legitimately become a `TARGET_FIRST` once more bars arrive,
  so that case is *not* claimed to be invariant — and saying so is the difference
  between a contract and a hope.

## What the slowness costs

`replay` is O(n²): it re-analyses from the start at every bar. An incremental or
cached path would be far faster and is deliberately absent, because
`NON_REPAINT_CONTRACT.md` is worth more than the speed, and a cache that is right
nine times in ten is the classic way a backtest reports a result the engine would
never have produced live.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator, Mapping, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.engine.analyzer import Analyzer
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.price_action.bars import calculate_atr_series

# --------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------


class Outcome(str, Enum):
    """What happened to a path, as far as OHLC can say.

    `AMBIGUOUS` and `INVALID_ENTRY` are outcomes, not special cases to be tidied
    away. Both are things that happened.
    """

    #: The target was reached before the stop.
    TARGET_FIRST = "TARGET_FIRST"
    #: The stop was reached before the target.
    STOP_FIRST = "STOP_FIRST"
    #: Neither level was reached inside the horizon.
    NEITHER = "NEITHER"
    #: One bar contained both levels and OHLC cannot say which came first.
    AMBIGUOUS = "AMBIGUOUS"
    #: The fill price was already through the stop, or already past the target.
    INVALID_ENTRY = "INVALID_ENTRY"

    def to_dict(self) -> str:
        return self.value


class FillPolicy(str, Enum):
    """Where the fill is assumed to happen.

    The default is the only one that is defensible from a closed-bar engine: the
    earliest price available *after* the decision.
    """

    #: The next bar's open — the first price that existed once the decision could
    #: be acted on. The default.
    NEXT_OPEN = "NEXT_OPEN"
    #: The signal bar's close — a price the engine had when it could not yet act.
    #: Available for comparison, and named for what it assumes.
    SIGNAL_CLOSE = "SIGNAL_CLOSE"

    def to_dict(self) -> str:
        return self.value


class ConflictPolicy(str, Enum):
    """What to do when a decision arrives while a position is already open."""

    #: Take at most one position at a time. The default, because three signals in
    #: twelve bars are not three independent observations.
    SKIP = "SKIP"
    #: Close the open position at the next open and take the new one.
    CLOSE_AND_REVERSE = "CLOSE_AND_REVERSE"
    #: Allow overlapping positions. Names itself.
    PARALLEL = "PARALLEL"

    def to_dict(self) -> str:
        return self.value


class AmbiguityPolicy(str, Enum):
    """How to read a bar that contained both the target and the stop.

    Applied at **reporting** time; the event keeps `AMBIGUOUS` either way.
    """

    #: Assume the adverse order. The default, and the only honest one to assume.
    STOP_FIRST = "STOP_FIRST"
    #: Assume the favourable order, for a caller who wants the best case.
    TARGET_FIRST = "TARGET_FIRST"
    #: Leave the sample out of the counts entirely.
    EXCLUDE = "EXCLUDE"

    def to_dict(self) -> str:
        return self.value


#: Carried in every result. Read these before reading a number.
CAVEATS: tuple[str, ...] = (
    "These are counts and path statistics over the sample this run was given. "
    "They are not a probability, an edge, or a forecast.",
    "Nothing in this project has been validated against outcomes. A count of "
    "target-first events over a sample says nothing about the next one.",
    "OHLC cannot say which of a bar's extremes came first, so a bar containing "
    "both the target and the stop is recorded as AMBIGUOUS and left unresolved "
    "in the event itself.",
    "The fill price is an assumption (FillPolicy), not an observation. The default "
    "assumes the next bar's open, which is the first price that existed once the "
    "decision could be acted on.",
    "No P&L, equity curve, expectancy or profit factor is produced. Those are "
    "claims about the future, and nothing here has been validated.",
    "The sample is not independent: consecutive decisions in one trend are "
    "correlated, and ConflictPolicy.SKIP reduces that without removing it.",
)

#: Reason codes for a bar where no event was created.
SKIP_NOT_ACTIONABLE = "DECISION_NOT_ACTIONABLE"
SKIP_NO_PLAN = "NO_PLAN"
SKIP_OPEN = "POSITION_ALREADY_OPEN"
SKIP_NO_FORWARD_BARS = "NO_FORWARD_BARS"
SKIP_INVALID_PLAN = "INVALID_PLAN"


# --------------------------------------------------------------------------
# The event
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TradeEvent:
    """One decision and what the path afterwards did.

    Filled at the *event* rather than at the report, so an `AMBIGUOUS` outcome is
    a fact about the bar and not a choice the report made on its behalf.
    """

    #: The closed bar the decision was made on.
    signal_bar: int
    #: Which candidate won, for traceability back to the decision.
    subject: str
    direction: int
    #: The bar the fill was assumed on, and the price.
    fill_bar: int
    entry: float
    stop: float
    target: float
    #: The plan's own entry, before the fill policy was applied. Kept so the
    #: difference between "the plan said 104" and "it filled at 104.3" is visible.
    plan_entry: float
    outcome: Outcome
    #: Maximum favourable / adverse excursion from the **fill**, in price units.
    mfe: float = 0.0
    mae: float = 0.0
    #: The same excursions in ATR multiples, which is the only version of them that
    #: is comparable across instruments and regimes.
    mfe_atr: float = 0.0
    mae_atr: float = 0.0
    bars_to_target: int = -1
    bars_to_stop: int = -1
    bars_held: int = 0
    atr: float = 0.0
    #: Why this is `INVALID_ENTRY`, when it is.
    detail: str = ""

    @property
    def is_long(self) -> bool:
        return self.direction > 0

    @property
    def risk(self) -> float:
        """Distance from fill to stop, per unit. Never negative."""
        return abs(self.entry - self.stop)

    @property
    def reward(self) -> float:
        """Distance from fill to target, per unit. Never negative."""
        return abs(self.target - self.entry)

    def resolved(self, policy: AmbiguityPolicy) -> Outcome:
        """The outcome under a stated ambiguity policy.

        Only `AMBIGUOUS` is affected. Everything else is returned unchanged, so a
        reader can see at a glance that the policy did not quietly reclassify the
        whole sample.
        """
        if self.outcome is not Outcome.AMBIGUOUS:
            return self.outcome
        if policy is AmbiguityPolicy.TARGET_FIRST:
            return Outcome.TARGET_FIRST
        if policy is AmbiguityPolicy.STOP_FIRST:
            return Outcome.STOP_FIRST
        return Outcome.AMBIGUOUS

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_bar": self.signal_bar,
            "subject": self.subject,
            "direction": self.direction,
            "fill_bar": self.fill_bar,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "plan_entry": self.plan_entry,
            "outcome": self.outcome.to_dict(),
            "mfe": self.mfe,
            "mae": self.mae,
            "mfe_atr": self.mfe_atr,
            "mae_atr": self.mae_atr,
            "bars_to_target": self.bars_to_target,
            "bars_to_stop": self.bars_to_stop,
            "bars_held": self.bars_held,
            "atr": self.atr,
            "detail": self.detail,
        }


# --------------------------------------------------------------------------
# The result
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Every event, the reasons for every non-event, and the caveats.

    `skipped` is a count per reason code rather than nothing, because "no signal"
    and "a signal arrived while a position was open" and "the series was too short
    to say" are three different facts about the run and a bare event list expresses
    none of them.
    """

    events: tuple[TradeEvent, ...] = ()
    #: Bars the loop looked at, including the warmup.
    scanned: int = 0
    #: Bars skipped before the first decision was even attempted.
    warmup: int = 0
    #: Forward bars allowed per event, or `None` for "the rest of the series".
    horizon: int | None = None
    fill_policy: FillPolicy = FillPolicy.NEXT_OPEN
    conflict_policy: ConflictPolicy = ConflictPolicy.SKIP
    ambiguity_policy: AmbiguityPolicy = AmbiguityPolicy.STOP_FIRST
    skipped: Mapping[str, int] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self) -> Iterator[TradeEvent]:
        return iter(self.events)

    def counts(self, policy: AmbiguityPolicy | None = None) -> dict[str, int]:
        """Outcome counts under a stated ambiguity policy.

        `INVALID_ENTRY` is always counted: a fill that arrived dead did happen, and
        hiding it would edit the sample in its own favour. `EXCLUDE` drops
        `AMBIGUOUS` from the tally *and* records nothing in its place, so the
        total falls — which is the visible consequence of excluding.
        """
        chosen = policy or self.ambiguity_policy
        out: dict[str, int] = {outcome.to_dict(): 0 for outcome in Outcome}
        for event in self.events:
            resolved = event.resolved(chosen)
            if resolved is Outcome.AMBIGUOUS and chosen is AmbiguityPolicy.EXCLUDE:
                continue
            out[resolved.to_dict()] += 1
        return out

    def sample_share(
        self, outcome: Outcome, policy: AmbiguityPolicy | None = None
    ) -> float | None:
        """The share of *this sample* with that outcome, or `None` if the sample is
        empty.

        Named `sample_share` rather than `win_rate` on purpose. It is a proportion
        of the events this run produced, which is a statement about the sample and
        not about the market. `None` rather than `0.0` for an empty sample, because
        "no events" is not a proportion of zero.
        """
        chosen = policy or self.ambiguity_policy
        counts = self.counts(chosen)
        total = sum(counts.values())
        if total == 0:
            return None
        return counts[outcome.to_dict()] / total

    def mean_mfe_atr(self) -> float | None:
        """Mean favourable excursion in ATR, over events that had a path at all.

        `INVALID_ENTRY` events are excluded because they have no path, and
        `AMBIGUOUS` events are included because a path is a path whichever end it
        reached first.
        """
        values = [
            e.mfe_atr
            for e in self.events
            if e.outcome not in (Outcome.INVALID_ENTRY,)
        ]
        return sum(values) / len(values) if values else None

    def mean_mae_atr(self) -> float | None:
        values = [
            e.mae_atr
            for e in self.events
            if e.outcome not in (Outcome.INVALID_ENTRY,)
        ]
        return sum(values) / len(values) if values else None

    @property
    def caveats(self) -> tuple[str, ...]:
        """The reading instructions, carried in the output rather than the docs."""
        out = list(CAVEATS)
        if self.horizon is None:
            out.append(
                "No horizon was set, so a path runs to the end of the supplied "
                "series and the excursions are measured over everything that "
                "happened afterwards. That is not a holding period."
            )
        if self.conflict_policy is ConflictPolicy.SKIP and self.horizon is None:
            out.append(
                "ConflictPolicy.SKIP with no horizon holds a position open until a "
                "level is actually reached, so a position that never reaches one "
                "keeps skipping signals until the series ends."
            )
        if self.conflict_policy is ConflictPolicy.PARALLEL:
            out.append(
                "ConflictPolicy.PARALLEL was used, so events overlap and the "
                "sample is not independent. Counts are not comparable with a run "
                "that used the default."
            )
        return tuple(out)

    def summary(self, policy: AmbiguityPolicy | None = None) -> dict[str, Any]:
        """Counts and path statistics, and the settings that produced them."""
        return {
            "events": len(self.events),
            "scanned": self.scanned,
            "warmup": self.warmup,
            "horizon": self.horizon,
            "counts": self.counts(policy),
            "mean_mfe_atr": self.mean_mfe_atr(),
            "mean_mae_atr": self.mean_mae_atr(),
            "skipped": dict(self.skipped),
            "fill_policy": self.fill_policy.to_dict(),
            "conflict_policy": self.conflict_policy.to_dict(),
            "ambiguity_policy": (policy or self.ambiguity_policy).to_dict(),
            "caveats": list(self.caveats),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.summary()
        payload["events_detail"] = [event.to_dict() for event in self.events]
        return payload


# --------------------------------------------------------------------------
# Path classification
# --------------------------------------------------------------------------


def _fill_bar(bars: BarSeries, signal_bar: int, policy: FillPolicy) -> tuple[int, float] | None:
    """The bar and price a fill is assumed at, or `None` if there is no such bar.

    `NEXT_OPEN` needs bar `signal + 1`, which is the first price that existed once
    the decision could be acted on. A signal on the very last bar has no fill and
    produces no event, which is stated as a skip reason rather than as a zero
    excursion.
    """
    if policy is FillPolicy.SIGNAL_CLOSE:
        if 0 <= signal_bar < len(bars):
            return signal_bar, bars[signal_bar].close
        return None
    index = signal_bar + 1
    if 0 <= index < len(bars):
        return index, bars[index].open
    return None


def _invalid_entry(direction: int, entry: float, stop: float, target: float) -> str:
    """Why a fill cannot be traded, or `""` if it can.

    A fill that is already through the stop, or already beyond the target, never
    existed as a trade. Both are reported rather than dropped: an invalid fill
    quietly removed is a sample edited in its own favour.
    """
    if direction > 0:
        if entry <= stop:
            return "FILL_ALREADY_THROUGH_STOP"
        if entry >= target:
            return "FILL_ALREADY_PAST_TARGET"
    else:
        if entry >= stop:
            return "FILL_ALREADY_THROUGH_STOP"
        if entry <= target:
            return "FILL_ALREADY_PAST_TARGET"
    return ""


def _forward_window(
    bars: BarSeries, fill_bar: int, horizon: int | None, end_bar: int | None = None
) -> list[Bar]:
    """Bars from `fill_bar` forward, up to the horizon or an explicit end.

    The fill bar is included: a trade can be stopped out or reach its target on the
    bar it was filled on, and excluding it would understate both excursions.

    `end_bar` is inclusive and exists for `CLOSE_AND_REVERSE`, where a position is
    closed early by a new signal and its path must stop there rather than run on
    into a move that belonged to the trade that replaced it.
    """
    limit = len(bars) if horizon is None else min(len(bars), fill_bar + horizon)
    if end_bar is not None:
        limit = min(limit, end_bar + 1)
    return list(bars[fill_bar:limit])


def _measure(
    direction: int, entry: float, stop: float, target: float, window: Sequence[Bar]
) -> tuple[Outcome, int, int, int, str, float, float]:
    """`(outcome, to_target, to_stop, held, detail, mfe, mae)` for a forward window.

    The excursions stop at the exit. Measuring them to the end of the window would
    credit a stopped-out trade with everything the market did afterwards, which
    inflates MFE by an amount that has nothing to do with the trade.
    """
    outcome, to_target, to_stop, detail = _classify(
        direction, window, entry, stop, target
    )
    held = to_stop if outcome is Outcome.STOP_FIRST else to_target
    if held < 0:
        held = max(0, len(window) - 1)
    mfe, mae = _excursions(direction, entry, window[: held + 1])
    return outcome, to_target, to_stop, held, detail, mfe, mae


def _excursions(
    direction: int, entry: float, window: Sequence[Bar]
) -> tuple[float, float]:
    """`(mfe, mae)` in price units from the fill, never negative.

    A long's favourable excursion is how far the *high* went above the entry; a
    short's is how far the *low* went below. Both are floored at zero, because an
    excursion is a distance travelled and a path that only ever moved against you
    has no favourable one.
    """
    if not window:
        return 0.0, 0.0
    best = max(b.high for b in window)
    worst = min(b.low for b in window)
    if direction > 0:
        return max(0.0, best - entry), max(0.0, entry - worst)
    return max(0.0, entry - worst), max(0.0, best - entry)


def _first_target_touch(
    direction: int, window: Sequence[Bar], target: float
) -> int:
    """Offset of the first bar whose *favourable* extreme reached `target`, or -1.

    The extreme depends on which side the level is on, not on which side the entry
    was: a long's target is reached by a **high** and a short's by a **low**.
    Conflating the two is how a backtest ends up reporting a stop it never checked.
    """
    for offset, bar in enumerate(window):
        if direction > 0:
            if bar.high >= target:
                return offset
        elif bar.low <= target:
            return offset
    return -1


def _first_stop_touch(direction: int, window: Sequence[Bar], stop: float) -> int:
    """Offset of the first bar whose *adverse* extreme reached `stop`, or -1.

    A long's stop is hit by a **low** and a short's by a **high**.

    "Reached" is `>=` / `<=`, so a bar that opens exactly at the level counts. A
    level is a price, and a price that was traded is a price that was reached.
    """
    for offset, bar in enumerate(window):
        if direction > 0:
            if bar.low <= stop:
                return offset
        elif bar.high >= stop:
            return offset
    return -1


def _classify(
    direction: int, window: Sequence[Bar], entry: float, stop: float, target: float
) -> tuple[Outcome, int, int, str]:
    """`(outcome, bars_to_target, bars_to_stop, detail)` from a forward window.

    The ambiguity rule is the load-bearing line: when one bar contains both levels
    the result is `AMBIGUOUS`, and **not** the favourable reading. A backtest that
    picks the better of the two is not measuring a market.
    """
    to_target = _first_target_touch(direction, window, target)
    to_stop = _first_stop_touch(direction, window, stop)

    if to_target < 0 and to_stop < 0:
        return Outcome.NEITHER, -1, -1, ""
    if to_target >= 0 and to_stop >= 0 and to_target == to_stop:
        return Outcome.AMBIGUOUS, to_target, to_stop, "one bar contained both levels"
    if to_target >= 0 and (to_stop < 0 or to_target < to_stop):
        return Outcome.TARGET_FIRST, to_target, to_stop, ""
    return Outcome.STOP_FIRST, to_target, to_stop, ""


# --------------------------------------------------------------------------
# An open position
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Open:
    """A position that has been filled but whose path has not been read yet.

    The event is built when the position **closes**, not when it opens, because
    how long the path is depends on when the position ended — and a
    `CLOSE_AND_REVERSE` can end it early. Building the event at fill time and
    patching it afterwards would mean rewriting a record that was already emitted.
    """

    signal_bar: int
    subject: str
    direction: int
    fill_bar: int
    entry: float
    stop: float
    target: float
    plan_entry: float
    atr: float


def _settle(
    position: _Open,
    series: BarSeries,
    horizon: int | None,
    end_bar: int | None = None,
    detail: str = "",
) -> tuple[TradeEvent, int]:
    """Close `position`, read its path, and return `(event, exit_bar)`.

    `end_bar` bounds the path early, for a position closed by a reversal. `detail`
    records *why* it closed early, so a truncated path is never mistaken for one
    that simply ran out of horizon.

    `exit_bar` is the bar on which the position stopped being open, which is what
    decides whether a later signal may be taken. It is derived from the path rather
    than from the horizon, so a position that reached its target on bar three does
    not block signals for the rest of the window.
    """
    window = _forward_window(series, position.fill_bar, horizon, end_bar=end_bar)
    outcome, to_target, to_stop, held, path_detail, mfe, mae = _measure(
        position.direction, position.entry, position.stop, position.target, window
    )
    reasons = [part for part in (path_detail, detail) if part]
    event = TradeEvent(
        signal_bar=position.signal_bar,
        subject=position.subject,
        direction=position.direction,
        fill_bar=position.fill_bar,
        entry=position.entry,
        stop=position.stop,
        target=position.target,
        plan_entry=position.plan_entry,
        outcome=outcome,
        mfe=mfe,
        mae=mae,
        mfe_atr=mfe / position.atr if position.atr > 0.0 else 0.0,
        mae_atr=mae / position.atr if position.atr > 0.0 else 0.0,
        bars_to_target=to_target,
        bars_to_stop=to_stop,
        bars_held=held,
        atr=position.atr,
        detail="; ".join(reasons),
    )
    return event, position.fill_bar + held


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------


def replay(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    *,
    config: AnalyzerConfig | None = None,
    analyzer: Analyzer | None = None,
    warmup: int = 0,
    horizon: int | None = None,
    fill_policy: FillPolicy = FillPolicy.NEXT_OPEN,
    conflict_policy: ConflictPolicy = ConflictPolicy.SKIP,
    ambiguity_policy: AmbiguityPolicy = AmbiguityPolicy.STOP_FIRST,
    symbol: str = "GENERIC",
    timeframe: str = "UNKNOWN",
) -> BacktestResult:
    """Walk the series one closed bar at a time and record what the path did.

    `warmup` bars are not traded, so a run does not begin on a series too short to
    classify. The loop then calls `analyze(bars, last_closed=k)` at every bar and
    reads bars `k+1..` **for the outcome only** — the two are separate statements
    here for the same reason they are separate in the tests.

    The decision is the engine's own: a bar is traded only when `decision.action`
    is `BUY` or `SELL`, which means it already passed every gate and survived the
    ranking. This module does not re-gate, re-rank, or second-guess.
    """
    cfg = config or AnalyzerConfig()
    engine = analyzer or Analyzer(cfg)
    series = bars if isinstance(bars, BarSeries) else BarSeries(bars)
    atrs = calculate_atr_series(series, period=cfg.atr_period)

    events: list[TradeEvent] = []
    skipped: dict[str, int] = {}
    open_position: _Open | None = None

    def _skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    def _close(
        position: _Open,
        end_bar: int | None = None,
        detail: str = "",
    ) -> None:
        event, _ = _settle(position, series, horizon, end_bar, detail)
        events.append(event)

    for index in range(warmup, len(series)):
        result = engine.analyze(
            series, symbol=symbol, timeframe=timeframe, last_closed=index
        )
        action = str(result.decision.get("action", ""))
        if action not in ("BUY", "SELL"):
            _skip(SKIP_NOT_ACTIONABLE)
            continue

        plan = result.decision.get("plan")
        if not isinstance(plan, Mapping):
            _skip(SKIP_NO_PLAN)
            continue
        try:
            direction = int(plan["direction"])
            stop = float(plan["stop"])
            target = float(plan["target"])
            plan_entry = float(plan["entry"])
        except (KeyError, TypeError, ValueError):
            _skip(SKIP_INVALID_PLAN)
            continue
        if direction not in (1, -1) or min(stop, target, plan_entry) <= 0.0:
            _skip(SKIP_INVALID_PLAN)
            continue

        fill = _fill_bar(series, index, fill_policy)
        if fill is None:
            _skip(SKIP_NO_FORWARD_BARS)
            continue
        fill_bar, entry = fill
        atr = atrs[index] if index < len(atrs) else 0.0

        if open_position is not None and conflict_policy is not ConflictPolicy.PARALLEL:
            # Whether the open position still blocks this signal is answered by its
            # own path, read up to the bar this signal would fill on. A position that
            # reached its target three bars ago must not go on blocking signals for
            # the rest of the window, and treating the horizon as "the position is
            # open until the horizon ends" gets that wrong.
            # The probe stops at the bar *before* the new fill. A level reached on the
            # new fill's own bar happens intrabar, after that bar's open, so a fill at
            # that open would be taking the new position before the old one was
            # closed. Requiring the exit to be strictly earlier is the reading that
            # cannot be accused of that.
            probe = _forward_window(
                series, open_position.fill_bar, horizon, end_bar=fill_bar - 1
            )
            probe_outcome = _measure(
                open_position.direction,
                open_position.entry,
                open_position.stop,
                open_position.target,
                probe,
            )[0]
            still_open = probe_outcome is Outcome.NEITHER

            if still_open:
                if conflict_policy is ConflictPolicy.SKIP:
                    _skip(SKIP_OPEN)
                    continue
                if direction == open_position.direction:
                    # Not a reversal. The trade already running *is* this trade, so
                    # counting it as taken would double the same position.
                    _skip(SKIP_OPEN)
                    continue
                # A genuine reversal. The replaced position's path is cut at the new
                # fill, so it cannot claim a move that belonged to its replacement,
                # and the fact that it closed early is recorded rather than left to
                # look like a horizon timeout.
                _close(
                    open_position,
                    end_bar=fill_bar - 1,
                    detail="closed by an opposite signal",
                )
            else:
                _close(open_position)
            open_position = None

        bad = _invalid_entry(direction, entry, stop, target)
        if bad:
            events.append(
                TradeEvent(
                    signal_bar=index,
                    subject=str(result.decision.get("subject", "")),
                    direction=direction,
                    fill_bar=fill_bar,
                    entry=entry,
                    stop=stop,
                    target=target,
                    plan_entry=plan_entry,
                    outcome=Outcome.INVALID_ENTRY,
                    atr=atr,
                    detail=bad,
                )
            )
            continue

        position = _Open(
            signal_bar=index,
            subject=str(result.decision.get("subject", "")),
            direction=direction,
            fill_bar=fill_bar,
            entry=entry,
            stop=stop,
            target=target,
            plan_entry=plan_entry,
            atr=atr,
        )
        if conflict_policy is ConflictPolicy.PARALLEL:
            _close(position)
        else:
            open_position = position

    if open_position is not None:
        _close(open_position)

    return BacktestResult(
        events=tuple(events),
        scanned=max(0, len(series) - warmup),
        warmup=warmup,
        horizon=horizon,
        fill_policy=fill_policy,
        conflict_policy=conflict_policy,
        ambiguity_policy=ambiguity_policy,
        skipped=skipped,
    )
