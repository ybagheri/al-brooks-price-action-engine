"""Trading-range measurement: how wide, how tight, how balanced.

The measured quantities here are objective (a window high minus a window low,
normalised by ATR). Turning them into a *classification* is a proxy, and the
classification is owned by `market_state.py`; this module supplies the facts and
the raw score contribution.

Classification: PROXY for the range verdict, OBJECTIVE for the measurements.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries

# Span (in ATR) above which the window counts as expanding.
EXPAND_SPAN: float = 3.0
# Span (in ATR) below which the window counts as compact.
COMPACT_SPAN: float = 6.0


@dataclass(frozen=True, slots=True)
class RangeMetrics:
    """Objective range measurements over a lookback window ending at `idx`."""

    span_atr: float = 0.0
    window_high: float = 0.0
    window_low: float = 0.0
    lookback: int = 0

    @property
    def is_expanding(self) -> bool:
        return self.span_atr > EXPAND_SPAN

    @property
    def is_compact(self) -> bool:
        return self.span_atr < COMPACT_SPAN

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


def clamp01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def clamp11(x: float) -> float:
    return min(max(x, -1.0), 1.0)


def measure_range(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    atr: float,
    lookback: int = 20,
) -> RangeMetrics:
    """Window high/low over `lookback` closed bars ending at `idx`, in ATR."""
    if idx < 0 or idx >= len(bars) or atr <= 0 or lookback < 1:
        return RangeMetrics()
    w0 = max(0, idx - lookback + 1)
    highs = [_get_ohlc(bars[i])[1] for i in range(w0, idx + 1)]
    lows = [_get_ohlc(bars[i])[2] for i in range(w0, idx + 1)]
    if not highs or not lows:
        return RangeMetrics()
    hh, ll = max(highs), min(lows)
    return RangeMetrics(
        span_atr=(hh - ll) / atr,
        window_high=hh,
        window_low=ll,
        lookback=idx - w0 + 1,
    )


def expansion_score(span_atr: float) -> float:
    """0..1 evidence that the window is wide/open."""
    return clamp01((span_atr - EXPAND_SPAN) / EXPAND_SPAN)


def compaction_score(span_atr: float) -> float:
    """0..1 evidence that the window is narrow/contained."""
    return clamp01((COMPACT_SPAN - span_atr) / 4.0)


def balance_score(pressure: float) -> float:
    """0..1 evidence that neither side is dominating."""
    return 1.0 - abs(clamp11(pressure))


def raw_score(span_atr: float, chop: float, pressure: float) -> float:
    """Raw (un-normalised) contribution toward the TRADING_RANGE mode."""
    return compaction_score(span_atr) + chop + balance_score(pressure)
