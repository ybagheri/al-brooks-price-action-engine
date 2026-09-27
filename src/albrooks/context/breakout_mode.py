"""Breakout-mode measurement: is the market compressing toward an expansion?

Brooks describes a market "in breakout mode" when it has been quiet and tight
and is therefore coiled to move in either direction. Tightness is not directly
observable, so two measurable stand-ins are used:

* the newest bar's range is smaller than the median of the previous four
  (`is_tightening`), and
* the lookback window is narrow in ATR terms (shared with the range module).

The verdict is a `PROXY`. A tightening market does not reliably break out, and
`market_state.py` deliberately ranks BREAKOUT_MODE below directional modes so
that a genuine trend is not overridden by mere compression.

Detection rule for the mode itself: it is used only when no directional mode
scores higher, which is why `raw_score` returns a small quantity and the
orchestrator applies a floor.
"""

from __future__ import annotations

from typing import Any, Sequence

from albrooks.context.trading_range import RangeMetrics, compaction_score
from albrooks.core.bars import Bar, BarSeries

# Bars used for the median-range comparison.
TIGHTNESS_WINDOW: int = 4


def _get_ohlc(b: Bar | dict[str, Any]) -> tuple[float, float, float, float]:
    if isinstance(b, Bar):
        return b.open, b.high, b.low, b.close
    return (
        float(b.get("o", b.get("open", 0.0))),
        float(b.get("h", b.get("high", 0.0))),
        float(b.get("l", b.get("low", 0.0))),
        float(b.get("c", b.get("close", 0.0))),
    )


def is_tightening(bars: Sequence[Bar | dict[str, Any]] | BarSeries, idx: int) -> bool:
    """True when the newest bar's range is below the median of the prior four."""
    if idx < TIGHTNESS_WINDOW or idx >= len(bars):
        return False
    ranges = sorted(
        _get_ohlc(bars[i])[1] - _get_ohlc(bars[i])[2]
        for i in range(idx - TIGHTNESS_WINDOW, idx)
    )
    med = (ranges[1] + ranges[2]) * 0.5
    _, h, low_val, _ = _get_ohlc(bars[idx])
    return (h - low_val) < med


def raw_score(tight: bool, chop: float, rng: RangeMetrics) -> float:
    """Raw (un-normalised) contribution toward BREAKOUT_MODE."""
    return (1.0 if tight else 0.0) + compaction_score(rng.span_atr) + chop
