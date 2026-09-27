"""Swing and Pivot point detection models and algorithms."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries


@dataclass(frozen=True, slots=True)
class SwingPoint:
    bar_index: int
    price: float
    direction: int  # +1 for Swing High, -1 for Swing Low
    confirmed_bar_index: int
    is_high: bool
    is_low: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def find_swings(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    last_closed_idx: int | None = None,
    k: int = 3,
    use_close: bool = False,
) -> list[SwingPoint]:
    n = len(bars)
    if n == 0:
        return []
    if last_closed_idx is None:
        last_closed_idx = n - 1
    else:
        last_closed_idx = min(last_closed_idx, n - 1)

    def _px_h(b: Bar | dict[str, Any]) -> float:
        if use_close:
            return b.close if isinstance(b, Bar) else float(b.get('c', b.get('close', 0.0)))
        return b.high if isinstance(b, Bar) else float(b.get('h', b.get('high', 0.0)))

    def _px_l(b: Bar | dict[str, Any]) -> float:
        if use_close:
            return b.close if isinstance(b, Bar) else float(b.get('c', b.get('close', 0.0)))
        return b.low if isinstance(b, Bar) else float(b.get('l', b.get('low', 0.0)))

    swings: list[SwingPoint] = []
    # Bar s requires s - k >= 0 and s + k <= last_closed_idx
    for s in range(k, last_closed_idx - k + 1):
        if s < 1 or s + k >= n:
            continue

        ps_h = _px_h(bars[s])
        ps_l = _px_l(bars[s])

        is_high = True
        is_low = True

        for j in range(s - k, s + k + 1):
            if j == s:
                continue
            pj_h = _px_h(bars[j])
            pj_l = _px_l(bars[j])
            if pj_h > ps_h:
                is_high = False
            if pj_l < ps_l:
                is_low = False

        # Earliest-wins tie-break forward within the right wing
        if is_high:
            for j in range(s + 1, s + k + 1):
                if _px_h(bars[j]) == ps_h:
                    is_high = False
                    break

        if is_low:
            for j in range(s + 1, s + k + 1):
                if _px_l(bars[j]) == ps_l:
                    is_low = False
                    break

        if is_high:
            swings.append(
                SwingPoint(
                    bar_index=s,
                    price=ps_h,
                    direction=1,
                    confirmed_bar_index=s + k,
                    is_high=True,
                    is_low=False,
                )
            )
        elif is_low:
            swings.append(
                SwingPoint(
                    bar_index=s,
                    price=ps_l,
                    direction=-1,
                    confirmed_bar_index=s + k,
                    is_high=False,
                    is_low=True,
                )
            )

    return swings
