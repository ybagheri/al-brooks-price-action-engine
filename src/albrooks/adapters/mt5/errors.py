"""Adapter errors, kept apart because a caller acts on them differently.

The engine's own failure vocabulary lives in the layers that raise: a reason code
on an `AnalysisResult` when the *input* is degenerate, an exception when the
*program* is misused. This module follows the same rule for the platform boundary.

Four failures, and the distinction between them is the point:

| Exception | What went wrong | What a caller should do |
|---|---|---|
| `MT5Unavailable` | terminal not running / not reachable | start MetaTrader, retry |
| `SymbolNotFound` | symbol not in the terminal's list | check the broker's spelling |
| `HistoryUnavailable` | `copy_rates` returned nothing usable | widen the request |
| `TimeframeUnsupported` | timeframe not one we can measure | pass `period_seconds` |

They are separate classes rather than one `AdapterError` with a message because
the recovery differs: a missing symbol is not fixed by retrying, and a missing
terminal is not fixed by correcting a symbol name. Collapsing them into one type
would push the discrimination back into a string comparison at the call site,
which is where it started.

None of them is a statement about the market. Every one is a statement about the
connection, and the adapter never converts one into a reading — the engine's own
`NO_BARS` / `ATR_UNAVAILABLE` reasons cover degenerate *data*, and they stay
separate from these.
"""

from __future__ import annotations


class MT5AdapterError(Exception):
    """Base class for every failure at the platform boundary."""


class MT5Unavailable(MT5AdapterError):
    """The terminal is not running, not logged in, or refused the call."""


class SymbolNotFound(MT5AdapterError):
    """The symbol is not in the terminal's symbol list."""


class HistoryUnavailable(MT5AdapterError):
    """`copy_rates` succeeded but returned no usable rows."""


class TimeframeUnsupported(MT5AdapterError):
    """The timeframe has no fixed length, so a forming bar cannot be identified.

    Raised only for timeframes whose period genuinely varies — a calendar month,
    which is 28, 29, 30 or 31 days. A caller that knows the bar period (or has a
    server that can tell it) supplies `period_seconds`; everyone else gets an
    error rather than a freeze computed from an assumed 30 days.
    """


__all__ = [
    "MT5AdapterError",
    "MT5Unavailable",
    "SymbolNotFound",
    "HistoryUnavailable",
    "TimeframeUnsupported",
]
