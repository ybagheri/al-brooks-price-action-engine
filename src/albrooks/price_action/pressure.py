"""Directional pressure: consecutive runs and cumulative strong-bar counts.

"Pressure" in price action is psychological -- the accumulation of buying or
selling intent inferred from tails and closes. It is not directly observable.
What is observable is the count of bars that closed strongly in one direction,
and the length of consecutive directional runs. Both are used here as
`PROXY` stand-ins.

The run primitives live in this module rather than in `core/structures.py`
because wedge and exhaustion detection both need them, and putting them here
keeps the dependency one-directional: structures depend on price-action
features, never the reverse.
"""

from __future__ import annotations

from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries

#: Cap on how far back a single run is scanned.
MAX_RUN_SCAN: int = 6


def _get_ohlc(b: Bar | dict[str, Any]) -> tuple[float, float, float, float]:
    if isinstance(b, Bar):
        return b.open, b.high, b.low, b.close
    return (
        float(b.get("o", b.get("open", 0.0))),
        float(b.get("h", b.get("high", 0.0))),
        float(b.get("l", b.get("low", 0.0))),
        float(b.get("c", b.get("close", 0.0))),
    )


def _dir(b: Bar | dict[str, Any]) -> int:
    o, _, _, c = _get_ohlc(b)
    return 1 if c > o else (-1 if c < o else 0)


def push_count_back(
    bars: Sequence[Bar | dict[str, Any]],
    idx: int,
    last_closed: int,
    direction: int,
    limit: int = MAX_RUN_SCAN,
) -> int:
    """Consecutive closes (and extremes) toward `direction`, ending at `idx`.

    A bull push requires each bar to close higher *and* make a higher high than
    its predecessor; a bear push mirrors that. This is stricter than counting
    bar direction alone, which is deliberate: it excludes bars that closed
    strongly but failed to extend.

    `OBJECTIVE` as a count. Interpreting it as "momentum" is an `INTERPRETATION`.
    """
    if idx < 0 or idx > last_closed or idx >= len(bars):
        return 0
    if direction not in (1, -1):
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
        if n >= limit:
            break
        i -= 1
    return n


def _is_doji(b: Bar | dict[str, Any], doji_max_body: float) -> bool:
    o, h, low_val, c = _get_ohlc(b)
    rg = h - low_val
    rg = rg if rg > 0.0 else 1e-9
    return abs(c - o) / rg < doji_max_body


def consecutive_run(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    max_run: int = 20,
    doji_max_body: float = 0.15,
) -> int:
    """Signed run length of same-direction bars ending at `idx`.

    Positive for a bull run, negative for a bear run, zero for a doji or an
    empty run.

    A doji **at `idx`** ends the run: Brooks treats a doji as a pause rather
    than continuation, so a doji bar reports a run of zero instead of being
    counted as another push.

    A doji *inside* the scanned window is counted like any other bar, because
    the run is a property of bar direction. Truncating on interior dojis would
    understate a run that genuinely continued through a pause, and would make
    the count sensitive to a threshold rather than to the data.
    """
    if idx < 0 or idx >= len(bars):
        return 0
    if _is_doji(bars[idx], doji_max_body):
        return 0
    direction = _dir(bars[idx])
    if direction == 0:
        return 0
    n = 0
    for i in range(idx, -1, -1):
        if i > last_closed or i >= len(bars):
            continue
        if _dir(bars[i]) != direction:
            break
        n += 1
        if n >= max_run:
            break
    return n if direction > 0 else -n


def count_pressure(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    lookback: int = 10,
    strong_close_pct: float = 0.70,
    min_body_pct: float = 0.30,
) -> tuple[int, int]:
    """Count strong bull vs strong bear bars over the lookback window.

    A bar is *strong bull* when it closes in the top `strong_close_pct` of its
    range and its body is at least `min_body_pct` of that range; strong bear
    mirrors it. Returns `(bull_count, bear_count)`.
    """
    if idx < 0 or idx >= len(bars):
        return 0, 0
    n = max(1, lookback)
    bull = bear = 0
    for i in range(idx, max(-1, idx - n), -1):
        if i < 0 or i > last_closed or i >= len(bars):
            continue
        o, h, low_val, c = _get_ohlc(bars[i])
        rg = max(h - low_val, 1e-9)
        direction = 1 if c > o else (-1 if c < o else 0)
        close_pos = (c - low_val) / rg
        body_ratio = abs(c - o) / rg
        if direction > 0 and close_pos >= strong_close_pct and body_ratio >= min_body_pct:
            bull += 1
        if (
            direction < 0
            and (1.0 - close_pos) >= strong_close_pct
            and body_ratio >= min_body_pct
        ):
            bear += 1
    return bull, bear
