"""Systematic H1/H2 and L1/L2 Pullback Entry Detectors."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from albrooks.context.market_state import calculate_trend_gap
from albrooks.core.bars import Bar, BarSeries
from albrooks.engine.configuration import AnalyzerConfig


@dataclass(frozen=True, slots=True)
class PullbackSetup:
    found: bool = False
    setup_type: str = "NONE"  # H1, H2, L1, L2
    legs: int = 0
    signal_bar: int = -1
    anchor_bar: int = -1
    reference_price: float = 0.0
    stop_price: float = 0.0
    direction: int = 0  # +1 Bull (H1/H2), -1 Bear (L1/L2)
    state: str = "CONFIRMED"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get_ohlc(b: Bar | dict[str, Any]) -> tuple[float, float, float, float]:
    if isinstance(b, Bar):
        return b.open, b.high, b.low, b.close
    return (
        float(b.get('o', b.get('open', 0.0))),
        float(b.get('h', b.get('high', 0.0))),
        float(b.get('l', b.get('low', 0.0))),
        float(b.get('c', b.get('close', 0.0))),
    )


def determine_trend_direction(
    bars: Sequence[Bar | dict[str, Any]],
    idx: int,
    last_closed: int,
    atr: float,
) -> int:
    if idx < 0 or idx > last_closed or idx >= len(bars) or atr <= 0:
        return 0
    t_gap = calculate_trend_gap(bars, idx) / atr
    if t_gap > 0.4:
        return 1
    if t_gap < -0.4:
        return -1
    return 0


def detect_h1_h2(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> PullbackSetup:
    cfg = config or AnalyzerConfig()
    if idx < 0 or idx > last_closed or idx >= len(bars) or atr <= 0:
        return PullbackSetup()

    if determine_trend_direction(bars, idx, last_closed, atr) != 1:
        return PullbackSetup()

    w0 = max(0, idx - cfg.max_pb_bars)
    if w0 + 1 > idx:
        return PullbackSetup()

    highs = [_get_ohlc(bars[i])[1] for i in range(w0, idx + 1)]
    lows = [_get_ohlc(bars[i])[2] for i in range(w0, idx + 1)]
    mxh = max(highs)
    mnl = min(lows)

    if (mxh - mnl) < cfg.min_pb_ratio * atr:
        return PullbackSetup()

    h1 = -1
    for i in range(w0 + 1, idx + 1):
        if _get_ohlc(bars[i])[1] > _get_ohlc(bars[i - 1])[1]:
            h1 = i
            break
    if h1 < 0:
        return PullbackSetup()

    low_at = min(_get_ohlc(bars[i])[2] for i in range(w0, h1 + 1))
    jlow = -1
    for j in range(h1 + 1, idx + 1):
        if _get_ohlc(bars[j])[2] < low_at:
            jlow = j
            break

    if jlow < 0:
        return PullbackSetup(
            found=True,
            setup_type="H1",
            legs=1,
            signal_bar=h1,
            anchor_bar=h1,
            reference_price=_get_ohlc(bars[h1])[1],
            stop_price=mnl,
            direction=1,
        )

    h2 = -1
    for k in range(jlow + 1, idx + 1):
        if _get_ohlc(bars[k])[1] > _get_ohlc(bars[k - 1])[1]:
            h2 = k
            break

    if h2 < 0:
        return PullbackSetup(
            found=True,
            setup_type="H1",
            legs=1,
            signal_bar=h1,
            anchor_bar=h1,
            reference_price=_get_ohlc(bars[h1])[1],
            stop_price=mnl,
            direction=1,
        )

    return PullbackSetup(
        found=True,
        setup_type="H2",
        legs=2,
        signal_bar=h2,
        anchor_bar=h1,
        reference_price=_get_ohlc(bars[h2])[1],
        stop_price=mnl,
        direction=1,
    )


def detect_l1_l2(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> PullbackSetup:
    cfg = config or AnalyzerConfig()
    if idx < 0 or idx > last_closed or idx >= len(bars) or atr <= 0:
        return PullbackSetup()

    if determine_trend_direction(bars, idx, last_closed, atr) != -1:
        return PullbackSetup()

    w0 = max(0, idx - cfg.max_pb_bars)
    if w0 + 1 > idx:
        return PullbackSetup()

    highs = [_get_ohlc(bars[i])[1] for i in range(w0, idx + 1)]
    lows = [_get_ohlc(bars[i])[2] for i in range(w0, idx + 1)]
    mxh = max(highs)
    mnl = min(lows)

    if (mxh - mnl) < cfg.min_pb_ratio * atr:
        return PullbackSetup()

    l1 = -1
    for i in range(w0 + 1, idx + 1):
        if _get_ohlc(bars[i])[2] < _get_ohlc(bars[i - 1])[2]:
            l1 = i
            break
    if l1 < 0:
        return PullbackSetup()

    high_at = max(_get_ohlc(bars[i])[1] for i in range(w0, l1 + 1))
    jhigh = -1
    for j in range(l1 + 1, idx + 1):
        if _get_ohlc(bars[j])[1] > high_at:
            jhigh = j
            break

    if jhigh < 0:
        return PullbackSetup(
            found=True,
            setup_type="L1",
            legs=1,
            signal_bar=l1,
            anchor_bar=l1,
            reference_price=_get_ohlc(bars[l1])[2],
            stop_price=mxh,
            direction=-1,
        )

    l2 = -1
    for k in range(jhigh + 1, idx + 1):
        if _get_ohlc(bars[k])[2] < _get_ohlc(bars[k - 1])[2]:
            l2 = k
            break

    if l2 < 0:
        return PullbackSetup(
            found=True,
            setup_type="L1",
            legs=1,
            signal_bar=l1,
            anchor_bar=l1,
            reference_price=_get_ohlc(bars[l1])[2],
            stop_price=mxh,
            direction=-1,
        )

    return PullbackSetup(
        found=True,
        setup_type="L2",
        legs=2,
        signal_bar=l2,
        anchor_bar=l1,
        reference_price=_get_ohlc(bars[l2])[2],
        stop_price=mxh,
        direction=-1,
    )
