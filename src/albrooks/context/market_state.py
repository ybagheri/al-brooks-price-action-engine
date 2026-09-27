"""Market state: systematic proxies for the mode a market is in.

This module is an **orchestrator**. The measurements live in the focused
modules beside it:

| Module | Supplies |
|---|---|
| `trend` | EMA slope and directional pressure |
| `channel` | bar-overlap chop |
| `trading_range` | window span, compaction, balance |
| `breakout_mode` | range tightening |

Each produces a raw, un-normalised score contribution; this module sums them,
normalises to percentages, and picks the winning mode.

Honesty note (see docs/architecture/CONCEPT_TAXONOMY.md): "BULL_TREND" here is
a **PROXY**. It does not mean the market is in a bull trend. It means a
documented set of geometric conditions scored highest. Nothing here is
statistically validated, and no field is a probability.

`state` is retained as an alias of `mode` for backward compatibility.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from albrooks.context import breakout_mode as _breakout_mode
from albrooks.context import channel as _channel
from albrooks.context import trading_range as _range
from albrooks.context import trend as _trend
from albrooks.context.trend import calculate_trend_gap
from albrooks.core.bars import Bar, BarSeries
from albrooks.engine.configuration import AnalyzerConfig

STATES = [
    "BULL_TREND",
    "BEAR_TREND",
    "BULL_CHANNEL",
    "BEAR_CHANNEL",
    "TRADING_RANGE",
    "BREAKOUT_MODE",
]

TRANSITION = "TRANSITION"
UNKNOWN = "UNKNOWN"

#: Minimum raw score for a mode to be reported, instead of TRANSITION.
MODE_SCORE_FLOOR = 1.0

__all__ = [
    "STATES",
    "TRANSITION",
    "UNKNOWN",
    "MarketState",
    "analyze_market_state",
    "calculate_trend_gap",
]


@dataclass(frozen=True, slots=True)
class MarketState:
    """A systematic, explainable read of the current market mode.

    Attributes:
        mode: the winning mode, or ``TRANSITION`` / ``UNKNOWN``.
        direction: ``+1`` bull-leaning, ``-1`` bear-leaning, ``0`` neutral.
        strength: 0..1 concentration of the winning mode's share. This is *not*
            a probability of continuation.
        state: backward-compatible alias of ``mode``.
    """

    valid: bool = False
    state: str = UNKNOWN
    mode: str = UNKNOWN
    direction: int = 0
    strength: float = 0.0
    percentages: list[int] = field(default_factory=lambda: [0] * len(STATES))
    trend: float = 0.0
    range_atr: float = 0.0
    chop: float = 0.0
    pressure: float = 0.0
    tight: bool = False
    max_raw: float = 0.0
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_trending(self) -> bool:
        return self.mode in ("BULL_TREND", "BEAR_TREND")

    @property
    def is_channel(self) -> bool:
        return self.mode in ("BULL_CHANNEL", "BEAR_CHANNEL")

    @property
    def is_range(self) -> bool:
        return self.mode == "TRADING_RANGE"


def _direction_for(mode: str) -> int:
    if mode in ("BULL_TREND", "BULL_CHANNEL"):
        return 1
    if mode in ("BEAR_TREND", "BEAR_CHANNEL"):
        return -1
    return 0


def _largest_remainder(values: Sequence[float], total: float, slots: int) -> list[int]:
    """Distribute `slots` integer percentage points proportionally."""
    exact = [v / total * 100.0 for v in values]
    pct = [int(math.floor(e)) for e in exact]
    frac = [e - p for e, p in zip(exact, pct)]
    for _ in range(100 - sum(pct)):
        bi = max(range(len(values)), key=lambda i: (frac[i], -i))
        pct[bi] += 1
        frac[bi] = -1.0
    return pct


def analyze_market_state(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> MarketState:
    """Classify the market mode at bar `idx` from closed bars only."""
    cfg = config or AnalyzerConfig()
    if not cfg.enable_market_state:
        return MarketState()
    if idx < 0 or idx > last_closed or idx >= len(bars):
        return MarketState()
    if not atr or atr <= 0:
        return MarketState()

    lookback = max(10, cfg.state_lookback)
    overlap_bars = max(5, cfg.state_overlap_bars)
    if idx + 1 < max(lookback + 1, overlap_bars + 1, 6):
        return MarketState()

    trend = _trend.measure_trend(bars, idx, last_closed, atr, cfg)
    rng = _range.measure_range(bars, idx, atr, lookback=lookback)
    chop = _channel.calculate_chop(
        bars, idx, overlap_bars=overlap_bars, overlap_ratio=cfg.overlap_ratio
    )
    tight = _breakout_mode.is_tightening(bars, idx)
    expand = _range.expansion_score(rng.span_atr)

    raws = [
        *_trend.raw_scores(trend, expand),
        *_channel.raw_scores(trend.slope, chop, rng),
        _range.raw_score(rng.span_atr, chop, trend.pressure),
        _breakout_mode.raw_score(tight, chop, rng),
    ]

    evidence: list[str] = []
    if abs(trend.slope) > 0.5:
        evidence.append(f"STRONG_EMA_TREND_SLOPE: {trend.slope:.2f}")
    if chop > 0.5:
        evidence.append(f"HIGH_BAR_OVERLAP_CHOP: {chop:.2f}")
    if tight:
        evidence.append("RANGE_TIGHTENING_COMPRESSION")

    warnings: list[str] = []
    if rng.span_atr > 5.0 and abs(trend.pressure) < 0.2:
        warnings.append("WIDE_RANGE_EXHAUSTION_RISK")

    total = sum(raws)
    if total <= 0:
        return MarketState(
            valid=True,
            state=TRANSITION,
            mode=TRANSITION,
            percentages=[0] * len(STATES),
            trend=trend.slope,
            range_atr=rng.span_atr,
            chop=chop,
            pressure=trend.pressure,
            tight=tight,
            evidence=evidence,
            warnings=warnings,
        )

    bi = max(range(len(raws)), key=lambda i: (raws[i], -i))
    mode = STATES[bi] if raws[bi] >= MODE_SCORE_FLOOR else TRANSITION
    pct = _largest_remainder(raws, total, len(STATES))

    return MarketState(
        valid=True,
        state=mode,
        mode=mode,
        direction=_direction_for(mode),
        strength=pct[bi] / 100.0,
        percentages=pct,
        trend=trend.slope,
        range_atr=rng.span_atr,
        chop=chop,
        pressure=trend.pressure,
        tight=tight,
        max_raw=raws[bi],
        evidence=evidence,
        warnings=warnings,
    )
