"""Structural pivot points: swing locations weighted by significance.

Where `swings.py` answers "where are the alternating extremes", this module
answers "which of those extremes actually mattered". A pivot is a swing that
held: price returned to it more than once, or dominated a wide window of bars.

Pivots are deliberately built **on top of** `find_swings` rather than
reimplementing fractal detection, so there is exactly one authoritative swing
algorithm in the project.

Classification (see docs/architecture/CONCEPT_TAXONOMY.md):
  - pivot location          -> ALGORITHMIC (inherited from the swing definition)
  - touch counting          -> OBJECTIVE (a count of bars meeting a level)
  - major/minor significance -> HEURISTIC (window sizes are chosen values)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.core.swings import SwingPoint, find_swings

# Fraction of the touch tolerance at which a revisit counts as a test.
DEFAULT_TOUCH_ATR: float = 0.25
# How many bars past the pivot may be searched for revisits.
DEFAULT_TOUCH_WINDOW: int = 50


@dataclass(frozen=True, slots=True)
class PivotPoint:
    """A swing extreme annotated with how significant it proved to be.

    `strength` is the number of bars whose extreme failed to exceed the pivot
    inside its dominance window. `touches` counts later bars that came back
    within `tolerance` of the level without breaking it.
    """

    bar_index: int
    price: float
    direction: int  # +1 swing/pivot high, -1 swing/pivot low
    confirmed_bar_index: int
    strength: int = 0
    touches: int = 0
    is_major: bool = False
    tolerance: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_high(self) -> bool:
        return self.direction == 1

    @property
    def is_low(self) -> bool:
        return self.direction == -1


def _get_ohlc(b: Bar | dict[str, Any]) -> tuple[float, float, float, float]:
    if isinstance(b, Bar):
        return b.open, b.high, b.low, b.close
    return (
        float(b.get("o", b.get("open", 0.0))),
        float(b.get("h", b.get("high", 0.0))),
        float(b.get("l", b.get("low", 0.0))),
        float(b.get("c", b.get("close", 0.0))),
    )


def _pivot_fields(p: SwingPoint | PivotPoint | dict[str, Any]) -> tuple[int, float, int]:
    """Normalize a pivot-like input to (bar_index, price, direction)."""
    if isinstance(p, PivotPoint):
        return p.bar_index, p.price, p.direction
    if isinstance(p, SwingPoint):
        return p.bar_index, p.price, p.direction
    return (
        int(p.get("bar_index", p.get("bar", 0))),
        float(p.get("price", 0.0)),
        int(p.get("direction", p.get("dir", 0))),
    )


def measure_strength(
    bars: Sequence[Bar | dict[str, Any]],
    pivot: SwingPoint | PivotPoint | dict[str, Any],
    atr: float,
    last_closed: int,
    window: int = 20,
) -> int:
    """Count bars inside the pivot's dominance window that failed to break it.

    Starts at 1 so a pivot with no competitors still has non-zero strength.
    Bars beyond `last_closed` are never read, so the result cannot repaint.
    """
    if atr <= 0 or window < 1:
        return 1
    bar_index, price, direction = _pivot_fields(pivot)
    upper = min(last_closed, len(bars) - 1)
    lo = max(0, bar_index - window)
    hi = min(upper, bar_index + window)
    if hi < lo:
        return 1

    n = 1
    for i in range(lo, hi + 1):
        if i == bar_index:
            continue
        _, h, low_val, _ = _get_ohlc(bars[i])
        if direction == 1:
            broke = h > price
        elif direction == -1:
            broke = low_val < price
        else:
            broke = False
        if not broke:
            n += 1
    return max(1, n)


def count_touches(
    bars: Sequence[Bar | dict[str, Any]],
    pivot: SwingPoint | PivotPoint | dict[str, Any],
    atr: float,
    last_closed: int,
    tolerance_atr: float = DEFAULT_TOUCH_ATR,
    window: int = DEFAULT_TOUCH_WINDOW,
) -> int:
    """Count later bars that retested the pivot level without breaking it.

    A bar counts as a touch when it reached within `tolerance_atr * ATR` of the
    level but did not close decisively beyond it. Only bars after the pivot's
    own bar are considered, and only up to `last_closed`.
    """
    if atr <= 0:
        return 0
    bar_index, price, direction = _pivot_fields(pivot)
    tol = tolerance_atr * atr
    upper = min(last_closed, len(bars) - 1)
    start = bar_index + 1
    end = min(upper, bar_index + window)
    if end < start:
        return 0

    n = 0
    for i in range(start, end + 1):
        _, h, low_val, c = _get_ohlc(bars[i])
        if direction == 1:
            # Tested the high from below, and did not close above it.
            if h >= price - tol and c <= price + tol:
                n += 1
        elif direction == -1:
            if low_val <= price + tol and c >= price - tol:
                n += 1
    return n


def find_pivots(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    last_closed: int | None = None,
    k: int = 3,
    atr: float = 0.0,
    strength_window: int = 20,
    touch_window: int = DEFAULT_TOUCH_WINDOW,
    tolerance_atr: float = DEFAULT_TOUCH_ATR,
    major_touches: int = 2,
) -> list[PivotPoint]:
    """Return confirmed swings enriched with significance measures.

    A pivot is marked `is_major` when it was tested at least `major_touches`
    times, which is the standard reading of "a level the market respected".
    With `atr <= 0` the strength and touch machinery is skipped and every
    confirmed swing is returned with `strength=1, touches=0`.
    """
    swings = find_swings(bars, last_closed_idx=last_closed, k=k)
    n = len(bars)
    if n == 0:
        return []
    upper = n - 1 if last_closed is None else min(last_closed, n - 1)

    pivots: list[PivotPoint] = []
    for s in swings:
        if atr > 0:
            strength = measure_strength(bars, s, atr, upper, window=strength_window)
            touches = count_touches(
                bars,
                s,
                atr,
                upper,
                tolerance_atr=tolerance_atr,
                window=touch_window,
            )
        else:
            strength, touches = 1, 0
        pivots.append(
            PivotPoint(
                bar_index=s.bar_index,
                price=s.price,
                direction=s.direction,
                confirmed_bar_index=s.confirmed_bar_index,
                strength=strength,
                touches=touches,
                is_major=touches >= max(1, major_touches),
                tolerance=tolerance_atr * atr,
            )
        )
    return pivots


def find_major_pivots(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    last_closed: int | None = None,
    k: int = 3,
    atr: float = 0.0,
    major_touches: int = 2,
    **kwargs: Any,
) -> list[PivotPoint]:
    """Only those pivots that proved significant."""
    return [
        p
        for p in find_pivots(
            bars,
            last_closed=last_closed,
            k=k,
            atr=atr,
            major_touches=major_touches,
            **kwargs,
        )
        if p.is_major
    ]
