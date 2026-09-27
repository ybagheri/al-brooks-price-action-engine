"""Major Trend Reversal (MTR) and Minor Trend Reversal Engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.core.structures import push_count_back
from albrooks.core.swings import SwingPoint
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.setups.breakout import analyze_breakout


@dataclass(frozen=True, slots=True)
class ReversalResult:
    found: bool = False
    verdict: str = "NONE"  # MAJOR, MINOR, NONE
    direction: int = 0  # +1 Bull Reversal, -1 Bear Reversal
    ema_break: bool = False
    retest: bool = False
    bo_follow: bool = False
    pressure_ok: bool = False
    pressure_count: int = 0
    score: int = 0
    cross_bar: int = -1

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


def _calculate_ema20_tail(bars: Sequence[Bar | dict[str, Any]], idx: int) -> dict[int, float]:
    first_c = _get_ohlc(bars[0])[3]
    e = first_c
    k = 2.0 / 21.0
    tail: dict[int, float] = {}
    for i in range(1, idx + 1):
        c = _get_ohlc(bars[i])[3]
        e = c * k + e * (1.0 - k)
        tail[i] = e
    return tail


def _side(close: float, ema: float, tol: float) -> int:
    if close > ema + tol:
        return 1
    if close < ema - tol:
        return -1
    return 0


def analyze_reversal(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    swings: Sequence[SwingPoint | dict[str, Any]] = (),
    reversal_direction: int = 1,
    config: AnalyzerConfig | None = None,
) -> ReversalResult:
    cfg = config or AnalyzerConfig()
    if idx < 0 or idx > last_closed or idx >= len(bars) or atr <= 0:
        return ReversalResult(direction=reversal_direction)
    if reversal_direction not in (1, -1):
        return ReversalResult(direction=reversal_direction)

    k_bars = 10
    if idx + 1 < k_bars + 2:
        return ReversalResult(direction=reversal_direction)

    tol = 0.25 * atr
    ema = _calculate_ema20_tail(bars, idx)
    curr_c = _get_ohlc(bars[idx])[3]

    if _side(curr_c, ema[idx], tol) != reversal_direction:
        return ReversalResult(direction=reversal_direction)

    cross_bar = -1
    for j in range(idx - 1, max(-1, idx - k_bars), -1):
        if _side(_get_ohlc(bars[j])[3], ema[j], tol) == -reversal_direction:
            cross_bar = j
            break

    if cross_bar < 0:
        return ReversalResult(direction=reversal_direction)

    retest = False
    for j in range(cross_bar + 1, idx + 1):
        e = ema[j]
        jh = _get_ohlc(bars[j])[1]
        jl = _get_ohlc(bars[j])[2]
        jc = _get_ohlc(bars[j])[3]
        if reversal_direction > 0 and jl <= e + tol and jc > e - tol:
            retest = True
            break
        if reversal_direction < 0 and jh >= e - tol and jc < e + tol:
            retest = True
            break

    bo = analyze_breakout(bars, idx, last_closed, atr, swings, config=cfg)
    bo_follow = bool(bo.found and bo.direction == reversal_direction and bo.outcome == "FOLLOW")
    press_n = push_count_back(bars, idx, last_closed, reversal_direction)
    pressure_ok = press_n >= 5

    n = sum([True, retest, bo_follow, pressure_ok])
    score = 25 * n
    verdict = "MAJOR" if n >= 4 else ("MINOR" if n >= 1 else "NONE")

    return ReversalResult(
        found=verdict != "NONE",
        verdict=verdict,
        direction=reversal_direction,
        ema_break=True,
        retest=retest,
        bo_follow=bo_follow,
        pressure_ok=pressure_ok,
        pressure_count=press_n,
        score=score,
        cross_bar=cross_bar,
    )
