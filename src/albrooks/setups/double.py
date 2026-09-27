"""Double Tops and Double Bottoms Engine (Major and Micro)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.core.swings import SwingPoint
from albrooks.engine.configuration import AnalyzerConfig


@dataclass(frozen=True, slots=True)
class DoublePattern:
    found: bool = False
    direction: int = 0  # -1 for Double Top (Bearish), +1 for Double Bottom (Bullish)
    bar1: int = -1
    bar2: int = -1
    price1: float = 0.0
    price2: float = 0.0
    is_micro: bool = False
    pattern_type: str = "NONE"

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


def find_major_double_top(
    swings: Sequence[SwingPoint | dict[str, Any]],
    atr: float,
    config: AnalyzerConfig | None = None,
) -> DoublePattern:
    cfg = config or AnalyzerConfig()
    if not swings or atr <= 0:
        return DoublePattern(direction=-1, pattern_type="DOUBLE_TOP")

    tol = cfg.double_tol_atr * atr
    need = 0.50 * atr
    n = len(swings)

    def _dir(s: SwingPoint | dict[str, Any]) -> int:
        return s.direction if isinstance(s, SwingPoint) else int(s.get('dir', 0))

    def _price(s: SwingPoint | dict[str, Any]) -> float:
        return s.price if isinstance(s, SwingPoint) else float(s.get('price', 0.0))

    def _bar(s: SwingPoint | dict[str, Any]) -> int:
        return s.bar_index if isinstance(s, SwingPoint) else int(s.get('bar', 0))

    for j in range(n - 1, -1, -1):
        if _dir(swings[j]) != 1:
            continue
        for i in range(j - 1, -1, -1):
            if _dir(swings[i]) != 1:
                continue
            if abs(_price(swings[j]) - _price(swings[i])) > tol:
                continue
            if _bar(swings[j]) - _bar(swings[i]) > 20:
                continue
            base = min(_price(swings[i]), _price(swings[j]))
            ok = any(
                _dir(swings[k]) == -1 and (base - _price(swings[k])) >= need
                for k in range(i + 1, j)
            )
            if not ok:
                continue
            return DoublePattern(
                found=True,
                direction=-1,
                bar1=_bar(swings[i]),
                bar2=_bar(swings[j]),
                price1=_price(swings[i]),
                price2=_price(swings[j]),
                is_micro=False,
                pattern_type="MAJOR_DOUBLE_TOP",
            )
    return DoublePattern(direction=-1, pattern_type="MAJOR_DOUBLE_TOP")


def find_major_double_bottom(
    swings: Sequence[SwingPoint | dict[str, Any]],
    atr: float,
    config: AnalyzerConfig | None = None,
) -> DoublePattern:
    cfg = config or AnalyzerConfig()
    if not swings or atr <= 0:
        return DoublePattern(direction=1, pattern_type="DOUBLE_BOTTOM")

    tol = cfg.double_tol_atr * atr
    need = 0.50 * atr
    n = len(swings)

    def _dir(s: SwingPoint | dict[str, Any]) -> int:
        return s.direction if isinstance(s, SwingPoint) else int(s.get('dir', 0))

    def _price(s: SwingPoint | dict[str, Any]) -> float:
        return s.price if isinstance(s, SwingPoint) else float(s.get('price', 0.0))

    def _bar(s: SwingPoint | dict[str, Any]) -> int:
        return s.bar_index if isinstance(s, SwingPoint) else int(s.get('bar', 0))

    for j in range(n - 1, -1, -1):
        if _dir(swings[j]) != -1:
            continue
        for i in range(j - 1, -1, -1):
            if _dir(swings[i]) != -1:
                continue
            if abs(_price(swings[j]) - _price(swings[i])) > tol:
                continue
            if _bar(swings[j]) - _bar(swings[i]) > 20:
                continue
            base = max(_price(swings[i]), _price(swings[j]))
            ok = any(
                _dir(swings[k]) == 1 and (_price(swings[k]) - base) >= need
                for k in range(i + 1, j)
            )
            if not ok:
                continue
            return DoublePattern(
                found=True,
                direction=1,
                bar1=_bar(swings[i]),
                bar2=_bar(swings[j]),
                price1=_price(swings[i]),
                price2=_price(swings[j]),
                is_micro=False,
                pattern_type="MAJOR_DOUBLE_BOTTOM",
            )
    return DoublePattern(direction=1, pattern_type="MAJOR_DOUBLE_BOTTOM")


def detect_micro_double_top(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> DoublePattern:
    cfg = config or AnalyzerConfig()
    if idx < 0 or idx > last_closed or idx >= len(bars) or atr <= 0:
        return DoublePattern(direction=-1, is_micro=True, pattern_type="MICRO_DOUBLE_TOP")

    w = 5
    w0 = max(0, idx - w + 1)
    if idx - w0 + 1 < 3:
        return DoublePattern(direction=-1, is_micro=True, pattern_type="MICRO_DOUBLE_TOP")

    tol = cfg.double_tol_atr * atr
    need = 0.50 * atr * 0.5

    for j in range(idx, w0 - 1, -1):
        for i in range(j - 1, w0 - 1, -1):
            h_j = _get_ohlc(bars[j])[1]
            h_i = _get_ohlc(bars[i])[1]
            if abs(h_j - h_i) > tol:
                continue
            base = min(h_i, h_j)
            ok = any(
                base - _get_ohlc(bars[k])[2] >= need
                for k in range(i + 1, j)
            )
            if not ok:
                continue
            return DoublePattern(
                found=True,
                direction=-1,
                bar1=i,
                bar2=j,
                price1=h_i,
                price2=h_j,
                is_micro=True,
                pattern_type="MICRO_DOUBLE_TOP",
            )
    return DoublePattern(direction=-1, is_micro=True, pattern_type="MICRO_DOUBLE_TOP")


def detect_micro_double_bottom(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> DoublePattern:
    cfg = config or AnalyzerConfig()
    if idx < 0 or idx > last_closed or idx >= len(bars) or atr <= 0:
        return DoublePattern(direction=1, is_micro=True, pattern_type="MICRO_DOUBLE_BOTTOM")

    w = 5
    w0 = max(0, idx - w + 1)
    if idx - w0 + 1 < 3:
        return DoublePattern(direction=1, is_micro=True, pattern_type="MICRO_DOUBLE_BOTTOM")

    tol = cfg.double_tol_atr * atr
    need = 0.50 * atr * 0.5

    for j in range(idx, w0 - 1, -1):
        for i in range(j - 1, w0 - 1, -1):
            l_j = _get_ohlc(bars[j])[2]
            l_i = _get_ohlc(bars[i])[2]
            if abs(l_j - l_i) > tol:
                continue
            base = max(l_i, l_j)
            ok = any(
                _get_ohlc(bars[k])[1] - base >= need
                for k in range(i + 1, j)
            )
            if not ok:
                continue
            return DoublePattern(
                found=True,
                direction=1,
                bar1=i,
                bar2=j,
                price1=l_i,
                price2=l_j,
                is_micro=True,
                pattern_type="MICRO_DOUBLE_BOTTOM",
            )
    return DoublePattern(direction=1, is_micro=True, pattern_type="MICRO_DOUBLE_BOTTOM")
