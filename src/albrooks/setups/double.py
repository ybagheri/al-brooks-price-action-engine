"""Double tops and bottoms: major, micro, third-test, and breakout context.

Three questions are kept separate on purpose, because they answer different
things and collapse badly when merged:

1. **Is there a double?** Two extremes at the same level.
2. **Has the level been tested again?** A third test suggests the level matters.
3. **Did price break it, and did the break hold?** A break that fails is a
   different structure from a break that succeeds.

`classify_double_context` answers (2) and (3) from bar data and enriches a
pattern found by (1).

Classification: level matching is `ALGORITHMIC`; the tolerance that decides
"the same level" is a `HEURISTIC`; a double top is a `PROXY` for a reversal
setup, because two similar highs are a shape, not a forecast.

What this does NOT claim: that a double top is bearish, or that a failed break
of a double top is bullish. `direction` records the conventional reading of
the shape. No probability, expectancy, or reliability is attached, and none has
been validated.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.core.swings import SwingPoint
from albrooks.engine.configuration import AnalyzerConfig


@dataclass(frozen=True, slots=True)
class DoublePattern:
    """A double top or bottom, optionally enriched with test and break context.

    Context fields default to "not observed". They are only populated by
    `classify_double_context`, which needs bar data; a pattern found from
    swings alone carries the base fields only.
    """

    found: bool = False
    direction: int = 0  # -1 for Double Top (Bearish), +1 for Double Bottom (Bullish)
    bar1: int = -1
    bar2: int = -1
    price1: float = 0.0
    price2: float = 0.0
    is_micro: bool = False
    pattern_type: str = "NONE"
    # --- context, populated by classify_double_context ---
    level: float = 0.0  # the level both extremes share
    is_tested: bool = False  # a third test of the level occurred
    test_bar: int = -1
    test_count: int = 0  # total tests of the level after bar2
    breakout_direction: int = 0  # +1 up through resistance, -1 down through support
    breakout_bar: int = -1
    is_failed: bool = False  # the break did not hold
    failure_bar: int = -1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_double_top(self) -> bool:
        return self.direction == -1

    @property
    def is_double_bottom(self) -> bool:
        return self.direction == 1

    @property
    def is_broken(self) -> bool:
        return self.breakout_bar >= 0


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


def _enrich(pattern: DoublePattern, **changes: Any) -> DoublePattern:
    """Return an enriched copy, or the original when the pattern is not found."""
    if not pattern.found:
        return pattern
    return replace(pattern, **changes)


def classify_double_context(
    pattern: DoublePattern,
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> DoublePattern:
    """Add third-test, breakout and failure context to a found double.

    The level is taken as the mean of the two extremes. Working from `bar2`
    forward, a bar is a **test** when it reaches the level but does not close
    beyond it, and a **break** when it closes beyond it by more than the
    tolerance. A break followed by a close back inside the double's range is a
    **failed break**.

    Only the break direction that *through* the level counts. A double top is
    resistance, so only an upside break is a break; a close falling away below
    it is the pattern working as intended, not a breakdown. A double bottom
    mirrors this. Without that restriction every double top would immediately
    "break" downward on the bar after it formed.
    """
    cfg = config or AnalyzerConfig()
    if not pattern.found or atr <= 0 or last_closed < 0 or last_closed >= len(bars):
        return pattern

    tol = cfg.double_tol_atr * atr
    level = (pattern.price1 + pattern.price2) / 2.0
    is_top = pattern.direction == -1
    # The only meaningful break direction for this pattern.
    break_sign = 1 if is_top else -1

    tests = 0
    test_bar = -1
    break_bar = -1
    failure_bar = -1

    start = pattern.bar2 + 1
    upper = min(last_closed, len(bars) - 1)
    for i in range(start, upper + 1):
        _, h, low_val, c = _get_ohlc(bars[i])

        # Once a break has occurred the only remaining question is whether price
        # came back. Reclaim is checked FIRST: a close that returns to the
        # original side of the level also clears the opposite break threshold,
        # and evaluating the break first would misfile every reclaim as a fresh
        # break in the same direction.
        if break_bar >= 0:
            if failure_bar < 0:
                reclaimed = c < level if break_sign > 0 else c > level
                if reclaimed:
                    failure_bar = i
            continue

        broke = c > level + tol if break_sign > 0 else c < level - tol
        if broke:
            break_bar = i
            continue

        reached = h >= level - tol if is_top else low_val <= level + tol
        if reached:
            tests += 1
            if test_bar < 0:
                test_bar = i

    return _enrich(
        pattern,
        level=level,
        is_tested=tests > 0,
        test_bar=test_bar,
        test_count=tests,
        breakout_direction=break_sign if break_bar >= 0 else 0,
        breakout_bar=break_bar,
        is_failed=failure_bar >= 0,
        failure_bar=failure_bar,
    )


def detect_double_test(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    last_closed: int,
    level: float,
    is_resistance: bool,
    atr: float,
    window: int = 20,
    min_tests: int = 1,
    config: AnalyzerConfig | None = None,
) -> int:
    """Count bars that tested `level` without decisively breaking it.

    Standalone form of the third-test question, for callers that hold a level
    rather than a detected pattern. Returns 0 when fewer than `min_tests` are
    found, so the threshold lives in one place.
    """
    cfg = config or AnalyzerConfig()
    if atr <= 0 or last_closed < 0 or last_closed >= len(bars):
        return 0
    tol = cfg.double_tol_atr * atr
    start = max(0, last_closed - window + 1)
    count = 0
    for i in range(start, min(last_closed, len(bars) - 1) + 1):
        _, h, low_val, c = _get_ohlc(bars[i])
        if is_resistance:
            if h >= level - tol and c <= level + tol:
                count += 1
        else:
            if low_val <= level + tol and c >= level - tol:
                count += 1
    return count if count >= min_tests else 0


def find_major_double_top_with_context(
    swings: Sequence[SwingPoint | dict[str, Any]],
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> DoublePattern:
    """Major double top with test and breakout context filled in."""
    cfg = config or AnalyzerConfig()
    return classify_double_context(
        find_major_double_top(swings, atr, cfg), bars, last_closed, atr, cfg
    )


def find_major_double_bottom_with_context(
    swings: Sequence[SwingPoint | dict[str, Any]],
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> DoublePattern:
    """Major double bottom with test and breakout context filled in."""
    cfg = config or AnalyzerConfig()
    return classify_double_context(
        find_major_double_bottom(swings, atr, cfg), bars, last_closed, atr, cfg
    )


def detect_micro_double_top_with_context(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> DoublePattern:
    """Micro double top with test and breakout context filled in."""
    cfg = config or AnalyzerConfig()
    return classify_double_context(
        detect_micro_double_top(bars, idx, last_closed, atr, cfg), bars, last_closed, atr, cfg
    )


def detect_micro_double_bottom_with_context(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> DoublePattern:
    """Micro double bottom with test and breakout context filled in."""
    cfg = config or AnalyzerConfig()
    return classify_double_context(
        detect_micro_double_bottom(bars, idx, last_closed, atr, cfg),
        bars,
        last_closed,
        atr,
        cfg,
    )
