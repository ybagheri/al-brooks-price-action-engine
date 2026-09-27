"""Climax and stall bars: the two extremes of bar character.

A **climax** is a very large bar. A **stall** is a very small bar with wicks on
both sides. Brooks reads both as pauses or exhaustion rather than continuation,
but that reading is a judgement.

What is measurable:

$$\\text{Climax}: \\quad \\text{range} \\geq \\text{big\\_bar\\_atr} \\times ATR$$

$$\\text{Stall}: \\quad \\text{range} < \\text{small\\_bar\\_atr} \\times ATR$$

with, in addition, both tails covering more than a `wick_fraction` (0.4) of the
range. The ATR multiples and the wick fraction are `HEURISTIC` values chosen by
this project, configurable via `AnalyzerConfig`. The measurements are
`OBJECTIVE`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from albrooks.core.bars import Bar

#: Minimum share of the range that each tail must cover to read as a stall.
STALL_WICK_FRACTION: float = 0.4


@dataclass(frozen=True, slots=True)
class BarCharacter:
    """Measured character of a single bar, independent of context."""

    range: float = 0.0
    body: float = 0.0
    body_ratio: float = 0.0
    upper_tail: float = 0.0
    lower_tail: float = 0.0
    direction: int = 0
    is_climax: bool = False
    is_stall: bool = False
    is_doji: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get_ohlc(b: Bar | dict[str, Any]) -> tuple[float, float, float, float]:
    if isinstance(b, Bar):
        return b.open, b.high, b.low, b.close
    return (
        float(b.get("o", b.get("open", 0.0))),
        float(b.get("h", b.get("high", 0.0))),
        float(b.get("l", b.get("low", 0.0))),
        float(b.get("c", b.get("close", 0.0))),
    )


def measure_bar(
    bar: Bar | dict[str, Any],
    atr: float = 0.0,
    big_bar_atr: float = 2.0,
    small_bar_atr: float = 0.5,
    doji_max_body: float = 0.15,
    wick_fraction: float = STALL_WICK_FRACTION,
) -> BarCharacter:
    """Measure a bar's character, including climax and stall classification.

    With `atr <= 0` the ATR-relative classifications are skipped, because there
    is nothing to be relative to. The size-independent measurements are still
    reported.
    """
    o, h, low_val, c = _get_ohlc(bar)
    rg = h - low_val
    rg = rg if rg > 0.0 else 1e-9
    body = abs(c - o)
    upper = h - max(c, o)
    lower = min(c, o) - low_val
    body_ratio = body / rg
    direction = 1 if c > o else (-1 if c < o else 0)

    is_climax = atr > 0 and rg >= big_bar_atr * atr
    is_stall = (
        atr > 0
        and rg < small_bar_atr * atr + 1e-9
        and upper > wick_fraction * rg
        and lower > wick_fraction * rg
    )
    return BarCharacter(
        range=h - low_val,
        body=body,
        body_ratio=body_ratio,
        upper_tail=upper,
        lower_tail=lower,
        direction=direction,
        is_climax=is_climax,
        is_stall=is_stall,
        is_doji=body_ratio < doji_max_body,
    )


def is_climax(
    bar: Bar | dict[str, Any],
    atr: float,
    big_bar_atr: float = 2.0,
) -> bool:
    """True when the bar's range is at least `big_bar_atr` ATR."""
    if atr <= 0:
        return False
    _, h, low_val, _ = _get_ohlc(bar)
    return (h - low_val) >= big_bar_atr * atr


def is_stall(
    bar: Bar | dict[str, Any],
    atr: float,
    small_bar_atr: float = 0.5,
    wick_fraction: float = STALL_WICK_FRACTION,
) -> bool:
    """True when the bar is small relative to ATR and wicks on both sides."""
    if atr <= 0:
        return False
    o, h, low_val, c = _get_ohlc(bar)
    rg = h - low_val
    if rg >= small_bar_atr * atr + 1e-9:
        return False
    upper = h - max(c, o)
    lower = min(c, o) - low_val
    return upper > wick_fraction * rg and lower > wick_fraction * rg
