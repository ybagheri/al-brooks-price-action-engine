"""Second-entry structure: two attempts at the same direction, separated by a pause.

The idea, in Brooks' terms, is that a first move often fails and a *second*
attempt in the same direction is more meaningful, because it is made after the
market has had a chance to prove the first one wrong.

The pattern measured here, oldest to newest, is:

```text
   push (entry 1)  ->  counter-move  ->  push (entry 2)
```

Entry 2 is the run ending at the analysis bar. Entry 1 is the run that preceded
the counter-move. The counter-move must be at least `min_pullback_atr` ATR deep,
which is what separates a genuine second entry from two bars in a row going the
same way.

Classification: `ALGORITHMIC` for the geometry. That a second entry is more
reliable than a first is an `INTERPRETATION`, and is **not** claimed here --
this module only reports that the structure is present.

Limitations:
* The counter-move depth and maximum separation are chosen values.
* `extends` is measured and reported, not required, so a second entry that fails
  to exceed the first extreme is still a second entry.
* Two entries is a small sample. This is a structural observation, not evidence
  of an edge.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.price_action.pressure import push_count_back

#: Counter-move depth, in ATR, required between the two entries.
DEFAULT_MIN_PULLBACK_ATR: float = 0.5
#: Largest number of bars allowed between the two entries.
DEFAULT_MAX_SEPARATION: int = 10


@dataclass(frozen=True, slots=True)
class SecondEntry:
    """Two same-direction pushes separated by a counter-move."""

    found: bool = False
    direction: int = 0  # +1 second bull entry, -1 second bear entry
    first_bar: int = -1
    second_bar: int = -1
    pullback_bars: int = 0
    separation_bars: int = 0
    pullback_size: float = 0.0
    entry1_extreme: float = 0.0
    entry2_extreme: float = 0.0
    extends: bool = False

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


def _counter_run(
    bars: Sequence[Bar | dict[str, Any]],
    end_bar: int,
    direction: int,
    max_len: int,
) -> int:
    """Length of the counter-direction run ending at `end_bar`."""
    n = 0
    i = end_bar
    while i >= 1 and n < max_len:
        _, curr_h, curr_l, curr_c = _get_ohlc(bars[i])
        _, prev_h, prev_l, prev_c = _get_ohlc(bars[i - 1])
        if direction > 0:
            if not (curr_c < prev_c and curr_l < prev_l):
                break
        else:
            if not (curr_c > prev_c and curr_h > prev_h):
                break
        n += 1
        i -= 1
    return n


def detect_second_entry(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    direction: int,
    atr: float,
    min_pullback_atr: float = DEFAULT_MIN_PULLBACK_ATR,
    max_separation: int = DEFAULT_MAX_SEPARATION,
) -> SecondEntry:
    """Detect `push -> counter-move -> push` ending at bar `idx`.

    Requires a valid `direction` and `atr > 0`. Returns a not-found result
    rather than guessing when the structure is absent.
    """
    if direction not in (1, -1) or atr <= 0 or idx < 1 or idx > last_closed:
        return SecondEntry(direction=direction)
    n_bars = len(bars)
    if idx >= n_bars:
        return SecondEntry(direction=direction)

    min_pullback = min_pullback_atr * atr
    window = max(2, max_separation)

    # Entry 2 is the directional run that ends at idx.
    entry2_len = push_count_back(bars, idx, last_closed, direction, limit=window)
    if entry2_len < 1:
        return SecondEntry(direction=direction)
    second_bar = idx - entry2_len + 1

    # The counter-move separates the two entries.
    pb_len = _counter_run(bars, second_bar - 1, direction, window)
    if pb_len < 1:
        return SecondEntry(direction=direction)

    first_bar = second_bar - pb_len - 1
    if first_bar < 0:
        return SecondEntry(direction=direction)
    if push_count_back(bars, first_bar, last_closed, direction, limit=window) < 1:
        return SecondEntry(direction=direction)

    _, h1, l1, _ = _get_ohlc(bars[first_bar])
    _, h2, l2, _ = _get_ohlc(bars[second_bar])
    e1 = h1 if direction > 0 else l1
    e2 = h2 if direction > 0 else l2

    # The pullback depth is measured from entry 1's extreme to the far side of
    # the counter-move -- NOT to entry 2's extreme, which can already be beyond
    # entry 1 and would make the depth negative.
    counter_extreme = None
    for i in range(second_bar - pb_len, second_bar):
        _, h, low_val, _ = _get_ohlc(bars[i])
        candidate = low_val if direction > 0 else h
        if counter_extreme is None:
            counter_extreme = candidate
        elif direction > 0:
            counter_extreme = min(counter_extreme, candidate)
        else:
            counter_extreme = max(counter_extreme, candidate)
    if counter_extreme is None:
        return SecondEntry(direction=direction)
    pullback_size = (e1 - counter_extreme) if direction > 0 else (counter_extreme - e1)
    if pullback_size < min_pullback:
        return SecondEntry(direction=direction)

    return SecondEntry(
        found=True,
        direction=direction,
        first_bar=first_bar,
        second_bar=second_bar,
        pullback_bars=pb_len,
        separation_bars=second_bar - first_bar,
        pullback_size=pullback_size,
        entry1_extreme=e1,
        entry2_extreme=e2,
        extends=bool(e2 > e1 if direction > 0 else e2 < e1),
    )
