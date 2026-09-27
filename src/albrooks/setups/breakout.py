"""Breakout and Failed Breakout State Machine Engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.core.swings import SwingPoint
from albrooks.engine.configuration import AnalyzerConfig


@dataclass(frozen=True, slots=True)
class BreakoutResult:
    found: bool = False
    direction: int = 0
    breakout_bar: int = -1
    reference_price: float = 0.0
    ref_is_swing: bool = False
    outcome: str = "NONE"  # PENDING, FOLLOW, FAILED, NONE
    trap: bool = False
    decide_bar: int = -1

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


def nbar_reference(
    bars: Sequence[Bar | dict[str, Any]],
    k: int,
    n: int,
) -> tuple[float, float] | None:
    lo = max(0, k - n)
    win = bars[lo:k]
    if len(win) < 10:
        return None
    return (
        max(_get_ohlc(b)[1] for b in win),
        min(_get_ohlc(b)[2] for b in win),
    )


def swing_reference(
    swings: Sequence[SwingPoint | dict[str, Any]],
    k: int,
) -> tuple[float | None, float | None]:
    sh: float | None = None
    sl: float | None = None

    for s in swings:
        bar = s.bar_index if isinstance(s, SwingPoint) else int(s.get('bar', 0))
        d = s.direction if isinstance(s, SwingPoint) else int(s.get('dir', 0))
        px = s.price if isinstance(s, SwingPoint) else float(s.get('price', 0.0))

        if bar >= k:
            continue
        if d == 1:
            sh = px
        elif d == -1:
            sl = px
    return sh, sl


def detect_breakout_event(
    bars: Sequence[Bar | dict[str, Any]],
    k: int,
    last_closed: int,
    atr: float,
    swings: Sequence[SwingPoint | dict[str, Any]],
    lookback: int = 20,
    tol_atr: float = 0.10,
) -> tuple[int, float, bool]:
    if k < 0 or k > last_closed or k >= len(bars) or atr <= 0:
        return 0, 0.0, False

    n = max(10, lookback)
    tol = tol_atr * atr
    nb = nbar_reference(bars, k, n)
    sh, sl = swing_reference(swings, k)
    c = _get_ohlc(bars[k])[3]

    if (sh is not None and c > sh + tol) or (nb is not None and c > nb[0] + tol):
        if sh is not None and c > sh + tol:
            return 1, sh, True
        return 1, nb[0], False

    if (sl is not None and c < sl - tol) or (nb is not None and c < nb[1] - tol):
        if sl is not None and c < sl - tol:
            return -1, sl, True
        return -1, nb[1], False

    return 0, 0.0, False


def _failed_since(
    bars: Sequence[Bar | dict[str, Any]],
    m: int,
    stop_idx: int,
    ref: float,
    direction: int,
    tol: float,
) -> int:
    for j in range(m - 1, stop_idx, -1):
        c = _get_ohlc(bars[j])[3]
        if direction > 0 and c < ref - tol:
            return j
        if direction < 0 and c > ref + tol:
            return j
    return -1


def analyze_breakout(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    swings: Sequence[SwingPoint | dict[str, Any]] = (),
    config: AnalyzerConfig | None = None,
) -> BreakoutResult:
    if idx < 0 or idx > last_closed or idx >= len(bars) or atr <= 0:
        return BreakoutResult()

    tol = 0.10 * atr
    f_bars = 5
    t_bars = 20
    k = -1
    ref = 0.0
    is_sw = False
    direction = 0

    for kk in range(idx, max(-1, idx - f_bars - 1), -1):
        if kk < 0:
            continue
        d, rp, sw = detect_breakout_event(
            bars, kk, last_closed, atr, swings, lookback=20, tol_atr=0.10
        )
        if d != 0:
            k, ref, is_sw, direction = kk, rp, sw, d
            break

    if k < 0:
        return BreakoutResult()

    outcome = "PENDING"
    decide_bar = -1
    fb = _failed_since(bars, idx + 1, k, ref, direction, tol)

    if fb >= 0:
        outcome = "FAILED"
        decide_bar = fb
    else:
        for j in range(idx, k, -1):
            c = _get_ohlc(bars[j])[3]
            if direction > 0 and c > ref + tol:
                outcome = "FOLLOW"
                decide_bar = j
                break
            if direction < 0 and c < ref - tol:
                outcome = "FOLLOW"
                decide_bar = j
                break

    trap = False
    for m in range(max(0, k - t_bars), k):
        if m > last_closed:
            continue
        d, rp, _sw = detect_breakout_event(
            bars, m, last_closed, atr, swings, lookback=20, tol_atr=0.10
        )
        if d != direction:
            continue
        if _failed_since(bars, k + 1, m, rp, direction, tol) >= 0:
            trap = True
            break

    return BreakoutResult(
        found=True,
        direction=direction,
        breakout_bar=k,
        reference_price=ref,
        ref_is_swing=is_sw,
        outcome=outcome,
        trap=trap,
        decide_bar=decide_bar,
    )
