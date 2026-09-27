"""Market State and Context Analysis Engine (Systematic Proxies)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.price_action.bars import pair_overlap

STATES = [
    "BULL_TREND",
    "BEAR_TREND",
    "BULL_CHANNEL",
    "BEAR_CHANNEL",
    "TRADING_RANGE",
    "BREAKOUT_MODE",
]


@dataclass(frozen=True, slots=True)
class MarketState:
    valid: bool = False
    state: str = "UNKNOWN"
    percentages: list[int] = field(default_factory=lambda: [0] * 6)
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


def _get_ohlc(b: Bar | dict[str, Any]) -> tuple[float, float, float, float]:
    if isinstance(b, Bar):
        return b.open, b.high, b.low, b.close
    return (
        float(b.get('o', b.get('open', 0.0))),
        float(b.get('h', b.get('high', 0.0))),
        float(b.get('l', b.get('low', 0.0))),
        float(b.get('c', b.get('close', 0.0))),
    )


def _clamp01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def _clamp11(x: float) -> float:
    return min(max(x, -1.0), 1.0)


def calculate_trend_gap(bars: Sequence[Bar | dict[str, Any]], idx: int) -> float:
    if idx < 0 or idx >= len(bars) or idx + 1 < 50:
        return 0.0
    k20, k50 = 2.0 / 21.0, 2.0 / 51.0
    _, _, _, first_c = _get_ohlc(bars[0])
    e20 = e50 = first_c
    for i in range(1, idx + 1):
        _, _, _, c = _get_ohlc(bars[i])
        e20 = c * k20 + e20 * (1.0 - k20)
        e50 = c * k50 + e50 * (1.0 - k50)
    return e20 - e50


def analyze_market_state(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> MarketState:
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

    t_gap = calculate_trend_gap(bars, idx)
    ts = _clamp11(t_gap / atr / 2.0)
    w0 = max(0, idx - lookback + 1)

    highs = [_get_ohlc(bars[i])[1] for i in range(w0, idx + 1)]
    lows = [_get_ohlc(bars[i])[2] for i in range(w0, idx + 1)]
    rs = (max(highs) - min(lows)) / atr

    o0 = max(0, idx - overlap_bars + 1)
    pairs = list(range(o0 + 1, idx + 1))
    chop = 0.0
    if pairs:
        ov_count = sum(1 for i in pairs if pair_overlap(bars[i], bars[i - 1]) >= cfg.overlap_ratio)
        chop = ov_count / len(pairs)

    # Pressure
    p_lookback = max(1, cfg.pressure_lookback)
    pb, pe = 0, 0
    for i in range(idx, max(-1, idx - p_lookback), -1):
        if i < 0 or i > last_closed or i >= len(bars):
            continue
        o, h, l_val, c = _get_ohlc(bars[i])
        rg = max(h - l_val, 1e-9)
        d = 1 if c > o else (-1 if c < o else 0)
        cp = (c - l_val) / rg
        br = abs(c - o) / rg
        if d > 0 and cp >= cfg.strong_close_pct and br >= cfg.min_body_pct:
            pb += 1
        if d < 0 and (1.0 - cp) >= cfg.strong_close_pct and br >= cfg.min_body_pct:
            pe += 1

    pr = (pb - pe) / p_lookback

    # Tightening
    tight = False
    if idx >= 4:
        ranges = sorted(_get_ohlc(bars[i])[1] - _get_ohlc(bars[i])[2] for i in range(idx - 4, idx))
        med = (ranges[1] + ranges[2]) * 0.5
        curr_rg = _get_ohlc(bars[idx])[1] - _get_ohlc(bars[idx])[2]
        tight = curr_rg < med

    bull_t, bear_t = _clamp01(ts), _clamp01(-ts)
    bull_p, bear_p = _clamp01(pr), _clamp01(-pr)
    expand = _clamp01((rs - 3.0) / 3.0)
    compact = _clamp01((6.0 - rs) / 4.0)
    balance = 1.0 - abs(pr)

    raws = [
        bull_t + bull_p + expand,
        bear_t + bear_p + expand,
        bull_t + chop + compact,
        bear_t + chop + compact,
        compact + chop + balance,
        (1.0 if tight else 0.0) + compact + chop,
    ]

    evidence: list[str] = []
    if abs(ts) > 0.5:
        evidence.append(f"STRONG_EMA_TREND_SLOPE: {ts:.2f}")
    if chop > 0.5:
        evidence.append(f"HIGH_BAR_OVERLAP_CHOP: {chop:.2f}")
    if tight:
        evidence.append("RANGE_TIGHTENING_COMPRESSION")

    warnings: list[str] = []
    if rs > 5.0 and abs(pr) < 0.2:
        warnings.append("WIDE_RANGE_EXHAUSTION_RISK")

    s = sum(raws)
    if s <= 0:
        return MarketState(
            valid=True,
            state="TRANSITION",
            percentages=[0] * 6,
            trend=ts,
            range_atr=rs,
            chop=chop,
            pressure=pr,
            tight=tight,
            evidence=evidence,
            warnings=warnings,
        )

    exact = [r / s * 100.0 for r in raws]
    pct = [int(math.floor(e)) for e in exact]
    frac = [e - p for e, p in zip(exact, pct)]
    for _ in range(100 - sum(pct)):
        bi = max(range(6), key=lambda i: (frac[i], -i))
        pct[bi] += 1
        frac[bi] = -1.0

    bi = max(range(6), key=lambda i: (raws[i], -i))
    state_str = STATES[bi] if raws[bi] >= 1.0 else "TRANSITION"

    return MarketState(
        valid=True,
        state=state_str,
        percentages=pct,
        trend=ts,
        range_atr=rs,
        chop=chop,
        pressure=pr,
        tight=tight,
        max_raw=raws[bi],
        evidence=evidence,
        warnings=warnings,
    )
