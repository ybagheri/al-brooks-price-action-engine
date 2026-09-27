"""H1/H2 and L1/L2 pullback detection, with an explicit lifecycle.

A pullback is not a single event. It begins, develops through one or two
counter-trend attempts, either resumes in the trend direction or breaks down.
Collapsing that into a single boolean throws away most of what a trader
actually watches for, so this module reports a **state**:

```text
NONE  ->  CANDIDATE  ->  PROVISIONAL  ->  CONFIRMED
                  \\->  INVALIDATED   (from any non-terminal state)
```

| State | Meaning |
|---|---|
| `CANDIDATE` | A pullback window is open but no counter-trend leg has completed. |
| `PROVISIONAL` | One counter-trend leg completed (H1 / L1). |
| `CONFIRMED` | A second leg completed and the trend resumed (H2 / L2). |
| `INVALIDATED` | The structure the pullback depended on broke. |

Classification: the counting rules are `ALGORITHMIC`; the depth bands that decide
whether a counter-move still counts as a pullback are `HEURISTIC`; the
perceived reliability of an H2 versus an H1 is **not claimed anywhere here**.

What this does NOT claim: that a `CONFIRMED` H2 is more likely to work than a
`PROVISIONAL` H1. That ordering is a hypothesis for out-of-sample testing, not
a property this engine measures. `state` is a description of the structure, not
a rating.

Implementation note: `detect_h1_h2` and `detect_l1_l2` were near-verbatim mirror
images of each other. They now share one `_classify` implementation, so a
correction cannot land in one direction and miss the other.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Sequence

from albrooks.context.market_state import calculate_trend_gap
from albrooks.core.bars import Bar, BarSeries
from albrooks.engine.configuration import AnalyzerConfig


class PullbackState(str, Enum):
    """Lifecycle position of a pullback."""

    NONE = "NONE"
    CANDIDATE = "CANDIDATE"
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True, slots=True)
class PullbackSetup:
    found: bool = False
    setup_type: str = "NONE"  # H1, H2, L1, L2
    legs: int = 0
    signal_bar: int = -1
    anchor_bar: int = -1
    reference_price: float = 0.0
    stop_price: float = 0.0
    direction: int = 0  # +1 Bull (H1/H2), -1 Bear (L1/L2)
    state: str = PullbackState.NONE.value
    extreme_bar: int = -1  # bar holding the extreme the pullback must respect
    extreme_price: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_confirmed(self) -> bool:
        return self.state == PullbackState.CONFIRMED.value

    @property
    def is_invalidated(self) -> bool:
        return self.state == PullbackState.INVALIDATED.value


def _get_ohlc(b: Bar | dict[str, Any]) -> tuple[float, float, float, float]:
    if isinstance(b, Bar):
        return b.open, b.high, b.low, b.close
    return (
        float(b.get("o", b.get("open", 0.0))),
        float(b.get("h", b.get("high", 0.0))),
        float(b.get("l", b.get("low", 0.0))),
        float(b.get("c", b.get("close", 0.0))),
    )


def determine_trend_direction(
    bars: Sequence[Bar | dict[str, Any]],
    idx: int,
    last_closed: int,
    atr: float,
) -> int:
    """Context gate: is there a trend strong enough to pull back in?

    Uses the normalised EMA20/EMA50 gap. This is a `PROXY` for "is there a
    trend at all", not a claim that a trend exists.
    """
    if idx < 0 or idx > last_closed or idx >= len(bars) or atr <= 0:
        return 0
    t_gap = calculate_trend_gap(bars, idx) / atr
    if t_gap > 0.4:
        return 1
    if t_gap < -0.4:
        return -1
    return 0


def _classify(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    direction: int,
    config: AnalyzerConfig | None = None,
) -> PullbackSetup:
    """Shared H1/H2 and L1/L2 classification.

    `direction` is the trend direction: `+1` for a bull pullback (H1/H2),
    `-1` for a bear pullback (L1/L2). The bull and bear cases are the same
    algorithm with the sign flipped; they are written once, here.
    """
    cfg = config or AnalyzerConfig()
    if direction not in (1, -1):
        return PullbackSetup()
    if idx < 0 or idx > last_closed or idx >= len(bars) or atr <= 0:
        return PullbackSetup()
    if determine_trend_direction(bars, idx, last_closed, atr) != direction:
        return PullbackSetup()

    up = direction > 0
    entry_1 = "H1" if up else "L1"
    entry_2 = "H2" if up else "L2"

    w0 = max(0, idx - cfg.max_pb_bars)
    if w0 + 1 > idx:
        return PullbackSetup()

    highs = [_get_ohlc(bars[i])[1] for i in range(w0, idx + 1)]
    lows = [_get_ohlc(bars[i])[2] for i in range(w0, idx + 1)]
    mxh, mnl = max(highs), min(lows)
    if (mxh - mnl) < cfg.min_pb_ratio * atr:
        return PullbackSetup()

    def _made_extreme(i: int) -> bool:
        """Bar `i` extended further in the counter-trend direction."""
        if up:
            return _get_ohlc(bars[i])[1] > _get_ohlc(bars[i - 1])[1]
        return _get_ohlc(bars[i])[2] < _get_ohlc(bars[i - 1])[2]

    def _broke_extreme(i: int) -> bool:
        """Bar `i` extended further in the trend direction."""
        if up:
            return _get_ohlc(bars[i])[2] < _get_ohlc(bars[i - 1])[2]
        return _get_ohlc(bars[i])[1] > _get_ohlc(bars[i - 1])[1]

    def _first_extreme(start: int, test: Any) -> int:
        for i in range(start, idx + 1):
            if test(i):
                return i
        return -1

    def _anchor_price(bar: int) -> float:
        return _get_ohlc(bars[bar])[1] if up else _get_ohlc(bars[bar])[2]

    def _extreme_price(bar: int) -> float:
        return _get_ohlc(bars[bar])[2] if up else _get_ohlc(bars[bar])[1]

    # The pullback window is open as soon as it spans a meaningful range, but
    # until a counter-trend leg completes the state is only CANDIDATE.
    leg1 = _first_extreme(w0 + 1, _made_extreme)
    if leg1 < 0:
        return PullbackSetup(
            found=True,
            setup_type=entry_1,
            legs=0,
            state=PullbackState.CANDIDATE.value,
            direction=direction,
            anchor_bar=-1,
            extreme_bar=idx,
            extreme_price=_extreme_price(idx),
            stop_price=mnl if up else mxh,
        )

    # Counter-move between the first entry and the next attempt.
    level_at_1 = min(_get_ohlc(bars[i])[2] for i in range(w0, leg1 + 1)) if up else max(
        _get_ohlc(bars[i])[1] for i in range(w0, leg1 + 1)
    )

    def _deepened(i: int) -> bool:
        if up:
            return _get_ohlc(bars[i])[2] < level_at_1
        return _get_ohlc(bars[i])[1] > level_at_1

    leg2_low = _first_extreme(leg1 + 1, _deepened)
    if leg2_low < 0:
        return PullbackSetup(
            found=True,
            setup_type=entry_1,
            legs=1,
            signal_bar=leg1,
            anchor_bar=leg1,
            reference_price=_anchor_price(leg1),
            state=PullbackState.PROVISIONAL.value,
            direction=direction,
            extreme_bar=leg1,
            extreme_price=_extreme_price(leg1),
            stop_price=mnl if up else mxh,
        )

    # A second counter-trend leg has formed. If the trend has not resumed the
    # setup is still provisional -- this is the case the old implementation
    # mislabelled as a completed H1.
    resumption = _first_extreme(leg2_low + 1, _made_extreme)
    extreme_bar = leg2_low
    extreme_price = _extreme_price(leg2_low)
    if resumption < 0:
        return PullbackSetup(
            found=True,
            setup_type=entry_2,
            legs=2,
            signal_bar=-1,
            anchor_bar=leg1,
            reference_price=0.0,
            state=PullbackState.PROVISIONAL.value,
            direction=direction,
            extreme_bar=extreme_bar,
            extreme_price=extreme_price,
            stop_price=mnl if up else mxh,
        )

    return PullbackSetup(
        found=True,
        setup_type=entry_2,
        legs=2,
        signal_bar=resumption,
        anchor_bar=leg1,
        reference_price=_anchor_price(resumption),
        state=PullbackState.CONFIRMED.value,
        direction=direction,
        extreme_bar=extreme_bar,
        extreme_price=extreme_price,
        stop_price=mnl if up else mxh,
    )


def detect_h1_h2(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> PullbackSetup:
    """Detect a bull-pullback H1/H2 setup. Mirrors `detect_l1_l2` exactly."""
    return _classify(bars, idx, last_closed, atr, 1, config)


def detect_l1_l2(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> PullbackSetup:
    """Detect a bear-pullback L1/L2 setup. Mirrors `detect_h1_h2` exactly."""
    return _classify(bars, idx, last_closed, atr, -1, config)


def is_invalidated(setup: PullbackSetup, bars: Sequence[Bar | dict[str, Any]], idx: int) -> bool:
    """Has price closed beyond the extreme the pullback depended on?

    This is the check a caller makes on a **subsequent** bar: a setup carries
    the extreme it was built on, and once price closes past that extreme the
    structure the pullback relied on no longer holds.
    """
    if setup.extreme_bar < 0 or idx < 0 or idx >= len(bars) or not setup.found:
        return False
    if idx <= setup.extreme_bar:
        return False
    close = _get_ohlc(bars[idx])[3]
    if setup.direction > 0:
        return close < setup.extreme_price
    return close > setup.extreme_price


def apply_invalidation(
    setup: PullbackSetup,
    bars: Sequence[Bar | dict[str, Any]],
    idx: int,
) -> PullbackSetup:
    """Return the setup marked `INVALIDATED` if its structure has broken."""
    if not is_invalidated(setup, bars, idx):
        return setup
    return PullbackSetup(
        found=setup.found,
        setup_type=setup.setup_type,
        legs=setup.legs,
        signal_bar=setup.signal_bar,
        anchor_bar=setup.anchor_bar,
        reference_price=setup.reference_price,
        stop_price=setup.stop_price,
        direction=setup.direction,
        state=PullbackState.INVALIDATED.value,
        extreme_bar=setup.extreme_bar,
        extreme_price=setup.extreme_price,
    )
