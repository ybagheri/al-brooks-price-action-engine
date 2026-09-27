"""Channel measurement: how much bars overlap each other.

A channel in price action is trend plus shallow pullback -- price keeps making
overlapping progress rather than running clean. "Shallow pullback" is not
directly observable from bars, so the measurable stand-in used here is the
fraction of consecutive bar pairs whose bodies overlap by at least
`overlap_ratio`.

That is a PROXY, and a weak one: high overlap is consistent with a channel, but
it is also consistent with a tight trading range. `market_state.py` separates
the two using the independent trend-slope input.

Classification: chop measurement is OBJECTIVE, the channel verdict is PROXY.
"""

from __future__ import annotations

from typing import Any, Sequence

from albrooks.context.trading_range import RangeMetrics, clamp01
from albrooks.core.bars import Bar, BarSeries
from albrooks.price_action.bars import pair_overlap


def calculate_chop(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    overlap_bars: int = 10,
    overlap_ratio: float = 0.5,
) -> float:
    """Fraction of recent consecutive bar pairs that overlap, in 0..1.

    Only pairs fully inside `[0, idx]` are considered, so the result never
    depends on bars after the analysis point.
    """
    if idx < 0 or idx >= len(bars) or overlap_bars < 1:
        return 0.0
    o0 = max(0, idx - overlap_bars + 1)
    pairs = list(range(o0 + 1, idx + 1))
    if not pairs:
        return 0.0
    ov_count = sum(
        1 for i in pairs if pair_overlap(bars[i], bars[i - 1]) >= overlap_ratio
    )
    return ov_count / len(pairs)


def raw_scores(
    slope: float,
    chop: float,
    rng: RangeMetrics,
) -> tuple[float, float]:
    """Raw (un-normalised) contributions toward BULL_CHANNEL / BEAR_CHANNEL."""
    from albrooks.context.trading_range import compaction_score

    bull_t = clamp01(slope)
    bear_t = clamp01(-slope)
    compact = compaction_score(rng.span_atr)
    return bull_t + chop + compact, bear_t + chop + compact
