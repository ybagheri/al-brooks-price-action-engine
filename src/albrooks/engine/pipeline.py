"""Multi-timeframe orchestration: a higher-timeframe read the low timeframe can
be held to.

## The problem this solves

Every layer so far reasons about **one** timeframe. That is a real limit: an H1
bull signal inside an H4 bear trend is a different proposition from the same H1
signal inside an H4 bull trend, and until now nothing in the engine could say so.
`DECISION_ENGINE.md` §11 has recorded that limitation since Phase 15.

## Alignment, and why it is the whole problem

An H4 bar is not knowable until its last M15 bar has closed. So the first job is
not "find the H4 trend" — it is **deciding which H4 bars exist yet**.

The rule this module implements, and the one the no-lookahead test pins:

> `Bar.time` is the bar's **open** time. A higher-timeframe bar is usable at
> lower-timeframe bar `i` only once it has **closed**, i.e. only when
> `htf.time + htf_step <= ltf.time[i] + ltf_step`.

That is why the alignment works in *close* times rather than open times. A naive
`htf.time < ltf.time` test would read the currently-forming H4 bar and hand the
low timeframe an hour of future information — the most likely way to build a
multi-timeframe look-ahead bug, and the one the test suite exists to catch.

The bar step is measured from each series' own timestamps rather than parsed out
of a timeframe string. `M15`, `H4`, `D1` and every broker's spelling of them are
too varied to parse reliably, and a mis-parsed timeframe would be a silent
misalignment. A series whose timestamps are missing or non-monotonic is
**reported**, not aligned: `MISSING_TIMESTAMPS` and `NON_MONOTONIC_TIME` are
diagnostics, and the bias in that case is `0` with a reason, because "no bias"
would be a claim the data cannot support.

## The bias is a veto input, not a signal

`HTFBias` is deliberately the smallest thing that can be true: a direction, the
proxy strength behind it, the HTF bar it came from, and the reason. It is `0`
unless the higher timeframe's `MarketState.strength` reaches `htf_min_strength` —
below that the HTF is a range, a transition or a weak read, and a low-timeframe
signal against it is not a conflict.

Where it *is* directional and the low-timeframe decision runs against it,
`apply_htf_veto()` withholds the decision as `WAIT` /
`AGAINST_HIGHER_TIMEFRAME`, with the bias recorded in the veto's detail. It
withholds rather than **inverting**: the engine does not know that an H1 long
against an H4 bear is a *short*. It knows the two disagree, and that is what it
says. `htf_opposition_veto=False` reports the same conflict without gating on it.

## What the bias is not

`MarketState.strength` is a **proxy share of score**, not a probability of
continuation, and `htf_min_strength` is a chosen threshold on it. Both are
`HEURISTIC` in `docs/architecture/CONCEPT_TAXONOMY.md` §4. "Bullish higher
timeframe" means "a documented set of geometric conditions on the HTF series
scored highest, and the winner's share was at least `htf_min_strength`".

## How the no-lookahead property is obtained

Not by filtering after the fact — by construction. The higher-timeframe analysis
is run **as of** the aligned bar with `last_closed=k`, the same "analyse as of a
bar" contract every detector in this engine already obeys. The pipeline therefore
never holds a full higher-timeframe result and reaches into it for a historical
bar, because it never holds one.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.decision.veto import VETO_AGAINST_HIGHER_TIMEFRAME, Veto
from albrooks.engine.analyzer import Analyzer
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.engine.state import AnalysisResult

# --------------------------------------------------------------------------
# Alignment diagnostics
# --------------------------------------------------------------------------

#: A bar carries no usable timestamp, so its step cannot be measured.
WARN_MISSING_TIMESTAMPS = "MISSING_TIMESTAMPS"
#: Timestamps do not strictly increase, so a bar cannot be located in time.
WARN_NON_MONOTONIC_TIME = "NON_MONOTONIC_TIME"
#: The observed step ratio disagrees with the one the caller supplied.
WARN_RATIO_MISMATCH = "TIMEFRAME_RATIO_MISMATCH"
#: The two series do not overlap, so no higher bar is ever usable.
WARN_NO_OVERLAP = "NO_TIME_OVERLAP"
#: The step ratio was not supplied.
WARN_NO_RATIO = "TIMEFRAME_RATIO_NOT_SUPPLIED"

#: How far the observed step ratio may differ from the supplied one before it is
#: reported. A ratio of 4 against an observed 3.99 is a rounding difference in the
#: data; 4 against 2 is a different timeframe and a real misalignment.
RATIO_TOLERANCE = 0.01

#: Reason recorded on a decision the higher timeframe contradicted.
REASON_AGAINST_HTF = "AGAINST_HIGHER_TIMEFRAME"


@dataclass(frozen=True, slots=True)
class Alignment:
    """The diagnostic record of how two series were lined up in time.

    Reported in full rather than reduced to a verdict, because "the bias is zero"
    and "the bias is zero *because the timestamps are missing*" are different
    statements and a caller needs to be able to tell them apart.
    """

    #: The ratio the caller supplied, in higher bars per lower bar.
    ratio: int = 0
    #: Step measured from the lower series' own timestamps.
    ltf_step: float = 0.0
    #: Step measured from the higher series' own timestamps.
    htf_step: float = 0.0
    #: `htf_step / ltf_step`, when both steps could be measured.
    observed_ratio: float = 0.0
    #: Newest higher-timeframe bar that had closed at the analysed low bar.
    htf_index: int = -1
    #: Diagnostics, empty when the alignment is clean.
    warnings: tuple[str, ...] = ()

    @property
    def is_usable(self) -> bool:
        """Whether an HTF bar could be located at all.

        False means the bias is reported as unaligned rather than as neutral: a
        bias of `0` derived from aligned data and a bias of `0` derived from
        missing timestamps are not the same statement.
        """
        return self.htf_index >= 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ratio": self.ratio,
            "ltf_step": self.ltf_step,
            "htf_step": self.htf_step,
            "observed_ratio": self.observed_ratio,
            "htf_index": self.htf_index,
            "is_usable": self.is_usable,
            "warnings": list(self.warnings),
        }


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------


def measure_step(series: BarSeries) -> tuple[float, bool]:
    """The modal positive gap between consecutive bar times, and whether it is
    measurable at all.

    The **mode** rather than the mean, because one session break or weekend gap
    would drag a mean away from the bar's own period, and a weekend gap used as
    the step would misalign every bar after it.

    A series with fewer than two bars, or with every timestamp identical (the
    `0.0` a `Bar.from_dict` gives a bar that carried no time), has no measurable
    step. That is reported rather than assumed away.
    """
    times = series.times
    gaps = [b - a for a, b in zip(times, times[1:]) if b > a]
    if not gaps:
        return 0.0, False
    counts: dict[float, int] = {}
    for gap in gaps:
        counts[gap] = counts.get(gap, 0) + 1
    # Ties break toward the *smaller* gap, so a series of duplicated bars
    # resolves to its own period rather than to an aggregate.
    return max(sorted(counts), key=lambda g: counts[g]), True


def _is_monotonic(series: BarSeries) -> bool:
    times = series.times
    return all(b > a for a, b in zip(times, times[1:]))


def htf_close_times(series: BarSeries, step: float) -> list[float]:
    """When each higher-timeframe bar closes, in the same order as `series`.

    `close = time + step`, because `Bar.time` is documented as the **open** time.
    Ascending, because `bisect_right` needs that — and `_is_monotonic` has already
    established it.
    """
    return [t + step for t in series.times]


def aligned_htf_index(
    ltf: BarSeries,
    htf: BarSeries,
    ltf_index: int,
    *,
    ratio: int = 0,
) -> tuple[int, Alignment]:
    """The newest higher-timeframe bar that had **closed** at `ltf_index`.

    Returns `(-1, alignment)` when no higher bar is usable, with the reason in
    `alignment.warnings`. The closed-bar rule is the whole point: the forming
    higher bar is never returned, so the low timeframe cannot see a higher
    timeframe's future.
    """
    warnings: list[str] = []
    ltf_step, ltf_ok = measure_step(ltf)
    htf_step, htf_ok = measure_step(htf)

    if not ltf_ok or not htf_ok:
        warnings.append(WARN_MISSING_TIMESTAMPS)
    if ltf_ok and not _is_monotonic(ltf):
        warnings.append(WARN_NON_MONOTONIC_TIME)
    if htf_ok and not _is_monotonic(htf):
        warnings.append(WARN_NON_MONOTONIC_TIME)
    if warnings:
        return -1, Alignment(
            ratio=ratio, ltf_step=ltf_step, htf_step=htf_step, warnings=tuple(warnings)
        )

    observed = htf_step / ltf_step
    if ratio <= 0:
        warnings.append(WARN_NO_RATIO)
    elif abs(observed - ratio) > RATIO_TOLERANCE * max(1.0, ratio):
        # Reported, and the alignment still proceeds on the *timestamps* rather
        # than on the ratio. A wrong ratio means the caller's model of their own
        # data is wrong, which is worth saying; it does not make the timestamps
        # wrong, and refusing to align would throw away a usable series.
        warnings.append(WARN_RATIO_MISMATCH)

    def unusable() -> Alignment:
        return Alignment(
            ratio=ratio,
            ltf_step=ltf_step,
            htf_step=htf_step,
            observed_ratio=observed,
            warnings=tuple(warnings),
        )

    if not 0 <= ltf_index < len(ltf):
        return -1, unusable()

    ltf_close = ltf[ltf_index].time + ltf_step
    position = bisect_right(htf_close_times(htf, htf_step), ltf_close) - 1
    if position < 0:
        warnings.append(WARN_NO_OVERLAP)
        return -1, unusable()
    return position, Alignment(
        ratio=ratio,
        ltf_step=ltf_step,
        htf_step=htf_step,
        observed_ratio=observed,
        htf_index=position,
        warnings=tuple(warnings),
    )


# --------------------------------------------------------------------------
# The bias
# --------------------------------------------------------------------------

#: A directional HTF read at or above `htf_min_strength`.
BIAS_ALIGNED = "HTF_ALIGNED"
#: No higher-timeframe bar had closed yet at this low bar.
BIAS_NOT_ALIGNED = "HTF_NOT_ALIGNED"
#: The higher series is too short, or too flat, to classify directionally.
BIAS_NOT_CLASSIFIED = "HTF_NOT_CLASSIFIED"
#: The timestamps could not be lined up, so no bias could be read at all.
BIAS_NOT_ALIGNED_IN_TIME = "HTF_NOT_ALIGNED_IN_TIME"


@dataclass(frozen=True, slots=True)
class HTFBias:
    """The higher-timeframe read, and everything needed to argue with it."""

    direction: int = 0
    #: `MarketState.strength`, the higher series' proxy share of score. **Not** a
    #: probability of continuation.
    strength: float = 0.0
    #: The higher timeframe's classified mode, or `UNKNOWN`.
    mode: str = "UNKNOWN"
    #: Which higher-timeframe bar the read came from, and which low bar asked.
    htf_index: int = -1
    htf_time: float = 0.0
    ltf_index: int = -1
    reason: str = BIAS_NOT_ALIGNED
    alignment: Alignment = field(default_factory=Alignment)

    @property
    def is_directional(self) -> bool:
        """Whether this is an actual directional read rather than an absence.

        `0` here means "the HTF gave no direction", which is a statement — and not
        the same statement as `reason == HTF_NOT_ALIGNED_IN_TIME`.
        """
        return self.direction != 0

    def opposes(self, direction: int) -> bool:
        """Is `direction` against this read?"""
        return self.is_directional and direction != 0 and self.direction != direction

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "strength": self.strength,
            "mode": self.mode,
            "htf_index": self.htf_index,
            "htf_time": self.htf_time,
            "ltf_index": self.ltf_index,
            "reason": self.reason,
            "is_directional": self.is_directional,
            "alignment": self.alignment.to_dict(),
        }


def htf_bias(
    htf: BarSeries,
    htf_result: AnalysisResult | None,
    alignment: Alignment,
    ltf_index: int,
    config: AnalyzerConfig,
) -> HTFBias:
    """Turn a higher-timeframe analysis into a bias, or into a reason for not
    having one.

    The "no bias" cases are kept apart on purpose:

    | `reason` | What it means |
    |---|---|
    | `HTF_ALIGNED` | a directional read at or above `htf_min_strength` |
    | `HTF_NOT_CLASSIFIED` | aligned, but the HTF proxy is too weak to lean |
    | `HTF_NOT_ALIGNED` | no higher bar had closed yet at this low bar |
    | `HTF_NOT_ALIGNED_IN_TIME` | the timestamps could not be lined up at all |

    Collapsing the last two would let a data problem read as a neutral market,
    which is the failure mode the `reason` / `unimplemented_layers` apparatus in
    this project exists to prevent.
    """
    if not alignment.is_usable:
        return HTFBias(
            ltf_index=ltf_index,
            reason=BIAS_NOT_ALIGNED_IN_TIME,
            alignment=alignment,
        )
    if htf_result is None:
        return HTFBias(ltf_index=ltf_index, reason=BIAS_NOT_ALIGNED, alignment=alignment)

    state = htf_result.market_state or {}
    mode = str(state.get("mode", "UNKNOWN"))
    try:
        strength = float(state.get("strength", 0.0) or 0.0)
    except (TypeError, ValueError):
        strength = 0.0
    direction = int(state.get("direction", 0) or 0)
    htf_time = htf[alignment.htf_index].time

    if not state.get("valid", False) or strength < config.htf_min_strength:
        return HTFBias(
            strength=strength,
            mode=mode,
            htf_index=alignment.htf_index,
            htf_time=htf_time,
            ltf_index=ltf_index,
            reason=BIAS_NOT_CLASSIFIED,
            alignment=alignment,
        )
    return HTFBias(
        direction=direction,
        strength=strength,
        mode=mode,
        htf_index=alignment.htf_index,
        htf_time=htf_time,
        ltf_index=ltf_index,
        reason=BIAS_ALIGNED,
        alignment=alignment,
    )


# --------------------------------------------------------------------------
# Applying it
# --------------------------------------------------------------------------


def apply_htf_veto(
    decision: dict[str, Any], bias: HTFBias, config: AnalyzerConfig
) -> dict[str, Any]:
    """Withhold a lower-timeframe decision that runs against a strong HTF read.

    **Withhold, not invert.** The engine knows the two disagree; it does not know
    that an H1 long against an H4 bear is a short, and turning the signal round
    would be a claim this project has not earned.

    An abstention is returned untouched. Overwriting a `WAIT` that already had a
    reason would replace a true statement with a weaker one, and the higher
    timeframe was not the reason for it.

    Operates on the serialised decision because that is what
    `AnalysisResult.decision` is; rebuilding a `Decision` to pass through one
    field would need a field list that could silently fall behind.
    """
    if not config.htf_opposition_veto:
        return decision
    if decision.get("action") not in ("BUY", "SELL"):
        return decision
    if not bias.opposes(int(decision.get("direction", 0) or 0)):
        return decision

    veto = Veto(
        code=VETO_AGAINST_HIGHER_TIMEFRAME,
        subject=str(decision.get("subject", "")),
        detail=(
            f"the lower-timeframe decision is {decision['action']} but the "
            f"higher timeframe reads {bias.mode} with proxy strength "
            f"{bias.strength:.4f}, at or above the htf_min_strength limit "
            f"{config.htf_min_strength:.4f}. The two disagree; the signal is "
            f"withheld, not reversed."
        ),
        blocking=True,
        config_key="htf_opposition_veto",
    )
    return {
        **decision,
        "action": "WAIT",
        "reason": REASON_AGAINST_HTF,
        "is_actionable": False,
        "explanation": list(decision.get("explanation", ()))
        + [
            f"the higher timeframe reads {bias.mode} with proxy strength "
            f"{bias.strength:.4f} from its bar {bias.htf_index}, against this "
            f"decision's direction, so it is withheld rather than reversed",
            "the higher-timeframe read is a documented proxy share of score, not "
            "a probability of continuation, and htf_min_strength is a chosen "
            "threshold on it",
        ],
        "vetoes": list(decision.get("vetoes", ())) + [veto.to_dict()],
        "considered": {
            **dict(decision.get("considered", {})),
            "htf_opposed": 1,
        },
    }


# --------------------------------------------------------------------------
# The pipeline
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MultiTimeframeResult:
    """Both analyses, the bias, and the alignment that produced it.

    `higher` is `None` when no higher-timeframe bar had closed at the analysed low
    bar, which is a different statement from "the higher timeframe was neutral" —
    the latter is `higher` present with `bias.reason == HTF_NOT_CLASSIFIED`.
    """

    lower: AnalysisResult
    higher: AnalysisResult | None = None
    bias: HTFBias = field(default_factory=HTFBias)
    #: The lower decision, after the higher-timeframe veto.
    decision: dict[str, Any] = field(default_factory=dict)
    symbol: str = "GENERIC"
    lower_timeframe: str = "UNKNOWN"
    higher_timeframe: str = "UNKNOWN"

    @property
    def alignment(self) -> Alignment:
        return self.bias.alignment

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "lower_timeframe": self.lower_timeframe,
            "higher_timeframe": self.higher_timeframe,
            "lower": self.lower.to_dict(),
            "higher": self.higher.to_dict() if self.higher is not None else None,
            "bias": self.bias.to_dict(),
            "decision": self.decision,
        }


def analyze_multi_timeframe(
    lower: Sequence[Bar | dict[str, Any]] | BarSeries,
    higher: Sequence[Bar | dict[str, Any]] | BarSeries,
    *,
    ratio: int = 0,
    config: AnalyzerConfig | None = None,
    symbol: str = "GENERIC",
    lower_timeframe: str = "UNKNOWN",
    higher_timeframe: str = "UNKNOWN",
    last_closed: int | None = None,
    analyzer: Analyzer | None = None,
) -> MultiTimeframeResult:
    """Analyse one timeframe, and hold its decision to the next one up.

    `ratio` is the number of lower bars in one higher bar — `4` for M15 under H1.
    It is **supplied, not inferred**, and cross-checked against the timestamps: a
    disagreement is reported as `TIMEFRAME_RATIO_MISMATCH` and the alignment
    proceeds on the timestamps anyway.

    `last_closed` is the low-timeframe analysis point, exactly as in
    `Analyzer.analyze()`. The higher-timeframe analysis is run **as of** the
    aligned bar, which is where the no-lookahead guarantee comes from: the
    pipeline never holds a full higher-timeframe result and reaches back into it.
    """
    cfg = config or AnalyzerConfig()
    engine = analyzer or Analyzer(cfg)
    ltf = lower if isinstance(lower, BarSeries) else BarSeries(lower)
    htf = higher if isinstance(higher, BarSeries) else BarSeries(higher)

    closed = (len(ltf) - 1) if last_closed is None else min(last_closed, len(ltf) - 1)
    lower_result = engine.analyze(
        ltf, symbol=symbol, timeframe=lower_timeframe, last_closed=closed
    )

    index, alignment = aligned_htf_index(ltf, htf, closed, ratio=ratio)
    higher_result = (
        engine.analyze(htf, symbol=symbol, timeframe=higher_timeframe, last_closed=index)
        if index >= 0
        else None
    )
    bias = htf_bias(htf, higher_result, alignment, closed, cfg)

    return MultiTimeframeResult(
        lower=lower_result,
        higher=higher_result,
        bias=bias,
        decision=apply_htf_veto(lower_result.decision, bias, cfg),
        symbol=symbol,
        lower_timeframe=lower_timeframe,
        higher_timeframe=higher_timeframe,
    )
