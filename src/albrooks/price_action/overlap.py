"""Bar-to-bar overlap: how much two bars trade in the same territory.

`OBJECTIVE`: these are geometric comparisons of OHLC values. There is no
judgement here, only arithmetic. What a high overlap *means* is decided
elsewhere (see `channel.py` for the chop proxy).

Historically these lived in `price_action/bars.py`, which had grown to hold
seven unrelated responsibilities. They are re-exported from there for backward
compatibility.
"""

from __future__ import annotations

from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries


def _get_ohlc(b: Bar | dict[str, Any]) -> tuple[float, float, float, float]:
    if isinstance(b, Bar):
        return b.open, b.high, b.low, b.close
    return (
        float(b.get("o", b.get("open", 0.0))),
        float(b.get("h", b.get("high", 0.0))),
        float(b.get("l", b.get("low", 0.0))),
        float(b.get("c", b.get("close", 0.0))),
    )


def _range(b: Bar | dict[str, Any]) -> float:
    _, h, low_val, _ = _get_ohlc(b)
    rg = h - low_val
    return rg if rg > 0.0 else 1e-9


def _body(b: Bar | dict[str, Any]) -> float:
    o, _, _, c = _get_ohlc(b)
    return abs(c - o)


def pair_overlap(a: Bar | dict[str, Any], b: Bar | dict[str, Any]) -> float:
    """Fraction of the smaller bar's range that both bars share.

    The shared portion of the two bodies, divided by the smaller range:

    ```text
    top     = min(max(close_a, open_a), max(close_b, open_b))
    bottom  = max(min(close_a, open_a), min(close_b, open_b))
    overlap = max(0, top - bottom) / min(range_a, range_b)
    ```
    """
    ao, ah, al, ac = _get_ohlc(a)
    bo, bh, bl, bc = _get_ohlc(b)
    m = min(ah - al, bh - bl)
    if m <= 0.0:
        return 0.0
    top = min(max(ac, ao), max(bc, bo))
    bottom = max(min(ac, ao), min(bc, bo))
    return max(0.0, (top - bottom) / m)


def is_inside_bar(
    bar: Bar | dict[str, Any], prev: Bar | dict[str, Any]
) -> bool:
    """`bar` is fully contained within `prev`."""
    _, h, low_val, _ = _get_ohlc(bar)
    _, ph, pl, _ = _get_ohlc(prev)
    return h <= ph and low_val >= pl


def is_outside_bar(
    bar: Bar | dict[str, Any], prev: Bar | dict[str, Any]
) -> bool:
    """`bar` fully engulfs `prev`, with at least one strict inequality."""
    _, h, low_val, _ = _get_ohlc(bar)
    _, ph, pl, _ = _get_ohlc(prev)
    return (h >= ph and low_val <= pl) and (h > ph or low_val < pl)


def count_inside_run(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
) -> int:
    """Length of the consecutive inside-bar run ending at `idx`."""
    if idx <= 0 or idx >= len(bars):
        return 0
    n = 0
    for i in range(idx, 0, -1):
        if i > last_closed or i >= len(bars):
            continue
        if is_inside_bar(bars[i], bars[i - 1]):
            n += 1
        else:
            break
    return n


def detect_barbwire(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    window: int = 5,
    min_overlap: int = 3,
    overlap_ratio: float = 0.5,
    doji_max_body: float = 0.15,
) -> bool:
    """`PROXY` for "no clear direction, both sides being hit".

    True when at least `min_overlap` consecutive bar pairs in the window
    overlap by `overlap_ratio` or more, **and** the window contains a doji.

    The doji requirement is what keeps this from firing on ordinary trending
    overlap. It remains a proxy: real barbwire is a visual judgement about both
    sides being probed, and a tight one-sided channel can satisfy these
    conditions without being barbwire.
    """
    if idx < 0 or idx >= len(bars):
        return False
    w = max(3, window)
    overlapping = 0
    any_doji = False
    for i in range(idx, max(-1, idx - w), -1):
        if i <= 0 or i > last_closed or i >= len(bars):
            continue
        if pair_overlap(bars[i], bars[i - 1]) >= overlap_ratio:
            overlapping += 1
        if _body(bars[i]) / _range(bars[i]) < doji_max_body:
            any_doji = True
    tail = idx - w
    if 0 <= tail <= last_closed and tail < len(bars):
        if _body(bars[tail]) / _range(bars[tail]) < doji_max_body:
            any_doji = True
    return overlapping >= min_overlap and any_doji
