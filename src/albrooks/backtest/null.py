"""The stated null: what the same count would be without the engine's claim.

## Why this module exists

`events.py` measures outcomes and refuses to call them an edge, and `VALIDATION.md`
§9.4 names the reason: **a sample share of target-first events means nothing
without what the same count would be if the engine were wrong.** Without that
comparison, `sample_share(TARGET_FIRST)` is a number whose only interpretation is
"however many of the trades the engine chose happened to work", which is true of
every set of trades ever taken.

This module supplies the missing half. It is the *null distribution*: the same
count, computed on a version of the sample in which the engine's directional claim
has been destroyed and nothing else has been touched.

## The null, stated exactly

For every event the engine produced, build a counterfactual that keeps

- the **same fill bar** and the **same fill price**,
- the **same risk** and the **same reward**, so the R:R ratio and both ATR-scaled
  distances are preserved exactly,
- the same horizon, fill policy and ambiguity policy,

and replaces only the **direction**, by mirroring the two levels about the entry
price. Which way to mirror is drawn at random, independently per event, so the
engine's share of correctly-signed calls is exactly what the null destroys.

The levels are mirrored rather than re-derived because the plan's stop and target
are themselves a function of the direction the engine chose. Re-deriving them for a
counterfactual would hand the null a *different* trade, and the comparison would no
longer isolate anything.

**Why the direction and not the timing.** `VALIDATION.md` §9.4 says "random entries
into the same levels", and that phrase admits two readings: random direction, or
random timing. Randomising the *timing* would confound the engine's claim about
*when* with its claim about *which way*, and because the stop and target are
direction-dependent, a randomly-timed entry at an unchanged direction leaves the
directional claim entirely intact — the null would then be testing something the
engine never asserted. Randomising direction isolates the one claim the engine
actually makes, and the timing is held fixed at the engine's own choice so that the
comparison is *matched* rather than generous to either side.

## What this module refuses to do

**It refuses to conclude.** This is the load-bearing refusal, and it is not
temporary politeness:

- `verdict` is the constant `UNDECIDED`, always. It is not computed from the
  numbers, so no input can change it.
- `NullResult.to_dict()` reports `"is_probability": false`, as every other surface
  in this project does.
- The comparison statistic is reported as a **count of null draws**, named
  `null_draws_at_or_above_observed`, and is explicitly *not* a p-value. A p-value
  is a calibrated tail probability, and calibrating it needs the other three
  ingredients in `VALIDATION.md` §9 — real data, a labelled sample with stated
  provenance, and an out-of-sample split. None of them exist. Reading a fraction of
  random draws as a p-value is the exact substitution this project refuses
  everywhere else, and it would be easy here *because* a number is available.

The value of stating the null **before** seeing an answer is the whole point. A null
chosen after the result is known is not a null, it is a rationalisation, and by
running it now — on fixtures, with a fixed seed, refusing to score it — the
comparison is pinned down before any real data exists to bias it.

## The two preconditions it does enforce

1. **`ConflictPolicy.SKIP` only.** The null flips each event's direction
   independently, which is only sound when the events do not already overlap: two
   overlapping positions that both flip can become the *same* position twice. `SKIP`
   takes at most one position at a time, so the events are sequential. `PARALLEL`
   breaks the independence the whole argument rests on, and `CLOSE_AND_REVERSE`
   truncates a path at a bar this module cannot recover from the event, so the
   counterfactual window would silently differ from the observed one. Both are
   refused rather than approximated.
2. **A seed, always.** `NullDesign.seed` defaults to a fixed value and is carried
   into the output, so a run is reproducible and a number in a document can be
   re-derived. A null that cannot be reproduced is an anecdote.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Sequence

from albrooks.backtest.events import (
    AmbiguityPolicy,
    BacktestResult,
    ConflictPolicy,
    Outcome,
    TradeEvent,
    _classify,
    _forward_window,
    _invalid_entry,
)
from albrooks.core.bars import Bar, BarSeries

#: The only answer this module can give. Not computed from anything.
VERDICT = "UNDECIDED"

#: Why the verdict cannot move, carried in the output rather than left to a reader
#: to infer. Each entry is a `VALIDATION.md` §9 ingredient that is missing.
BLOCKED_ON: tuple[str, ...] = (
    "Real data: every bar available to this project so far is hand-built or "
    "synthetic, and a chart the author drew cannot be surprised.",
    "A labelled sample with a stated provenance: there is none, so there is "
    "nothing to compare the engine's own labels against.",
    "An out-of-sample split: without one, any threshold chosen here would be "
    "fitted to the same bars it is scored on.",
    "Therefore the tail fraction below is a count of random draws and NOT a "
    "p-value. It is not calibrated, and it cannot become one from this data.",
)


class NullUnavailable(RuntimeError):
    """The run's shape does not support a matched null. Never worked around."""


# --------------------------------------------------------------------------
# The design
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NullDesign:
    """Everything about the null that is chosen in advance.

    Every field here is a decision that could bias the result, which is why they
    are all explicit, all have defaults, and all are carried into the output. A
    null whose parameters are not recorded is a null whose parameters can be
    changed after the fact.
    """

    #: How many random draws to take. Each draw is one full pass over every event.
    randomizations: int = 1000
    #: Fixed by default so a run is reproducible without the caller choosing.
    seed: int = 20240501
    #: Read at reporting time, exactly as `events.py` does, so the observed and
    #: null tallies are resolved by the same rule or not at all.
    ambiguity_policy: AmbiguityPolicy = AmbiguityPolicy.STOP_FIRST

    def __post_init__(self) -> None:
        if self.randomizations < 1:
            raise ValueError(f"randomizations must be at least 1, got {self.randomizations}")


# --------------------------------------------------------------------------
# The counterfactual
# --------------------------------------------------------------------------


def mirror_levels(entry: float, stop: float, target: float) -> tuple[float, float]:
    """`(stop, target)` reflected about `entry`, preserving risk and reward.

    The reflection is about the entry rather than a re-derivation from ATR, so the
    counterfactual distances are *exactly* the observed ones and cannot drift by a
    rounding step. A mirrored level that differed even slightly would make the
    comparison a claim about two slightly different trades.

    Mirroring also preserves whether a fill is tradable: a fill already through the
    stop is still through the mirrored stop, because the distance is unchanged.
    That is why `INVALID_ENTRY` survives the transformation instead of having to be
    re-classified from a rule that could disagree with `events.py`.
    """
    return 2.0 * entry - stop, 2.0 * entry - target


def counterfactual(
    event: TradeEvent, flip: bool, window: Sequence[Bar]
) -> Outcome:
    """The outcome this event would have had with the direction destroyed.

    `flip` is the draw. When false the event is re-classified *unchanged*, which is
    what keeps the null honest: half the events are left alone, so the null share
    is not mechanically pushed to one extreme by the transformation itself.
    """
    if not flip:
        return event.outcome
    direction = -event.direction
    stop, target = mirror_levels(event.entry, event.stop, event.target)
    if _invalid_entry(direction, event.entry, stop, target):
        return Outcome.INVALID_ENTRY
    return _classify(direction, window, event.entry, stop, target)[0]


# --------------------------------------------------------------------------
# The result
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NullResult:
    """The observed count beside the null it has to beat, and no conclusion."""

    design: NullDesign
    #: Events the comparison was computed over, after the preconditions.
    events: int
    #: The engine's own tally, under the same ambiguity policy as the null.
    observed_counts: dict[str, int]
    observed_share: float | None
    #: One share per random draw, in draw order.
    null_shares: tuple[float, ...]
    null_mean: float | None
    null_std: float | None
    #: How many draws matched or beat `observed_share`. **Not a p-value.**
    null_draws_at_or_above_observed: int | None

    @property
    def verdict(self) -> str:
        """Always `UNDECIDED`. A property with no inputs, deliberately."""
        return VERDICT

    @property
    def caveats(self) -> tuple[str, ...]:
        return (
            "This is a null distribution, not a verdict. The engine's count has "
            "not been shown to beat anything, and the number below is not a "
            "p-value.",
            *BLOCKED_ON,
            "The null preserves the fill bar, the fill price, the risk and the "
            "reward, and destroys only the direction. It therefore tests the "
            "engine's directional claim and nothing else -- not its timing, not "
            "its stop placement, and not whether these setups are worth trading "
            "at all.",
            "Events are independent only because ConflictPolicy.SKIP was used. "
            "That reduces serial dependence within a trend; it does not remove "
            "it, and the null inherits whatever remains.",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": self.events,
            "design": {
                "randomizations": self.design.randomizations,
                "seed": self.design.seed,
                "ambiguity_policy": self.design.ambiguity_policy.to_dict(),
            },
            "observed_counts": dict(self.observed_counts),
            "observed_share": self.observed_share,
            "null_mean": self.null_mean,
            "null_std": self.null_std,
            "null_draws_at_or_above_observed": self.null_draws_at_or_above_observed,
            "null_shares": list(self.null_shares),
            "verdict": self.verdict,
            "is_probability": False,
            "caveats": list(self.caveats),
        }


# --------------------------------------------------------------------------
# The distribution
# --------------------------------------------------------------------------


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _std(values: Sequence[float]) -> float:
    """Population standard deviation, over the draws actually taken."""
    mean = _mean(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return variance**0.5


def null_distribution(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    result: BacktestResult,
    design: NullDesign | None = None,
) -> NullResult:
    """Compare the engine's count against the count its own claim removed.

    `bars` is the same series `replay` was given. It is required rather than taken
    from `result` because the forward window has to be **re-derived per event**, and
    reusing a cached outcome instead would mean the null was scored on the engine's
    own arithmetic rather than on the price.
    """
    chosen = design or NullDesign()

    if result.conflict_policy is not ConflictPolicy.SKIP:
        raise NullUnavailable(
            f"a matched null needs ConflictPolicy.SKIP, got "
            f"{result.conflict_policy.to_dict()}. PARALLEL overlaps the events, so "
            f"independent direction draws are not independent trades; "
            f"CLOSE_AND_REVERSE truncates a path at a bar the event does not "
            f"record, so the counterfactual window would not be the observed one."
        )
    if result.ambiguity_policy is not chosen.ambiguity_policy:
        raise NullUnavailable(
            f"the run resolved ambiguity as "
            f"{result.ambiguity_policy.to_dict()} but the null resolves it as "
            f"{chosen.ambiguity_policy.to_dict()}. The observed and null tallies "
            f"must be read by the same rule or not compared at all."
        )
    if not result.events:
        raise NullUnavailable(
            "the run produced no events, so there is no sample to compare. An "
            "empty sample has no share, and reporting 0.0 would be a fabricated "
            "number."
        )

    series = bars if isinstance(bars, BarSeries) else BarSeries(bars)

    # One window per event, built once: the window depends only on the fill bar and
    # the horizon, neither of which the counterfactual changes.
    windows = [
        _forward_window(series, event.fill_bar, result.horizon) for event in result.events
    ]

    observed = result.counts(chosen.ambiguity_policy)
    observed_total = sum(observed.values())
    observed_share: float | None = (
        observed[Outcome.TARGET_FIRST.to_dict()] / observed_total if observed_total else None
    )

    rng = random.Random(chosen.seed)
    shares: list[float] = []
    for _ in range(chosen.randomizations):
        counts = {outcome.to_dict(): 0 for outcome in Outcome}
        for event, window in zip(result.events, windows):
            outcome = counterfactual(event, rng.random() < 0.5, window)
            counts[outcome.to_dict()] += 1
        total = sum(counts.values())
        if total:
            shares.append(counts[Outcome.TARGET_FIRST.to_dict()] / total)

    at_or_above: int | None = None
    if observed_share is not None:
        at_or_above = sum(1 for share in shares if share >= observed_share)

    return NullResult(
        design=chosen,
        events=len(result.events),
        observed_counts=observed,
        observed_share=observed_share,
        null_shares=tuple(shares),
        null_mean=_mean(shares) if shares else None,
        null_std=_std(shares) if len(shares) > 1 else None,
        null_draws_at_or_above_observed=at_or_above,
    )
