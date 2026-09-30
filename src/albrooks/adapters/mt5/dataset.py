"""Dataset integrity: the checks a bar series must pass before it is evidence.

## Why this exists

`VALIDATION.md` §9.1 asks for real data, and §9.2 asks that the data carry a stated
provenance. This module is the part of that which can be built before any data
arrives: **the properties a series must have for a measurement to mean anything**,
and a refusal when it does not have them.

It is deliberately small. It does not resample, align, clean, fill gaps or
reinterpret anything. It checks four things and reports them, because every one of
them has a specific way of turning a result into a fiction:

1. **Strictly ascending bar times.** A duplicated or out-of-order timestamp makes
   "the next bar" ambiguous, and a backtest that resolves that ambiguity silently
   will report a path that never happened. `normalize_order` already refuses a
   mis-ordered *payload*; this refuses a mis-ordered *file*, which is the thing
   that survives a round trip through disk.
2. **Every bar closed at the stated clock.** A forming bar in a dataset is a
   look-ahead: its high and low are still moving, so any level "reached" inside it
   may never have been reached. This is `RPC-1` applied to a file rather than to a
   call.
3. **Positive prices.** `Bar.__post_init__` *already* refuses an incoherent bar —
   `high < low`, an open or close outside `[low, high]`, or a negative volume — so
   that check is **deliberately not repeated here**. It is enforced at construction,
   which is strictly stronger than enforcing it later: a series built from raw
   dictionaries goes through the same validation, so a corrupt bar cannot be
   represented at all rather than merely being detected downstream. A second copy of
   that rule in this module would be dead code that looks like a guarantee.

   What `Bar` does **not** check is positivity, and that is this entry. A zero or
   negative price is representable, and it poisons every ratio it appears in —
   ATR above all, being a denominator — while still returning a number.

4. **Not empty.** An empty series has no share, and reporting `0.0` for one is a
   fabricated number — the same refusal `events.py` makes.

## Why the checks report rather than raise

`inspect_series` never raises, so a caller can *see* what is wrong before deciding.
`require_integrity` raises, and is what a writer should call. The split matters
because the report is also the provenance record: a dataset file carries the
verdict that was true of it at the moment it was written, so a later reader can see
that it was checked rather than having to assume it.

## The clock is a parameter, and it is recorded

`now` and `clock` are explicit arguments and land in the report. The adapter's
module docstring records a measured 3.1-hour skew between a real terminal's server
clock and the local one, and a check that silently used the wrong clock would either
over-freeze or keep a forming bar. A verdict that does not say which clock produced
it cannot be checked against a later one.

## What this does not do

It does not say the data is *good*. Monotonic, closed, coherent bars can still come
from a broker with a bad tick, a symbol that renamed, or a history that was revised
after the fact. It says the series is internally consistent and free of
look-ahead — the two properties without which no downstream number means anything —
and nothing more. Whether the setups have an edge remains §9, and is not answered
here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from albrooks.adapters.mt5.series import CLOCK_LOCAL, is_closed
from albrooks.core.bars import BarSeries


class DatasetIntegrityError(ValueError):
    """A series failed a check that makes a measurement meaningless. Not fixed."""


@dataclass(frozen=True, slots=True)
class SeriesIntegrity:
    """What was checked, on which clock, and what came back.

    `problems` is empty exactly when `ok` is true. Both are carried so a caller can
    serialise the verdict rather than only assert it.
    """

    bars: int = 0
    period_seconds: float = 0.0
    #: The clock the closed-bar test used.
    now: float = 0.0
    clock: str = CLOCK_LOCAL
    first_time: float | None = None
    last_time: float | None = None
    #: Empty when the series is clean. Human-readable, one entry per distinct fault.
    problems: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "bars": self.bars,
            "period_seconds": self.period_seconds,
            "now": self.now,
            "clock": self.clock,
            "first_time": self.first_time,
            "last_time": self.last_time,
            "ok": self.ok,
            "problems": list(self.problems),
        }


def inspect_series(
    series: BarSeries,
    period_seconds: float,
    *,
    now: float,
    clock: str = CLOCK_LOCAL,
) -> SeriesIntegrity:
    """Check a series and report. Never raises, never repairs.

    Every fault is collected rather than stopping at the first, so one run tells a
    caller everything that is wrong with a file instead of one thing at a time.
    """
    problems: list[str] = []
    bars = list(series)

    if not bars:
        return SeriesIntegrity(
            bars=0,
            period_seconds=period_seconds,
            now=now,
            clock=clock,
            problems=("the series is empty, so it has no share and no span",),
        )

    # 1. Strictly ascending times. A repeated timestamp is a distinct fault from a
    # descending pair, because the first means a duplicated bar reached the file and
    # the second means the ordering was lost, and they need different fixes.
    duplicates: list[float] = []
    out_of_order: list[float] = []
    for previous, current in zip(bars, bars[1:]):
        if current.time == previous.time:
            duplicates.append(current.time)
        elif current.time < previous.time:
            out_of_order.append(current.time)
    if duplicates:
        problems.append(
            f"{len(duplicates)} duplicated bar time(s), first at {duplicates[0]}"
        )
    if out_of_order:
        problems.append(
            f"{len(out_of_order)} bar(s) out of ascending order, first at "
            f"{out_of_order[0]}"
        )

    # 2. Every bar closed at the stated clock. Reported as a count plus the most
    # recent offender, because "the last bar is still forming" is the common case
    # and is the one a reader most needs identified by its open time.
    unclosed = [b.time for b in bars if not is_closed(b.time, period_seconds, now)]
    if unclosed:
        problems.append(
            f"{len(unclosed)} bar(s) were not closed at {clock} time {now}, "
            f"most recent opening at {unclosed[-1]}"
        )

    # 3. Positive prices. The OHLC-coherence rule is enforced by `Bar` itself and
    # is not repeated -- see the module docstring for why a second copy would be
    # worse than none.
    nonpositive = [
        index
        for index, bar in enumerate(bars)
        if min(bar.open, bar.high, bar.low, bar.close) <= 0.0
    ]
    if nonpositive:
        problems.append(
            f"{len(nonpositive)} bar(s) carry a non-positive price, first at index "
            f"{nonpositive[0]}"
        )

    return SeriesIntegrity(
        bars=len(bars),
        period_seconds=period_seconds,
        now=now,
        clock=clock,
        first_time=bars[0].time,
        last_time=bars[-1].time,
        problems=tuple(problems),
    )


def require_integrity(report: SeriesIntegrity) -> SeriesIntegrity:
    """Raise unless the report is clean, listing every fault at once.

    Returns the report unchanged so a writer can keep the verdict it just proved.
    """
    if not report.ok:
        raise DatasetIntegrityError(
            "the series is not usable as evidence: "
            + "; ".join(report.problems)
            + f" (checked {report.bars} bar(s) on the {report.clock} clock at "
            f"{report.now})"
        )
    return report


__all__ = [
    "DatasetIntegrityError",
    "SeriesIntegrity",
    "inspect_series",
    "require_integrity",
]
