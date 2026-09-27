r"""Breakout state machine, traps, and pullbacks.

The state machine is:

```text
NONE -> PENDING -> BREAKOUT -> FOLLOW_THROUGH
                  \-> FAILED
```

`BREAKOUT` is the bar the reference was actually cleared on; `PENDING` is a
break detected on an earlier bar that has not yet resolved either way. Keeping
those two distinct matters, because a caller acting on the breakout bar is
acting before any follow-through exists.

`outcome` is retained as the historical field (`PENDING` / `FOLLOW` / `FAILED`)
and `state` carries the fuller machine.

Also here: the **second-leg trap** (a breakout's second leg reverses back
through the reference, taking out late followers) and the **breakout pullback**
(price returns toward the reference and holds above it).

Classification: reference selection and state transitions are `ALGORITHMIC`;
the `0.10 * ATR` tolerance is a `HEURISTIC`; what any of this implies about
future direction is **not claimed**.

What this does NOT claim: that `FOLLOW_THROUGH` is more likely to continue than
`FAILED` is to reverse, or that a second-leg trap is a reliable short. Those are
hypotheses for out-of-sample testing. `state` describes what price did.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.core.channels import PriceChannel
from albrooks.core.swings import SwingPoint
from albrooks.engine.configuration import AnalyzerConfig


class BreakoutState(str, Enum):
    """Position in the breakout state machine."""

    NONE = "NONE"
    PENDING = "PENDING"
    BREAKOUT = "BREAKOUT"
    FOLLOW_THROUGH = "FOLLOW_THROUGH"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class BreakoutResult:
    found: bool = False
    direction: int = 0
    breakout_bar: int = -1
    reference_price: float = 0.0
    ref_is_swing: bool = False
    outcome: str = "NONE"  # PENDING, FOLLOW, FAILED, NONE (historical)
    trap: bool = False
    decide_bar: int = -1
    state: str = BreakoutState.NONE.value
    reference_kind: str = "NONE"  # SWING, N_BAR, RANGE, CHANNEL
    second_leg_trap: bool = False
    second_leg_bar: int = -1
    pullback_bar: int = -1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_bull(self) -> bool:
        return self.direction == 1

    @property
    def is_bear(self) -> bool:
        return self.direction == -1

    @property
    def is_resolved(self) -> bool:
        return self.state in (BreakoutState.FOLLOW_THROUGH.value, BreakoutState.FAILED.value)


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

    # A swing reference takes precedence over the N-bar reference when both
    # would qualify, so it is tested first.
    bull_ref: float | None = None
    bull_is_swing = False
    if sh is not None and c > sh + tol:
        bull_ref, bull_is_swing = sh, True
    elif nb is not None and c > nb[0] + tol:
        bull_ref, bull_is_swing = nb[0], False
    if bull_ref is not None:
        return 1, bull_ref, bull_is_swing

    bear_ref: float | None = None
    bear_is_swing = False
    if sl is not None and c < sl - tol:
        bear_ref, bear_is_swing = sl, True
    elif nb is not None and c < nb[1] - tol:
        bear_ref, bear_is_swing = nb[1], False
    if bear_ref is not None:
        return -1, bear_ref, bear_is_swing

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

    leg2_bar = detect_second_leg_trap(bars, k, last_closed, ref, direction, tol)
    pullback_bar = detect_breakout_pullback(bars, k, last_closed, ref, direction, tol)

    # The state machine distinguishes "this bar cleared the reference" from
    # "an earlier bar cleared it and nothing has resolved yet".
    if outcome == "FAILED":
        state = BreakoutState.FAILED.value
    elif outcome == "FOLLOW":
        state = BreakoutState.FOLLOW_THROUGH.value
    elif idx == k:
        state = BreakoutState.BREAKOUT.value
    else:
        state = BreakoutState.PENDING.value

    return BreakoutResult(
        found=True,
        direction=direction,
        breakout_bar=k,
        reference_price=ref,
        ref_is_swing=is_sw,
        outcome=outcome,
        trap=trap,
        decide_bar=decide_bar,
        state=state,
        reference_kind="SWING" if is_sw else "N_BAR",
        second_leg_trap=leg2_bar >= 0,
        second_leg_bar=leg2_bar,
        pullback_bar=pullback_bar,
    )


def detect_second_leg_trap(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    breakout_bar: int,
    last_closed: int,
    reference: float,
    direction: int,
    tol: float,
    max_bars: int = 10,
) -> int:
    """Bar at which a second leg reversed back through the reference, else -1.

    A breakout's second leg is the move that lures in late followers. If price
    extends beyond the reference, then reverses and closes back on the original
    side, the late followers are trapped. Returns the reclaim bar.
    """
    if direction not in (1, -1) or breakout_bar < 0 or last_closed >= len(bars):
        return -1
    upper = min(last_closed, breakout_bar + max_bars)

    extended = -1
    for i in range(breakout_bar, upper + 1):
        c = _get_ohlc(bars[i])[3]
        beyond = c > reference + tol if direction > 0 else c < reference - tol
        if beyond:
            extended = i
        elif extended >= 0:
            back = c < reference - tol if direction > 0 else c > reference + tol
            if back:
                return i
    return -1


def detect_breakout_pullback(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    breakout_bar: int,
    last_closed: int,
    reference: float,
    direction: int,
    tol: float,
    max_bars: int = 10,
) -> int:
    """Bar of the pullback back toward the reference that still held, else -1.

    A pullback into a breakout is the retest. It is recorded when price comes
    back within `tol` of the reference on the broken side **without** closing
    through it -- a close back through is a failure, not a pullback, and is
    reported as such by the state machine instead.
    """
    if direction not in (1, -1) or breakout_bar < 0 or last_closed >= len(bars):
        return -1
    upper = min(last_closed, breakout_bar + max_bars)
    for i in range(breakout_bar + 1, upper + 1):
        c = _get_ohlc(bars[i])[3]
        through = c < reference - tol if direction > 0 else c > reference + tol
        if through:
            return -1  # failed, not a pullback
        near = abs(c - reference) <= tol
        if near:
            return i
    return -1


def detect_channel_breakout(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    channel: PriceChannel,
    tol_atr: float = 0.10,
    atr: float = 0.0,
) -> BreakoutResult:
    """Detect a close beyond a channel boundary.

    The channel is projected forward from its own last touchpoint, so a break is
    measured against the boundary as it stood at that bar rather than at a
    window edge that would move.
    """
    if channel.direction == 0 or channel.last_touch_bar < 0:
        return BreakoutResult()
    if idx < 0 or idx > last_closed or idx >= len(bars):
        return BreakoutResult()
    tol = tol_atr * atr if atr > 0 else 0.0

    close = _get_ohlc(bars[idx])[3]
    offset = idx - channel.last_touch_bar
    upper = channel.upper_price + channel.upper_slope * offset
    lower = channel.lower_price + channel.lower_slope * offset

    if close > upper + tol:
        return BreakoutResult(
            found=True,
            direction=1,
            breakout_bar=idx,
            reference_price=upper,
            ref_is_swing=False,
            outcome="PENDING",
            state=BreakoutState.BREAKOUT.value,
            reference_kind="CHANNEL",
        )
    if close < lower - tol:
        return BreakoutResult(
            found=True,
            direction=-1,
            breakout_bar=idx,
            reference_price=lower,
            ref_is_swing=False,
            outcome="PENDING",
            state=BreakoutState.BREAKOUT.value,
            reference_kind="CHANNEL",
        )
    return BreakoutResult()
