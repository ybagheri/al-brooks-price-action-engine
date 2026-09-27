"""Bar-by-bar price action feature calculation.

This module **composes** the focused price-action modules rather than
recomputing their logic inline. It owns the per-bar feature record
(`BarFeatures`), the ATR series, and the label taxonomy -- nothing else.

| Concern | Owner |
|---|---|
| overlap, inside/outside, barbwire, inside runs | `price_action.overlap` |
| consecutive runs, strong-bar pressure | `price_action.pressure` |
| micro gaps | `price_action.gaps` |
| climax / stall | `price_action.climaxes` |
| range contraction | `price_action.wedges` |

`pair_overlap` is re-exported from `price_action.overlap` for backward
compatibility.

Classification: the raw measurements are `OBJECTIVE`; the labels and the
`HEURISTIC` thresholds behind them are documented in
`docs/algorithms/BAR_BY_BAR.md`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.price_action.climaxes import measure_bar
from albrooks.price_action.gaps import detect_gap
from albrooks.price_action.overlap import (
    count_inside_run,
    detect_barbwire,
    is_inside_bar,
    is_outside_bar,
    pair_overlap,
)
from albrooks.price_action.pressure import consecutive_run, count_pressure
from albrooks.price_action.wedges import is_tightening


@dataclass(frozen=True, slots=True)
class BarFeatures:
    index: int
    valid: bool = False
    dir: int = 0
    range: float = 0.0
    body: float = 0.0
    body_ratio: float = 0.0
    close_pos: float = 0.5
    upper_tail: float = 0.0
    lower_tail: float = 0.0
    upper_ratio: float = 0.0
    lower_ratio: float = 0.0
    is_doji: bool = False
    is_big: bool = False
    is_small: bool = False
    is_strong_bull: bool = False
    is_strong_bear: bool = False
    is_inside: bool = False
    is_outside: bool = False
    overlap: float = 0.0
    gap_up: bool = False
    gap_down: bool = False
    consecutive: int = 0
    ii_count: int = 0
    pressure_bull: int = 0
    pressure_bear: int = 0
    barbwire: bool = False
    tightening: bool = False
    label: str = "NONE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get_ohlc(b: Bar | dict[str, Any]) -> tuple[float, float, float, float]:
    if isinstance(b, Bar):
        return b.open, b.high, b.low, b.close
    open_v = float(b.get('o', b.get('open', 0.0)))
    high_v = float(b.get('h', b.get('high', 0.0)))
    low_v = float(b.get('l', b.get('low', 0.0)))
    close_v = float(b.get('c', b.get('close', 0.0)))
    return open_v, high_v, low_v, close_v


def _range(b: Bar | dict[str, Any]) -> float:
    _, high_v, low_v, _ = _get_ohlc(b)
    rg = high_v - low_v
    return rg if rg > 0.0 else 1e-9


def _body(b: Bar | dict[str, Any]) -> float:
    o, _, _, c = _get_ohlc(b)
    return abs(c - o)


def _dir(b: Bar | dict[str, Any]) -> int:
    o, _, _, c = _get_ohlc(b)
    if c > o:
        return 1
    if c < o:
        return -1
    return 0


def calculate_atr_series(bars: Sequence[Bar | dict[str, Any]], period: int = 14) -> list[float]:
    n = len(bars)
    if n == 0:
        return []
    atrs: list[float] = [0.0] * n
    trs: list[float] = [0.0] * n

    for i in range(n):
        _, bh, bl, _ = _get_ohlc(bars[i])
        if i == 0:
            trs[i] = bh - bl
        else:
            _, _, _, pc = _get_ohlc(bars[i - 1])
            trs[i] = max(bh - bl, abs(bh - pc), abs(bl - pc))

    if n < period:
        cum = 0.0
        for i in range(n):
            cum += trs[i]
            atrs[i] = cum / (i + 1)
        return atrs

    cum = sum(trs[:period])
    atrs[period - 1] = cum / period
    for i in range(period, n):
        atrs[i] = (atrs[i - 1] * (period - 1) + trs[i]) / period
    for i in range(period - 1):
        atrs[i] = atrs[period - 1]

    return atrs


def analyze_bar(
    bars: Sequence[Bar | dict[str, Any]],
    idx: int,
    last_closed: int,
    atr: float = 0.0,
    config: AnalyzerConfig | None = None,
) -> BarFeatures:
    cfg = config or AnalyzerConfig()
    if idx < 0 or idx > last_closed or idx >= len(bars):
        return BarFeatures(index=idx)

    b = bars[idx]
    o, h, low_v, c = _get_ohlc(b)
    rg = _range(b)
    bd = _body(b)
    br = bd / rg
    cp = (c - low_v) / rg
    d = _dir(b)
    up_t = h - max(c, o)
    lo_t = min(c, o) - low_v
    is_doji = br < cfg.doji_max_body

    # Bar character is measured once, in one place, by `price_action.climaxes`.
    char = measure_bar(
        b,
        atr=atr,
        big_bar_atr=cfg.big_bar_atr,
        small_bar_atr=cfg.small_bar_atr,
        doji_max_body=cfg.doji_max_body,
    )
    is_big = char.is_climax
    is_small = atr > 0 and rg < cfg.small_bar_atr * atr

    is_strong_bull = d > 0 and cp >= cfg.strong_close_pct and br >= cfg.min_body_pct
    is_strong_bear = d < 0 and (1.0 - cp) >= cfg.strong_close_pct and br >= cfg.min_body_pct

    is_inside = False
    is_outside = False
    overlap = 0.0

    if idx - 1 >= 0:
        prev = bars[idx - 1]
        is_inside = is_inside_bar(b, prev)
        is_outside = is_outside_bar(b, prev)
        overlap = pair_overlap(b, prev)

    gap = detect_gap(bars, idx)
    gap_up = gap.direction == 1
    gap_down = gap.direction == -1

    consecutive = consecutive_run(
        bars,
        idx,
        last_closed,
        doji_max_body=cfg.doji_max_body,
    )
    ii_count = count_inside_run(bars, idx, last_closed)

    pb, pe = count_pressure(
        bars,
        idx,
        last_closed,
        lookback=cfg.pressure_lookback,
        strong_close_pct=cfg.strong_close_pct,
        min_body_pct=cfg.min_body_pct,
    )

    barbwire = detect_barbwire(
        bars,
        idx,
        last_closed,
        window=cfg.barbwire_bars,
        min_overlap=cfg.barbwire_min_overlap,
        overlap_ratio=cfg.overlap_ratio,
        doji_max_body=cfg.doji_max_body,
    )

    tightening = is_tightening(bars, idx)

    label = "BAR"
    if is_strong_bull:
        label = "STRONG_BULL"
    elif is_strong_bear:
        label = "STRONG_BEAR"
    elif ii_count >= 2:
        label = f"II{ii_count}"
    elif is_big:
        label = "BIG"
    elif is_doji:
        label = "DOJI"
    elif is_outside:
        label = "OUTSIDE"
    elif is_inside:
        label = "INSIDE"
    elif gap_up or gap_down:
        label = "GAP"

    return BarFeatures(
        index=idx,
        valid=True,
        dir=d,
        range=rg,
        body=bd,
        body_ratio=br,
        close_pos=cp,
        upper_tail=up_t,
        lower_tail=lo_t,
        upper_ratio=up_t / rg,
        lower_ratio=lo_t / rg,
        is_doji=is_doji,
        is_big=is_big,
        is_small=is_small,
        is_strong_bull=is_strong_bull,
        is_strong_bear=is_strong_bear,
        is_inside=is_inside,
        is_outside=is_outside,
        overlap=overlap,
        gap_up=gap_up,
        gap_down=gap_down,
        consecutive=consecutive,
        ii_count=ii_count,
        pressure_bull=pb,
        pressure_bear=pe,
        barbwire=barbwire,
        tightening=tightening,
        label=label,
    )


def analyze_series(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    config: AnalyzerConfig | None = None,
) -> list[BarFeatures]:
    cfg = config or AnalyzerConfig()
    n = len(bars)
    if n == 0:
        return []
    atrs = calculate_atr_series(bars, period=cfg.atr_period)
    last_closed = n - 1
    return [
        analyze_bar(bars, i, last_closed=last_closed, atr=atrs[i], config=cfg)
        for i in range(n)
    ]
