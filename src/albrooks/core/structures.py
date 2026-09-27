"""Price Action Structures: Climaxes, wedges, exhaustion, channels, and gaps."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.engine.configuration import AnalyzerConfig


@dataclass(frozen=True, slots=True)
class ExhaustionStructure:
    bar_index: int
    direction: int
    climax: bool = False
    stall: bool = False
    pushes: int = 0
    push_ok: bool = False
    wedge: bool = False
    overshoot: bool = False
    breadth: int = 0

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


def _range(b: Bar | dict[str, Any]) -> float:
    _, h, low_val, _ = _get_ohlc(b)
    rg = h - low_val
    return rg if rg > 0.0 else 1e-9


def push_count_back(
    bars: Sequence[Bar | dict[str, Any]],
    idx: int,
    last_closed: int,
    direction: int,
) -> int:
    if idx < 0 or idx > last_closed or idx >= len(bars):
        return 0
    n = 0
    i = idx
    while i >= 1 and i <= last_closed and i < len(bars):
        _, curr_h, curr_l, curr_c = _get_ohlc(bars[i])
        _, prev_h, prev_l, prev_c = _get_ohlc(bars[i - 1])
        if direction > 0:
            if not (curr_c > prev_c and curr_h > prev_h):
                break
        else:
            if not (curr_c < prev_c and curr_l < prev_l):
                break
        n += 1
        if n >= 6:
            break
        i -= 1
    return n


def detect_wedge(
    bars: Sequence[Bar | dict[str, Any]],
    idx: int,
    last_closed: int,
    direction: int,
) -> bool:
    if idx - 2 < 0 or idx > last_closed or idx >= len(bars):
        return False
    n = push_count_back(bars, idx, last_closed, direction)
    if n < 3:
        return False
    shrink = all(
        _range(bars[i]) <= _range(bars[i - 1]) * 1.05
        for i in range(idx, max(0, idx - n + 1), -1)
        if i - 1 >= 0
    )
    return bool(shrink or n >= 4)


def detect_exhaustion(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    direction: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> ExhaustionStructure:
    cfg = config or AnalyzerConfig()
    if idx < 0 or idx > last_closed or idx >= len(bars) or atr <= 0:
        return ExhaustionStructure(bar_index=idx, direction=direction)

    b = bars[idx]
    o, h, low_val, c = _get_ohlc(b)
    rg = _range(b)
    climax = rg >= cfg.big_bar_atr * atr
    up_w = h - max(c, o)
    lo_w = min(c, o) - low_val
    stall = rg < cfg.small_bar_atr * atr + 1e-9 and up_w > 0.4 * rg and lo_w > 0.4 * rg
    pushes = push_count_back(bars, idx, last_closed, direction)
    push_ok = pushes >= max(2, cfg.min_pushes)
    wedge = bool(cfg.use_wedge and detect_wedge(bars, idx, last_closed, direction))

    overshoot = False
    if idx - 19 >= 0:
        win = bars[idx - 19:idx + 1]
        closes = [_get_ohlc(x)[3] for x in win]
        highs = [_get_ohlc(x)[1] for x in win]
        lows = [_get_ohlc(x)[2] for x in win]
        sma = sum(closes) / 20.0
        hh = max(highs)
        ll = min(lows)
        if direction > 0:
            overshoot = (h - max(sma, hh - (hh - ll) * 0.2)) > 0.3 * atr
        else:
            overshoot = (min(sma, ll + (hh - ll) * 0.2) - low_val) > 0.3 * atr

    breadth = sum([climax, stall, push_ok, wedge, overshoot])
    return ExhaustionStructure(
        bar_index=idx,
        direction=direction,
        climax=climax,
        stall=stall,
        pushes=pushes,
        push_ok=push_ok,
        wedge=wedge,
        overshoot=overshoot,
        breadth=breadth,
    )
