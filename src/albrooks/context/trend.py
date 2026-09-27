"""Trend measurement: EMA slope and directional pressure.

Two independent, objective inputs feed the trend proxy:

* **Slope** -- the gap between a 20- and 50-period EMA, normalised by ATR. A
  positive gap means the fast average sits above the slow one, i.e. recent
  prices are elevated relative to the longer run.
* **Pressure** -- over a lookback window, the excess count of strong bull bars
  over strong bear bars, normalised. A stand-in for cumulative buying or
  selling pressure.

Both are `OBJECTIVE` measurements. Whether they constitute a "trend" is a
`PROXY` judgement, and that judgement is made by `market_state.py`.

`calculate_trend_gap` is re-exported from `market_state` for compatibility.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from albrooks.context.trading_range import clamp01, clamp11
from albrooks.core.bars import Bar, BarSeries
from albrooks.engine.configuration import AnalyzerConfig

# Minimum bars before the EMA pair is meaningful.
MIN_EMA_BARS: int = 50
# ATR multiple by which the EMA gap is divided before clamping to -1..1.
SLOPE_ATR_DIVISOR: float = 2.0


@dataclass(frozen=True, slots=True)
class TrendMetrics:
    """Objective trend inputs, all normalised to bounded ranges."""

    gap: float = 0.0        # raw EMA20 - EMA50, in price
    slope: float = 0.0      # -1..1, gap normalised by ATR
    pressure: float = 0.0   # -1..1, net strong bars over the lookback
    bull_slope: float = 0.0  # 0..1
    bear_slope: float = 0.0  # 0..1
    bull_pressure: float = 0.0  # 0..1
    bear_pressure: float = 0.0  # 0..1
    valid: bool = False

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


def calculate_trend_gap(
    bars: Sequence[Bar | dict[str, Any]],
    idx: int,
) -> float:
    """EMA20 minus EMA50 at `idx`, in price units.

    Seeded from the first close and smoothed forward, so the value at any index
    depends only on bars up to that index.
    """
    if idx < 0 or idx >= len(bars) or idx + 1 < MIN_EMA_BARS:
        return 0.0
    k20, k50 = 2.0 / 21.0, 2.0 / 51.0
    e20 = e50 = _get_ohlc(bars[0])[3]
    for i in range(1, idx + 1):
        c = _get_ohlc(bars[i])[3]
        e20 = c * k20 + e20 * (1.0 - k20)
        e50 = c * k50 + e50 * (1.0 - k50)
    return e20 - e50


def measure_pressure(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    lookback: int = 10,
    strong_close_pct: float = 0.70,
    min_body_pct: float = 0.30,
) -> tuple[float, int, int]:
    """Net strong-bar pressure over the lookback, in -1..1.

    Returns `(pressure, bull_count, bear_count)`.
    """
    if idx < 0 or idx >= len(bars):
        return 0.0, 0, 0
    n = max(1, lookback)
    bull = bear = 0
    for i in range(idx, max(-1, idx - n), -1):
        if i < 0 or i > last_closed or i >= len(bars):
            continue
        o, _h, l_val, c = _get_ohlc(bars[i])
        rg = max(_h - l_val, 1e-9)
        direction = 1 if c > o else (-1 if c < o else 0)
        close_pos = (c - l_val) / rg
        body_ratio = abs(c - o) / rg
        if direction > 0 and close_pos >= strong_close_pct and body_ratio >= min_body_pct:
            bull += 1
        if (
            direction < 0
            and (1.0 - close_pos) >= strong_close_pct
            and body_ratio >= min_body_pct
        ):
            bear += 1
    return (bull - bear) / n, bull, bear


def measure_trend(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> TrendMetrics:
    """Collect the objective trend inputs at `idx`."""
    cfg = config or AnalyzerConfig()
    if idx < 0 or idx > last_closed or idx >= len(bars) or atr <= 0:
        return TrendMetrics()

    gap = calculate_trend_gap(bars, idx)
    slope = clamp11(gap / atr / SLOPE_ATR_DIVISOR)
    pressure, _bull, _bear = measure_pressure(
        bars,
        idx,
        last_closed,
        lookback=cfg.pressure_lookback,
        strong_close_pct=cfg.strong_close_pct,
        min_body_pct=cfg.min_body_pct,
    )
    return TrendMetrics(
        gap=gap,
        slope=slope,
        pressure=pressure,
        bull_slope=clamp01(slope),
        bear_slope=clamp01(-slope),
        bull_pressure=clamp01(pressure),
        bear_pressure=clamp01(-pressure),
        valid=True,
    )


def raw_scores(
    trend: TrendMetrics,
    expand: float,
) -> tuple[float, float]:
    """Raw (un-normalised) contributions toward BULL_TREND / BEAR_TREND."""
    return (
        trend.bull_slope + trend.bull_pressure + expand,
        trend.bear_slope + trend.bear_pressure + expand,
    )
