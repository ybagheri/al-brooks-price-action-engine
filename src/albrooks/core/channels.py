"""Price channels: two parallel boundaries that price has respected.

A channel is described by two lines that are parallel by construction. Both are
derived from **confirmed** swing extremes, so a channel is never published
before the swings that define it have themselves been confirmed.

For a bull channel, the upper line is drawn through the two most recent swing
highs and the lower line is the *parallel* line through the two most recent
swing lows, offset so that the channel is balanced. A bear channel mirrors this.

Classification: `PROXY`. A drawn channel is a visual judgement; a pair of
parallel lines through swing extremes is the measurable stand-in used here.

Limitations:
* Parallel construction forces symmetry. A real accelerating channel is
  not representable, and a decelerating one will be reported as broken early.
* Only two touchpoints per side are used, so a channel with three or more
  touches is still described by its most recent two.
* A channel is not support. A break is a measurement, not a signal.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.core.swings import SwingPoint, find_swings
from albrooks.engine.configuration import AnalyzerConfig

#: Minimum swing separation, in bars, for two touchpoints to define a line.
MIN_TOUCH_SEPARATION: int = 2


@dataclass(frozen=True, slots=True)
class PriceChannel:
    """A parallel channel defined by confirmed swing extremes."""

    direction: int = 0  # +1 bull channel, -1 bear channel
    slope: float = 0.0
    upper_price: float = 0.0  # upper boundary at the channel's last touchpoint
    lower_price: float = 0.0  # lower boundary at the channel's last touchpoint
    upper_slope: float = 0.0
    lower_slope: float = 0.0
    width: float = 0.0
    parallel: bool = True
    first_touch_bar: int = -1
    last_touch_bar: int = -1
    confirmed_bar_index: int = -1
    is_broken: bool = False
    breakout_direction: int = 0
    breakout_bar: int = -1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_bull(self) -> bool:
        return self.direction == 1

    @property
    def is_bear(self) -> bool:
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


def _confirmed(swings: Sequence[SwingPoint | dict[str, Any]], last_closed: int) -> list[dict]:
    out = []
    for s in swings:
        if isinstance(s, SwingPoint):
            bar, price, direction, conf = s.bar_index, s.price, s.direction, s.confirmed_bar_index
        else:
            bar = int(s.get("bar", s.get("bar_index", 0)))
            price = float(s.get("price", 0.0))
            direction = int(s.get("dir", s.get("direction", 0)))
            conf = int(s.get("confirmed_bar", s.get("confirmed_bar_index", 0)))
        if bar > last_closed or (conf >= 0 and conf > last_closed):
            continue
        out.append({"bar": bar, "price": price, "dir": direction, "conf": conf})
    return out


def _boundary_at(
    p1: dict[str, Any],
    p2: dict[str, Any],
    at_bar: int,
) -> float:
    """Price of the line through p1 -> p2, evaluated at `at_bar`."""
    span = p2["bar"] - p1["bar"]
    if span == 0:
        return p2["price"]
    slope = (p2["price"] - p1["price"]) / span
    return p2["price"] + slope * (at_bar - p2["bar"])


def detect_channel(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    last_closed: int,
    k: int = 3,
    atr: float = 0.0,
    min_width_atr: float = 0.0,
    max_parallel_deviation_atr: float = 0.5,
    config: AnalyzerConfig | None = None,
) -> PriceChannel:
    """Detect a parallel channel from the two most recent swings per side.

    Requires at least two confirmed swing highs and two confirmed swing lows,
    separated by at least `MIN_TOUCH_SEPARATION` bars. The channel direction is
    taken from the slope of the highs; the lower line is drawn parallel to it.
    """
    cfg = config or AnalyzerConfig()
    if last_closed < 0 or last_closed >= len(bars):
        return PriceChannel()

    swings = _confirmed(find_swings(bars, last_closed_idx=last_closed, k=k), last_closed)
    highs = [s for s in swings if s["dir"] == 1]
    lows = [s for s in swings if s["dir"] == -1]
    if len(highs) < 2 or len(lows) < 2:
        return PriceChannel()

    h1, h2 = highs[-2], highs[-1]
    l1, l2 = lows[-2], lows[-1]

    upper_slope = (h2["price"] - h1["price"]) / (h2["bar"] - h1["bar"])
    lower_slope = (l2["price"] - l1["price"]) / (l2["bar"] - l1["bar"])

    direction = 1 if upper_slope > 0 else -1
    if direction == 1 and lower_slope <= 0:
        return PriceChannel()  # highs rising but lows falling: not a channel
    if direction == -1 and lower_slope >= 0:
        return PriceChannel()

    if h2["bar"] - h1["bar"] < MIN_TOUCH_SEPARATION:
        return PriceChannel()
    if l2["bar"] - l1["bar"] < MIN_TOUCH_SEPARATION:
        return PriceChannel()

    ref_bar = max(h2["bar"], l2["bar"])
    upper = _boundary_at(h1, h2, ref_bar)
    lower = _boundary_at(l1, l2, ref_bar)
    width = upper - lower
    if width <= 0:
        return PriceChannel()
    if atr > 0:
        if width < min_width_atr * atr:
            return PriceChannel()
        # Parallelism: the two slopes should agree within a tolerance.
        scale = max(abs(upper_slope), abs(lower_slope), 1e-9)
        if abs(upper_slope - lower_slope) > max_parallel_deviation_atr * scale:
            return PriceChannel()

    channel = PriceChannel(
        direction=direction,
        slope=upper_slope,
        upper_price=upper,
        lower_price=lower,
        upper_slope=upper_slope,
        lower_slope=lower_slope,
        width=width,
        parallel=True,
        first_touch_bar=min(h1["bar"], l1["bar"]),
        last_touch_bar=ref_bar,
        confirmed_bar_index=max(h2["conf"], l2["conf"]),
    )
    return _apply_breakout(bars, channel, last_closed, atr, cfg)


def _apply_breakout(
    bars: Sequence[Bar | dict[str, Any]],
    channel: PriceChannel,
    last_closed: int,
    atr: float,
    cfg: AnalyzerConfig,
) -> PriceChannel:
    """Mark the first bar after the channel that closed outside its boundary."""
    tol = cfg.double_tol_atr * atr if atr > 0 else 0.0
    start = channel.last_touch_bar + 1
    for i in range(start, min(last_closed, len(bars) - 1) + 1):
        _, h, low_val, c = _get_ohlc(bars[i])
        upper = channel.upper_price + channel.upper_slope * (i - channel.last_touch_bar)
        lower = channel.lower_price + channel.lower_slope * (i - channel.last_touch_bar)
        if c > upper + tol:
            return replace(channel, is_broken=True, breakout_direction=1, breakout_bar=i)
        if c < lower - tol:
            return replace(channel, is_broken=True, breakout_direction=-1, breakout_bar=i)
    return channel


