"""Major and Minor Trend Reversal: detection, quality, and decision, separated.

The specification makes this separation **mandatory**, and it is the right call:
conflating the three produces a single number that is impossible to reason
about. "Reversal detected: 75/100" hides whether anything was detected at all.

So this module exposes three layers:

| Layer | Function | Answers |
|---|---|---|
| Detection | `detect_reversal` | Is the structure present? Which legs? |
| Quality | `assess_reversal_quality` | How many of its legs are satisfied, and which? |
| Decision | *Phase 15* | Should anyone act on it? |

`detect_reversal` never computes a score. `assess_reversal_quality` never
searches for a pattern. `analyze_reversal` is retained as a convenience wrapper
that runs both, for backward compatibility.

## The four legs

A Major Trend Reversal is a four-phase sequence:

1. `EMA_BREAK` -- price breaks decisively through the 20-EMA against the
   prevailing trend.
2. `RETEST` -- price returns to the EMA and holds on the far side.
3. `BREAKOUT_FOLLOW` -- the swing structure breaks *with* the reversal.
4. `PRESSURE` -- consecutive pushes in the reversal direction, i.e. the old
   trend direction is being overwhelmed.

A Minor Trend Reversal satisfies some but not all of them.

Classification: the leg detection is `ALGORITHMIC`; the weights and the
major/minor threshold are `HEURISTIC`; the whole reading of a four-phase
sequence as a reversal is a `PROXY`.

## What this does NOT claim

- The `score` is **not** a probability, a win rate, or a confidence interval.
  It is a transparent count: how many of the four legs are satisfied. A score of
  100 means four of four, not "certain".
- A `MAJOR` verdict is **not** more likely to work than a `MINOR` one. That
  ordering is a hypothesis for out-of-sample testing.
- Whether to act is a **decision**, and lives in Phase 15. Nothing here decides.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.core.structures import push_count_back
from albrooks.core.swings import SwingPoint
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.setups.breakout import analyze_breakout

#: Pushes required for the pressure leg.
MIN_PRESSURE_PUSHES: int = 5
#: Bars searched back for the EMA cross.
CROSS_LOOKBACK: int = 10
#: ATR tolerance for the EMA side test.
EMA_TOL_ATR: float = 0.25
#: Points awarded per satisfied leg.
POINTS_PER_LEG: int = 25
#: Legs required for a MAJOR verdict.
MAJOR_LEG_COUNT: int = 4

# Stable evidence codes, consumed by the Phase 13 evidence model.
LEG_EMA_BREAK = "EMA_BREAK"
LEG_RETEST = "EMA_RETEST_HELD"
LEG_BREAKOUT_FOLLOW = "SWING_BREAKOUT_WITH_REVERSAL"
LEG_PRESSURE = "REVERSAL_PRESSURE"


@dataclass(frozen=True, slots=True)
class ReversalLegs:
    """The structural facts of a reversal. No score, no judgement."""

    direction: int = 0  # +1 bull reversal, -1 bear reversal
    ema_break: bool = False
    retest: bool = False
    bo_follow: bool = False
    pressure_ok: bool = False
    pressure_count: int = 0
    cross_bar: int = -1

    @property
    def leg_count(self) -> int:
        return sum([self.ema_break, self.retest, self.bo_follow, self.pressure_ok])

    @property
    def is_present(self) -> bool:
        """Any leg at all is enough to say a reversal structure exists."""
        return self.leg_count >= 1

    def satisfied_legs(self) -> list[str]:
        codes = []
        if self.ema_break:
            codes.append(LEG_EMA_BREAK)
        if self.retest:
            codes.append(LEG_RETEST)
        if self.bo_follow:
            codes.append(LEG_BREAKOUT_FOLLOW)
        if self.pressure_ok:
            codes.append(LEG_PRESSURE)
        return codes

    def missing_legs(self) -> list[str]:
        present = set(self.satisfied_legs())
        return [c for c in (LEG_EMA_BREAK, LEG_RETEST, LEG_BREAKOUT_FOLLOW, LEG_PRESSURE)
                if c not in present]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReversalQuality:
    """Quality assessment of a detected structure. Never searches for one."""

    verdict: str = "NONE"  # MAJOR, MINOR, NONE
    score: int = 0
    max_score: int = 100
    leg_count: int = 0
    satisfied: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    direction: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_major(self) -> bool:
        return self.verdict == "MAJOR"

    @property
    def is_minor(self) -> bool:
        return self.verdict == "MINOR"


@dataclass(frozen=True, slots=True)
class ReversalResult:
    """Combined detection + quality. Retained for backward compatibility."""

    found: bool = False
    verdict: str = "NONE"  # MAJOR, MINOR, NONE
    direction: int = 0
    ema_break: bool = False
    retest: bool = False
    bo_follow: bool = False
    pressure_ok: bool = False
    pressure_count: int = 0
    score: int = 0
    cross_bar: int = -1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get_ohlc(b: Bar | dict[str, Any]) -> tuple[float, float, float, float]:
    if isinstance(b, Bar):
        return b.open, b.high, b.low, b.close
    return (
        float(b.get("o", b.get("open", 0.0))),
        float(b.get("h", b.get("high", 0.0))),
        float(b.get("l", b.get("low", 0.0))),
        float(b.get("c", b.get("close", 0.0))),
    )


def _ema20_tail(bars: Sequence[Bar | dict[str, Any]], idx: int) -> dict[int, float]:
    """EMA20 at each index up to `idx`, computed forward from the first close."""
    e = _get_ohlc(bars[0])[3]
    k = 2.0 / 21.0
    tail: dict[int, float] = {}
    for i in range(1, idx + 1):
        c = _get_ohlc(bars[i])[3]
        e = c * k + e * (1.0 - k)
        tail[i] = e
    return tail


def _side(close: float, ema: float, tol: float) -> int:
    if close > ema + tol:
        return 1
    if close < ema - tol:
        return -1
    return 0


def detect_reversal(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    swings: Sequence[SwingPoint | dict[str, Any]] = (),
    reversal_direction: int = 1,
    config: AnalyzerConfig | None = None,
) -> ReversalLegs:
    """Detect the reversal structure. Returns the legs; computes no score."""
    if reversal_direction not in (1, -1):
        return ReversalLegs(direction=reversal_direction)
    if idx < 0 or idx > last_closed or idx >= len(bars) or atr <= 0:
        return ReversalLegs(direction=reversal_direction)
    if idx + 1 < CROSS_LOOKBACK + 2:
        return ReversalLegs(direction=reversal_direction)

    tol = EMA_TOL_ATR * atr
    ema = _ema20_tail(bars, idx)
    if _side(_get_ohlc(bars[idx])[3], ema[idx], tol) != reversal_direction:
        return ReversalLegs(direction=reversal_direction)

    # Leg 1: find where price crossed to the reversal side of the EMA.
    cross_bar = -1
    for j in range(idx - 1, max(-1, idx - CROSS_LOOKBACK), -1):
        if _side(_get_ohlc(bars[j])[3], ema[j], tol) == -reversal_direction:
            cross_bar = j
            break
    if cross_bar < 0:
        return ReversalLegs(direction=reversal_direction)
    ema_break = True

    # Leg 2: price comes back to the EMA and holds on the reversal side.
    retest = False
    for j in range(cross_bar + 1, idx + 1):
        e = ema[j]
        _, h, low_val, c = _get_ohlc(bars[j])
        if reversal_direction > 0 and low_val <= e + tol and c > e - tol:
            retest = True
            break
        if reversal_direction < 0 and h >= e - tol and c < e + tol:
            retest = True
            break

    # Leg 3: the swing structure breaks with the reversal.
    bo = analyze_breakout(bars, idx, last_closed, atr, swings, config=config)
    bo_follow = bool(bo.found and bo.direction == reversal_direction and bo.outcome == "FOLLOW")

    # Leg 4: consecutive pushes overwhelming the old trend.
    pressure_count = push_count_back(bars, idx, last_closed, reversal_direction)
    pressure_ok = pressure_count >= MIN_PRESSURE_PUSHES

    return ReversalLegs(
        direction=reversal_direction,
        ema_break=ema_break,
        retest=retest,
        bo_follow=bo_follow,
        pressure_ok=pressure_ok,
        pressure_count=pressure_count,
        cross_bar=cross_bar,
    )


def assess_reversal_quality(legs: ReversalLegs) -> ReversalQuality:
    """Score an already-detected structure. Never searches for one."""
    n = legs.leg_count
    return ReversalQuality(
        verdict="MAJOR" if n >= MAJOR_LEG_COUNT else ("MINOR" if n >= 1 else "NONE"),
        score=POINTS_PER_LEG * n,
        leg_count=n,
        satisfied=legs.satisfied_legs(),
        missing=legs.missing_legs(),
        direction=legs.direction,
    )


def analyze_reversal(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    swings: Sequence[SwingPoint | dict[str, Any]] = (),
    reversal_direction: int = 1,
    config: AnalyzerConfig | None = None,
) -> ReversalResult:
    """Detect then assess. Convenience wrapper retained for compatibility.

    Equivalent to `analyze_reversal` in the pre-refactor implementation. New
    callers should use `detect_reversal` and `assess_reversal_quality` so that
    presence and quality are never confused.
    """
    cfg = config or AnalyzerConfig()
    legs = detect_reversal(
        bars, idx, last_closed, atr, swings, reversal_direction, config=cfg
    )
    quality = assess_reversal_quality(legs)
    return ReversalResult(
        found=quality.verdict != "NONE",
        verdict=quality.verdict,
        direction=reversal_direction,
        ema_break=legs.ema_break,
        retest=legs.retest,
        bo_follow=legs.bo_follow,
        pressure_ok=legs.pressure_ok,
        pressure_count=legs.pressure_count,
        score=quality.score,
        cross_bar=legs.cross_bar,
    )
