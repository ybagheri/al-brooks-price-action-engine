"""MT5 timeframe constants, and how to measure a bar's length without guessing.

## Why the adapter needs a bar period at all

The engine is closed-bars only and has no forming-bar flag — `NON_REPAINT_CONTRACT.md`
§4 makes dropping the forming bar the **adapter's** obligation. To drop it, the
adapter has to know which bar is forming, and "the last one `copy_rates` returned"
is not an answer: on a weekend, at a session boundary, or immediately after a bar
close, the newest row may already be closed. Deciding by position means the freeze
is a guess, and a wrong guess is exactly the look-ahead this whole design refuses.

So the adapter decides by **time**: a bar is closed when
`bar.time + period_seconds <= now`, because `Bar.time` is documented as the bar's
**open** time. That needs a period, which is what this module supplies.

## The constants

`ENUM_TIMEFRAMES` is not arbitrary numbering, and reading it as such is how a port
ends up with a 16,385-second hourly bar. The scheme has three bands:

| Band | Encoding | Example |
|---|---|---|
| Minutes | the minute count itself, `1..30` | `PERIOD_M5 = 5` |
| Hours | `16384 + hours` | `PERIOD_H1 = 16385`, `PERIOD_H4 = 16388` |
| Days | `16384 + hours`, up to 24 | `PERIOD_D1 = 16408` |
| Weeks | `32768 + weeks` | `PERIOD_W1 = 32769` |
| Months | `49152 + months` | `PERIOD_MN1 = 49153` |

`period_seconds()` implements exactly that decoding rather than carrying a lookup
table of twenty-odd constants, because the table and the scheme are two ways of
writing the same fact and a disagreement between them would be a silent one. The
table here is the *named* constants a caller is most likely to pass; everything
else is decoded.

## The one timeframe with no fixed period

A **calendar month** is 28, 29, 30 or 31 days. There is no constant period, so
there is no way to decide from the bar's own timestamp whether a monthly bar has
closed. `period_seconds(MN1)` therefore raises `TimeframeUnsupported` rather than
assuming 30 days.

This is a refusal rather than a limitation to work around. A 30-day assumption is
wrong for at least two days in every month, and a freeze that is wrong on those
days is a look-ahead that looks like a correct answer — the failure mode
`RPC-16` exists to make visible. A caller who knows the period passes
`period_seconds` to `freeze_closed_bars()` and gets an exact freeze; a caller who
does not gets told, instead of a number.
"""

from __future__ import annotations

from albrooks.adapters.mt5.errors import TimeframeUnsupported

#: Minutes, as MetaTrader spells them. The values are the constants themselves.
M1 = 1
M2 = 2
M3 = 3
M4 = 4
M5 = 5
M6 = 6
M10 = 10
M12 = 12
M15 = 15
M20 = 20
M30 = 30

#: `16384 + hours`. The offset is why these are not 60, 240 and so on.
_HOUR_OFFSET = 16384
H1 = _HOUR_OFFSET + 1
H2 = _HOUR_OFFSET + 2
H3 = _HOUR_OFFSET + 3
H4 = _HOUR_OFFSET + 4
H6 = _HOUR_OFFSET + 6
H8 = _HOUR_OFFSET + 8
H12 = _HOUR_OFFSET + 12
D1 = _HOUR_OFFSET + 24

#: `32768 + weeks`, and `49152 + months`. Weeks are fixed; months are not.
_WEEK_OFFSET = 32768
W1 = _WEEK_OFFSET + 1

_MONTH_OFFSET = 49152
MN1 = _MONTH_OFFSET + 1

SECONDS_PER_MINUTE = 60.0
SECONDS_PER_HOUR = 3600.0
SECONDS_PER_DAY = 86400.0
SECONDS_PER_WEEK = 7 * SECONDS_PER_DAY

#: Canonical spelling -> constant. Only the names a caller is likely to type, so a
#: symbol is never passed where a timeframe belongs.
TIMEFRAMES: dict[str, int] = {
    "M1": M1,
    "M2": M2,
    "M3": M3,
    "M4": M4,
    "M5": M5,
    "M6": M6,
    "M10": M10,
    "M12": M12,
    "M15": M15,
    "M20": M20,
    "M30": M30,
    "H1": H1,
    "H2": H2,
    "H3": H3,
    "H4": H4,
    "H6": H6,
    "H8": H8,
    "H12": H12,
    "D1": D1,
    "W1": W1,
    "MN1": MN1,
}

#: The longest a single bar may be, in seconds, for a step measurement to be
#: trusted. Sixty days is above every fixed timeframe MT5 offers and well below a
#: gap a session break or a holiday can produce, so a series that *measures* a
#: larger step has almost certainly hit a gap rather than found a longer bar.
MAX_PERIOD_SECONDS = 60 * SECONDS_PER_DAY


def canonical_name(timeframe: int) -> str:
    """The `M15` / `H4` / `D1` spelling of a constant, or `UNKNOWN(<n>)`.

    Present so a result's `timeframe` field says something a human recognises
    rather than `16388`, and so a value outside the named set is visibly outside
    it instead of being given a plausible name.
    """
    for name, value in TIMEFRAMES.items():
        if value == timeframe:
            return name
    return f"UNKNOWN({timeframe})"


def period_seconds(timeframe: int) -> float:
    """How long one bar of `timeframe` lasts, in seconds.

    Raises `TimeframeUnsupported` for a calendar month, and for any constant that
    is not a period this scheme defines. Both are refusals for the same reason:
    a caller that cannot measure the bar period cannot identify the forming bar,
    and guessing would put a look-ahead into the freeze.
    """
    if timeframe == MN1:
        raise TimeframeUnsupported(
            "a calendar month has no fixed period (28-31 days), so the forming "
            "bar cannot be identified from the timestamp; pass period_seconds "
            "explicitly if the bar period is known"
        )
    if 0 < timeframe <= M30:
        return timeframe * SECONDS_PER_MINUTE
    if _HOUR_OFFSET < timeframe <= _HOUR_OFFSET + 24:
        return (timeframe - _HOUR_OFFSET) * SECONDS_PER_HOUR
    if _WEEK_OFFSET < timeframe <= _WEEK_OFFSET + 7:
        return (timeframe - _WEEK_OFFSET) * SECONDS_PER_WEEK
    raise TimeframeUnsupported(
        f"{timeframe} is not an ENUM_TIMEFRAMES value this adapter can measure; "
        f"known timeframes are {sorted(TIMEFRAMES)}"
    )


def timeframe_from_name(name: str) -> int:
    """The constant for a canonical spelling, e.g. `"H4"` -> `16388`.

    Case-insensitive, because a caller reading a name off a chart is not making a
    claim about case and should not be punished for it. An unknown name is a
    `KeyError` naming the ones that exist rather than a silent default.
    """
    try:
        return TIMEFRAMES[name.strip().upper()]
    except KeyError as exc:
        raise TimeframeUnsupported(
            f"{name!r} is not a known timeframe; expected one of "
            f"{sorted(TIMEFRAMES)}"
        ) from exc


__all__ = [
    "TIMEFRAMES",
    "MAX_PERIOD_SECONDS",
    "SECONDS_PER_MINUTE",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_DAY",
    "SECONDS_PER_WEEK",
    "canonical_name",
    "period_seconds",
    "timeframe_from_name",
]
