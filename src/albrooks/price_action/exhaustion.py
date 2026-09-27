"""Exhaustion: several independent signs that a move may be ending.

Five conditions are measured, each separately, and then counted. **No single one
is a reversal signal**, and the count is not a probability.

| Condition | Test | Label |
|---|---|---|
| `climax` | `range >= big_bar_atr * ATR` | `HEURISTIC` |
| `stall` | small range with tails on both sides | `HEURISTIC` |
| `push_ok` | `pushes >= max(2, min_pushes)` toward `direction` | `ALGORITHMIC` |
| `wedge` | decelerating run (see `wedges.py`) | `PROXY` |
| `overshoot` | extreme beyond a 20-bar SMA band by `> 0.3 ATR` | `PROXY` |

The overshoot band is:

```text
bull: high  > max(SMA20, HH - 0.2 * (HH - LL)) + 0.3 * ATR
bear: low   < min(SMA20, LL + 0.2 * (HH - LL)) - 0.3 * ATR
```

which measures extension past the recent range once 20 bars of history exist.

What this does **not** claim: exhaustion is not a reversal. A strong trend
produces climax bars repeatedly and keeps going. `breadth` is a count of
measured conditions, nothing more.

Moved here from `core/structures.py`, which re-exports these names.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.price_action.climaxes import is_climax, is_stall
from albrooks.price_action.pressure import push_count_back
from albrooks.price_action.wedges import detect_wedge

#: Bars of history required before an overshoot can be measured.
OVERSHOOT_WINDOW: int = 20
#: Share of the recent range that counts as the "normal" band.
OVERSHOOT_BAND: float = 0.2
#: How far past the band an extreme must sit, in ATR.
OVERSHOOT_ATR: float = 0.3


@dataclass(frozen=True, slots=True)
class ExhaustionStructure:
    """A composite structural observation. Facts, not a signal."""

    bar_index: int
    direction: int
    climax: bool = False
    stall: bool = False
    pushes: int = 0
    push_ok: bool = False
    wedge: bool = False
    overshoot: bool = False
    breadth: int = 0

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


def detect_overshoot(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    direction: int,
    atr: float,
    window: int = OVERSHOOT_WINDOW,
) -> bool:
    """True when the bar's extreme sits past the recent range band.

    Needs `window` bars of history ending at `idx`; returns False without it.
    """
    if atr <= 0 or idx - window + 1 < 0 or idx >= len(bars):
        return False
    win = bars[idx - window + 1: idx + 1]
    closes = [_get_ohlc(x)[3] for x in win]
    highs = [_get_ohlc(x)[1] for x in win]
    lows = [_get_ohlc(x)[2] for x in win]
    sma = sum(closes) / float(window)
    hh, ll = max(highs), min(lows)
    span = hh - ll
    h, low_val = highs[-1], lows[-1]
    if direction > 0:
        return (h - max(sma, hh - span * OVERSHOOT_BAND)) > OVERSHOOT_ATR * atr
    return (min(sma, ll + span * OVERSHOOT_BAND) - low_val) > OVERSHOOT_ATR * atr


def detect_exhaustion(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    direction: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> ExhaustionStructure:
    """Measure all five exhaustion conditions at `idx`."""
    cfg = config or AnalyzerConfig()
    if idx < 0 or idx > last_closed or idx >= len(bars) or atr <= 0:
        return ExhaustionStructure(bar_index=idx, direction=direction)

    bar = bars[idx]
    climax = is_climax(bar, atr, cfg.big_bar_atr)
    stall = is_stall(bar, atr, cfg.small_bar_atr)
    pushes = push_count_back(bars, idx, last_closed, direction)
    push_ok = pushes >= max(2, cfg.min_pushes)
    wedge = bool(cfg.use_wedge and detect_wedge(bars, idx, last_closed, direction))
    overshoot = detect_overshoot(bars, idx, direction, atr)

    breadth = sum([climax, stall, push_ok, wedge, overshoot])
    return ExhaustionStructure(
        bar_index=idx,
        direction=direction,
        climax=climax,
        stall=stall,
        pushes=pushes,
        push_ok=push_ok,
        wedge=wedge,
        overshoot=overshoot,
        breadth=breadth,
    )
