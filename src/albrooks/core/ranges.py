"""Trading ranges, breakout attempts, and failed breakouts.

A **trading range** is a bounded region whose edges price has repeatedly
rejected. Three measurements define it:

* the edges themselves, taken as the window high and low,
* how many times each edge was tested, and
* whether price has since closed decisively outside.

A **breakout attempt** is a bar that pushed beyond an edge. A **failed
breakout** is an attempt that was reclaimed -- price closed back inside within
`failed_bo_bars` bars. The distinction matters: the first is a fact about one
bar, the second is a fact about a short sequence.

Classification: edges and touch counts are `OBJECTIVE`; the range is a `PROXY`;
the notion of "decisive" beyond an edge is a `HEURISTIC` tolerance.

Limitations:
* The edges move as the window advances, so a range detected at bar *i* may
  differ from the same range detected at bar *i+1*. That is inherent to a
  window-based definition and is not repainting, but callers that need a frozen
  range should anchor it explicitly.
* Touch counting is tolerance-sensitive and depends on the chosen window.
* A failed breakout is not a reversal. It says the break did not hold, nothing
  about what follows.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.engine.configuration import AnalyzerConfig

#: Default number of bars scanned when looking for range edges.
DEFAULT_RANGE_LOOKBACK: int = 20
#: Tests required on each edge before a region is called a range.
DEFAULT_MIN_TOUCHES: int = 2


@dataclass(frozen=True, slots=True)
class TradingRange:
    """A bounded region with repeated edge tests."""

    high: float = 0.0
    low: float = 0.0
    height: float = 0.0
    high_bar: int = -1
    low_bar: int = -1
    touches_high: int = 0
    touches_low: int = 0
    window_start: int = -1
    window_end: int = -1
    is_broken: bool = False
    breakout_direction: int = 0
    breakout_bar: int = -1
    reclaim_bar: int = -1  # first close back inside after a break

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_bull_break(self) -> bool:
        return self.breakout_direction == 1

    @property
    def is_bear_break(self) -> bool:
        return self.breakout_direction == -1

    @property
    def is_failed(self) -> bool:
        """A break that was reclaimed inside the range."""
        return self.is_broken and self.reclaim_bar >= 0

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high


@dataclass(frozen=True, slots=True)
class BreakoutAttempt:
    """A single bar that pushed beyond a structural level."""

    bar_index: int = -1
    direction: int = 0  # +1 up, -1 down
    level: float = 0.0
    excursion: float = 0.0  # how far beyond the level the close reached
    reclaimed: bool = False
    reclaim_bar: int = -1

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


def count_edge_touches(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    start: int,
    end: int,
    level: float,
    is_upper: bool,
    tolerance: float,
) -> int:
    """Count bars in `[start, end]` that reached `level` within `tolerance`.

    A bar touches an edge when its extreme reached the level but it did not
    close beyond it by more than the tolerance.
    """
    n = 0
    for i in range(max(0, start), min(end, len(bars) - 1) + 1):
        _, h, low_val, c = _get_ohlc(bars[i])
        if is_upper:
            if h >= level - tolerance and c <= level + tolerance:
                n += 1
        else:
            if low_val <= level + tolerance and c >= level - tolerance:
                n += 1
    return n


def detect_trading_range(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    last_closed: int,
    atr: float,
    lookback: int = DEFAULT_RANGE_LOOKBACK,
    min_touches: int = DEFAULT_MIN_TOUCHES,
    min_height_atr: float = 0.0,
    tol_atr: float = 0.15,
    hold_bars: int = 1,
    config: AnalyzerConfig | None = None,
) -> TradingRange:
    """Detect a trading range ending at `last_closed`.

    A range is reported when both edges have been tested at least `min_touches`
    times inside the window. Bars are read only up to `last_closed`, so the
    result for a given index is stable regardless of later bars.

    `hold_bars` excludes the newest N bars from the edge calculation. This is
    necessary, not cosmetic: a range defined by the maximum high of a window
    that *includes* the current bar can never be broken by that bar, because the
    break would simply redefine the edge. Holding the last bars back leaves
    room for a break to be observed against edges that were set earlier.
    """
    cfg = config or AnalyzerConfig()
    empty = TradingRange()
    if last_closed < 0 or last_closed >= len(bars) or atr <= 0:
        return empty
    window_end = last_closed - max(0, hold_bars)
    window = max(2, lookback)
    start = max(0, window_end - window + 1)
    if window_end - start + 1 < 3:
        return empty

    highs = [(i, _get_ohlc(bars[i])[1]) for i in range(start, window_end + 1)]
    lows = [(i, _get_ohlc(bars[i])[2]) for i in range(start, window_end + 1)]
    high_bar, high = max(highs, key=lambda t: t[1])
    low_bar, low = min(lows, key=lambda t: t[1])
    height = high - low
    if height <= 0:
        return empty
    if height < min_height_atr * atr:
        return empty

    tol = tol_atr * atr
    touches_high = count_edge_touches(bars, start, window_end, high, True, tol)
    touches_low = count_edge_touches(bars, start, window_end, low, False, tol)
    if touches_high < min_touches or touches_low < min_touches:
        return empty

    rng = TradingRange(
        high=high,
        low=low,
        height=height,
        high_bar=high_bar,
        low_bar=low_bar,
        touches_high=touches_high,
        touches_low=touches_low,
        window_start=start,
        window_end=window_end,
    )
    return _apply_break_state(bars, rng, last_closed, tol, cfg)


def _apply_break_state(
    bars: Sequence[Bar | dict[str, Any]],
    rng: TradingRange,
    last_closed: int,
    tol: float,
    cfg: AnalyzerConfig,
) -> TradingRange:
    """Find the first decisive break after the window, and any reclaim."""
    direction = 0
    break_bar = -1
    for i in range(rng.window_end + 1, min(last_closed, len(bars) - 1) + 1):
        _, _, _, c = _get_ohlc(bars[i])
        if c > rng.high + tol:
            direction, break_bar = 1, i
            break
        if c < rng.low - tol:
            direction, break_bar = -1, i
            break
    if break_bar < 0:
        return rng

    reclaim_bar = -1
    window = max(1, cfg.failed_bo_bars)
    for i in range(break_bar + 1, min(last_closed, break_bar + window) + 1):
        _, _, _, c = _get_ohlc(bars[i])
        if rng.contains(c):
            reclaim_bar = i
            break

    return replace(
        rng,
        is_broken=True,
        breakout_direction=direction,
        breakout_bar=break_bar,
        reclaim_bar=reclaim_bar,
    )


def detect_breakout_attempt(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    level: float,
    direction: int,
    tol_atr: float = 0.15,
    atr: float = 0.0,
) -> BreakoutAttempt:
    """Did bar `idx` push beyond `level`, and was it later reclaimed?

    `direction` is the side being broken: `+1` treats `level` as resistance,
    `-1` as support. `excursion` is how far the close went beyond the level.
    """
    if idx < 0 or idx > last_closed or idx >= len(bars) or direction not in (1, -1):
        return BreakoutAttempt(bar_index=idx, direction=direction, level=level)
    tol = tol_atr * atr if atr > 0 else 0.0
    _, _, _, c = _get_ohlc(bars[idx])
    broke = c > level + tol if direction > 0 else c < level - tol
    if not broke:
        return BreakoutAttempt(bar_index=idx, direction=direction, level=level)

    excursion = (c - level) if direction > 0 else (level - c)
    reclaim_bar = -1
    for i in range(idx + 1, min(last_closed, len(bars) - 1) + 1):
        _, _, _, cc = _get_ohlc(bars[i])
        if direction > 0 and cc <= level + tol:
            reclaim_bar = i
            break
        if direction < 0 and cc >= level - tol:
            reclaim_bar = i
            break

    return BreakoutAttempt(
        bar_index=idx,
        direction=direction,
        level=level,
        excursion=excursion,
        reclaimed=reclaim_bar >= 0,
        reclaim_bar=reclaim_bar,
    )
