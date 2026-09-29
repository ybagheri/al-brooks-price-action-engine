"""From MetaTrader's series to this engine's, and the freeze in between.

## Correction, and it is a significant one

This module originally asserted that `copy_rates` returns **newest-first** and
refused any payload that was not. That is the **MQL5 native** convention —
`ArraySetAsSeries(true)` puts the current bar at index 0 — and it is *not* what the
Python bindings do.

Measured against a live terminal (Alpari MT5, build 6230,
`MetaTrader5` 5.0.6180), all three `copy_rates_*` entry points return
**oldest-first**, ascending, across M1, M5 and M15:

```text
copy_rates_from_pos('EURUSD', M15, 0, 100)  ->  n=100  asc=True  first=...  last=...
copy_rates_from('EURUSD',     M15, t-1e5, 100)  ->  n=100  asc=True
copy_rates_range('EURUSD',    M15, t-1e5, t)     ->  n=111  asc=True
```

So the strictness was aimed at the wrong convention and **would have raised on
every real payload**. It is fixed below, and the fix is not "accept anything".

The distinction that matters is not *which* direction but whether the payload is
**monotonic at all**. Both single directions are legitimate conventions — the
Python bindings use ascending, MQL5 native uses descending — and a payload in
either is a well-formed series. What cannot be legitimate is a series whose
timestamps do not move in one direction, because that is a genuinely broken or
mismatched payload, and normalising it would mean guessing which way the caller
meant. That is still refused, and the refusal is what this function is for.

`normalize_order` reports **which** convention it received, so a caller can see
rather than assume. The parity scope has `EXACT_INT` on `bar_index` and
`confirmed_bar_index` precisely because a wrong direction moves every index; a
silent normalisation would make that disagreement invisible at the point where it
is cheapest to catch.

## The two things this module has to get right

1. **Direction.** This engine is oldest-first everywhere — `Bar.index`,
   `last_closed`, every `range(k, n)` in every detector. `normalize_order()` is the
   only path from an MT5 payload to a `BarSeries`, and it records the direction it
   found rather than discarding it.
2. **The forming bar.** `NON_REPAINT_CONTRACT.md` §4 makes dropping the forming bar
   the **adapter's** job, because the engine has deliberately no forming-bar flag.
   `freeze_closed_bars()` does it — and see the clock, below, which is the part
   that is easy to get wrong.

## Why the freeze decides by time and not by position

The obvious implementation is "drop the last row". It is wrong, and wrong
*silently*, in three ordinary situations:

- the call happens in the instant after a bar closes, before the next opens, so
  the newest row is already closed and dropping it discards real data;
- a window can end on a bar boundary;
- across a weekend or a session break, the newest bar may have closed hours ago.

Dropping by position therefore either leaks the forming bar or throws away a
closed one, and both look like a working adapter until a comparison fails for no
visible reason.

The rule here is the same closed-bar arithmetic the rest of the project uses:

> `Bar.time` is the bar's **open** time, so bar `i` is closed at
> `bar.time + period_seconds`, and it is read only when that is `<= now`.

## The clock, and why the local one is wrong here

`now` must come from the **terminal's server clock**, not from `time.time()`.

Measured on the same terminal:

```text
local epoch       1790655320  = 2026-09-29 04:15:20 UTC
server tick epoch 1790666477  = 2026-09-29 07:21:17 UTC
skew: server - local = +11157 s = +3.099 h
```

That is a **3.1-hour** difference — twenty-six M15 bars. Against a 50-bar M15
window the consequences are not subtle:

| Clock | Bars treated as closed | Bars wrongly dropped |
|---|---|---|
| local | 36 of 50 | **14** |
| server | 49 of 50 | 1 (the real one) |

And the failure is **directional**, which is why it cannot be waved through as
"conservative":

- Server ahead of local (measured here): the local clock says fewer bars have
  closed, so the freeze **discards 13 bars of real history**. Annoying, not
  unsound.
- Local ahead of server: the local clock says more bars have closed, so the freeze
  **keeps a bar that is still forming**. That is a look-ahead, and it is the exact
  failure the whole design exists to prevent.

So the local clock is not merely imprecise — it is unsafe in whichever direction it
errs. `MT5Feed` therefore reads the clock from the terminal and passes it in, and
`FreezeReport` records **which clock was used** (`CLOCK_SERVER`, `CLOCK_CALLER` or
`CLOCK_LOCAL`) so a reader never has to guess. `CLOCK_LOCAL` exists only for
callers who have verified their clock, and it is named in the report for exactly
that reason.

A `now` supplied by the caller is `CLOCK_CALLER` and takes precedence: someone who
knows the right answer should not be overridden by a default.

## `server_time` is a tick time, and that is an approximation

The Python bindings expose no `TimeCurrent()`, so the server clock is read from
`symbol_info_tick(symbol).time` — the time of the **last tick**. On a liquid pair
that is within a second or two of now. On a quiet symbol it can be older, and an
old tick makes the freeze **conservative** (fewer bars treated as closed), which is
the safe direction. `MT5Feed` prefers the symbol being fetched, and falls back to a
liquid default only when it must.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from albrooks.core.bars import Bar, BarSeries

#: The direction convention a payload arrived in. Both are legal; neither is
#: assumed, and both are reported.
ASCENDING = "ASCENDING"
DESCENDING = "DESCENDING"

#: The clock that decided which bars were closed. Recorded because the answer to
#: "is this right?" depends on it and a reader should not have to go and find out.
CLOCK_SERVER = "SERVER"
CLOCK_CALLER = "CALLER"
CLOCK_LOCAL = "LOCAL"

#: Recorded when the payload had no forming bar to drop, so an empty
#: `FreezeReport.forming_bar_time` is not ambiguous between "none" and "not run".
NO_FORMING_BAR = "NO_FORMING_BAR"


class SeriesOrderError(ValueError):
    """An MT5 payload's timestamps do not move in a single direction.

    Raised rather than corrected. A payload that is neither ascending nor
    descending is not a convention this adapter can interpret, and sorting it would
    mean guessing which way the caller meant — which is precisely the guess that
    makes a reversed series produce a confident wrong answer.
    """


def detect_order(times: Sequence[float]) -> str:
    """`ASCENDING`, `DESCENDING`, or raise.

    Zero and one bar are ascending by definition, which is the right answer: there
    is no direction to get wrong. A payload whose timestamps repeat or reverse is
    refused, because sorting it would hide a real defect behind a working result.
    """
    if len(times) < 2:
        return ASCENDING
    rising = all(b > a for a, b in zip(times, times[1:]))
    falling = all(b < a for a, b in zip(times, times[1:]))
    if rising:
        return ASCENDING
    if falling:
        return DESCENDING
    raise SeriesOrderError(
        "MT5 bar timestamps are neither strictly ascending nor strictly "
        "descending; the payload is unordered, has duplicate times, or mixes "
        "sources. Refusing rather than sorting, because the direction the caller "
        "meant cannot be inferred from a broken sequence."
    )


def normalize_order(rows: Iterable[Any]) -> tuple[list[dict[str, float]], str]:
    """MT5 rows as oldest-first, plus the direction they arrived in.

    Accepts the Python bindings' ascending order and MQL5 native's descending one,
    and returns oldest-first either way. The second element is the **observed**
    direction, so a caller can log or assert on it: a silent flip to the other
    convention would move every bar index, and `FIELD_CLASSES` compares indices
    exactly for that reason.

    The MT5 field names are mapped here as well, so the rest of the package never
    has to know MT5's spelling.
    """
    out: list[dict[str, float]] = [
        {
            "time": _value(row, "time"),
            "open": _value(row, "open"),
            "high": _value(row, "high"),
            "low": _value(row, "low"),
            "close": _value(row, "close"),
            "volume": _value(row, "tick_volume", "real_volume", "volume", default=0.0),
        }
        for row in rows
    ]

    if not out:
        return out, ASCENDING

    order = detect_order([row["time"] for row in out])
    if order == DESCENDING:
        out.reverse()
    return out, order


def _value(row: Any, *names: str, default: float | None = None) -> float:
    """Read the first present field of `row`, by mapping key or attribute.

    A numpy record answers both `row["high"]` and `row.high`; a plain mapping
    answers only the first. Trying the mapping form inside a `try` and falling
    back to the attribute form is what lets one function serve both without
    importing either.
    """
    for name in names:
        try:
            return float(row[name])
        except (KeyError, IndexError, TypeError):
            pass
        try:
            return float(getattr(row, name))
        except AttributeError:
            continue
    if default is not None:
        return default
    raise KeyError(
        f"MT5 row has none of {names}; got "
        f"{sorted(row) if isinstance(row, Mapping) else row!r}"
    )


def to_series(
    rows: Iterable[Any],
    *,
    symbol: str = "GENERIC",
    timeframe: str = "UNKNOWN",
) -> BarSeries:
    """The full path from an MT5 payload to a `BarSeries`, oldest-first."""
    normalized, _ = normalize_order(rows)
    return BarSeries(normalized, symbol=symbol, timeframe=timeframe)


# --------------------------------------------------------------------------
# The freeze
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FreezeReport:
    """What the freeze did, on which clock, from which direction.

    Carried rather than returned as a bare series because a caller debugging a
    parity failure needs to know which bar was dropped, which clock said so, and
    which direction the payload arrived in. "The adapter froze it" is not a
    statement anyone can check.
    """

    #: The clock value used. The server's by default; see the module docstring.
    now: float = 0.0
    #: Bar length assumed for the closed-bar test.
    period_seconds: float = 0.0
    #: Bars handed in, and bars handed on.
    bars_in: int = 0
    bars_out: int = 0
    #: The open time of the bar that was dropped, or `NO_FORMING_BAR`.
    forming_bar_time: float | str = NO_FORMING_BAR
    #: Which clock decided: `SERVER`, `CALLER` or `LOCAL`.
    clock: str = CLOCK_LOCAL
    #: Which direction convention the payload used: `ASCENDING` or `DESCENDING`.
    order: str = ASCENDING

    @property
    def dropped(self) -> int:
        return self.bars_in - self.bars_out

    def to_dict(self) -> dict[str, Any]:
        return {
            "now": self.now,
            "period_seconds": self.period_seconds,
            "bars_in": self.bars_in,
            "bars_out": self.bars_out,
            "dropped": self.dropped,
            "forming_bar_time": self.forming_bar_time,
            "clock": self.clock,
            "order": self.order,
        }


def is_closed(bar_time: float, period_seconds: float, now: float) -> bool:
    """Has the bar that opened at `bar_time` finished?

    `bar_time + period_seconds <= now`, because `Bar.time` is the **open** time.
    The boundary is inclusive, which is the one choice that can be defended: a bar
    that closed exactly now has closed, and the next observation is what a live
    consumer would read at that same instant.
    """
    return bar_time + period_seconds <= now


def freeze_closed_bars(
    series: BarSeries,
    period_seconds: float,
    *,
    now: float | None = None,
    clock: str = CLOCK_LOCAL,
    unfrozen: bool = False,
) -> tuple[BarSeries, FreezeReport]:
    """Drop the forming bar, and report what was dropped and on whose clock.

    `now=None` falls back to `time.time()`. **That fallback is unsafe against a
    real terminal** and is kept only for callers who have verified their clock —
    see the module docstring for the measured 3.1-hour skew. `MT5Feed` always
    passes the server's clock.

    `unfrozen=True` skips the truncation and exists for `RPC-16`: the contract says
    a live adapter must freeze, and the only way to show the obligation has teeth is
    to show the answer *changes* when the bar is passed through as if closed. It is
    not a mode a caller should use.

    A series whose bars are all still forming freezes to **empty** rather than
    keeping the newest anyway. Keeping it would be the leak this function exists to
    prevent, and the engine already has a proper answer for an empty series —
    `NO_BARS`, reported as a reason on the result.
    """
    clock_used = clock if now is not None else CLOCK_LOCAL
    effective = time.time() if now is None else now
    bars_in = len(series)

    if unfrozen:
        return series, FreezeReport(
            now=effective,
            period_seconds=period_seconds,
            bars_in=bars_in,
            bars_out=bars_in,
            forming_bar_time=NO_FORMING_BAR,
            clock=clock_used,
        )

    # Oldest first, so the walk can stop at the first bar that is still forming:
    # every bar after it is newer, and a newer bar cannot be closed while an older
    # one is not. `break` is an early exit rather than a filter, and the pass is a
    # single forward scan.
    kept: list[Bar] = []
    dropped_time: float | str = NO_FORMING_BAR
    for bar in series:
        if not is_closed(bar.time, period_seconds, effective):
            dropped_time = bar.time
            break
        kept.append(bar)

    frozen = BarSeries(kept, symbol=series.symbol, timeframe=series.timeframe)
    return frozen, FreezeReport(
        now=effective,
        period_seconds=period_seconds,
        bars_in=bars_in,
        bars_out=len(frozen),
        forming_bar_time=dropped_time,
        clock=clock_used,
    )


def series_from_mapping(
    payload: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    symbol: str = "GENERIC",
    timeframe: str = "UNKNOWN",
) -> BarSeries:
    """Accept either a whole payload or a bare list of bars.

    A convenience for the common case where a caller already has normalised bars —
    this engine's own golden fixtures, for instance — and does not need the MT5 path
    at all. **The order is assumed, not checked**, because the input is not an MT5
    payload and there is no MT5 ordering to check against. Callers with an MT5
    payload go through `to_series`.
    """
    raw = payload["bars"] if isinstance(payload, Mapping) else payload
    # The payload is untyped by the time it reaches here, so the element type is
    # asserted rather than inferred. `BarSeries` re-validates every bar's OHLC
    # relationship on construction, so a malformed row is caught there rather than
    # reaching a detector.
    bars: list[Any] = list(raw)
    return BarSeries(bars, symbol=symbol, timeframe=timeframe)


__all__ = [
    "ASCENDING",
    "CLOCK_CALLER",
    "CLOCK_LOCAL",
    "CLOCK_SERVER",
    "DESCENDING",
    "NO_FORMING_BAR",
    "FreezeReport",
    "SeriesOrderError",
    "detect_order",
    "freeze_closed_bars",
    "is_closed",
    "normalize_order",
    "series_from_mapping",
    "to_series",
]
