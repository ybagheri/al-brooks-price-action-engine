"""Wedge geometry and range contraction.

A wedge is a run of consecutive pushes in one direction whose bar ranges shrink
as it goes -- the move is losing energy. Two measurable properties:

$$\\text{shrinking}(i) \\equiv \\text{range}(i) \\leq \\text{range}(i-1) \\times 1.05$$

$$\\text{tightening}(i) \\equiv \\text{range}(i) < \\text{median}(\\text{range}[i-n, i))$$

A wedge is reported when a directional run of at least three pushes is either
shrinking throughout, or is four or more pushes long (a long enough run is
treated as a wedge regardless of range behaviour).

Classification: `PROXY`. A wedge is a drawn shape on a chart; shrinking ranges
and a push run are measurable stand-ins for it.

Limitations:
* Shrinking ranges are common in any decelerating move, including healthy
  pullbacks. A wedge here is not a reversal signal.
* The 1.05 tolerance and the 3/4 push thresholds are chosen values.
* These functions were moved here from `core/structures.py`. That module
  re-exports them, so no detection logic is duplicated.
"""

from __future__ import annotations

from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.price_action.pressure import push_count_back

#: Tolerance allowing a small range increase before a shrink sequence breaks.
SHRINK_TOLERANCE: float = 1.05
#: Minimum pushes before a wedge may be reported.
MIN_WEDGE_PUSHES: int = 3
#: Push count at or above which a run is a wedge regardless of range behaviour.
CERTAIN_WEDGE_PUSHES: int = 4
#: Bars used for the median-range comparison in `is_tightening`.
TIGHTENING_WINDOW: int = 4


def _get_ohlc(b: Bar | dict[str, Any]) -> tuple[float, float, float, float]:
    if isinstance(b, Bar):
        return b.open, b.high, b.low, b.close
    return (
        float(b.get("o", b.get("open", 0.0))),
        float(b.get("h", b.get("high", 0.0))),
        float(b.get("l", b.get("low", 0.0))),
        float(b.get("c", b.get("close", 0.0))),
    )


def _range(b: Bar | dict[str, Any]) -> float:
    _, h, low_val, _ = _get_ohlc(b)
    rg = h - low_val
    return rg if rg > 0.0 else 1e-9


def is_shrinking(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    count: int,
    tolerance: float = SHRINK_TOLERANCE,
) -> bool:
    """True when the last `count` bars each had a range no larger than the one before."""
    if idx < 1 or idx >= len(bars) or count < 2:
        return False
    return all(
        _range(bars[i]) <= _range(bars[i - 1]) * tolerance
        for i in range(idx, max(0, idx - count + 1), -1)
        if i - 1 >= 0
    )


def is_tightening(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    window: int = TIGHTENING_WINDOW,
) -> bool:
    """True when the newest bar's range is below the median of the prior `window`."""
    if idx < window or idx >= len(bars) or window < 1:
        return False
    ranges = sorted(_range(bars[i]) for i in range(idx - window, idx))
    med = (ranges[1] + ranges[2]) * 0.5
    return _range(bars[idx]) < med


def detect_wedge(
    bars: Sequence[Bar | dict[str, Any]],
    idx: int,
    last_closed: int,
    direction: int,
) -> bool:
    """Detect a decelerating directional run ending at `idx`."""
    if idx - 2 < 0 or idx > last_closed or idx >= len(bars):
        return False
    if direction not in (1, -1):
        return False
    n = push_count_back(bars, idx, last_closed, direction)
    if n < MIN_WEDGE_PUSHES:
        return False
    shrinking = is_shrinking(bars, idx, n)
    return bool(shrinking or n >= CERTAIN_WEDGE_PUSHES)
