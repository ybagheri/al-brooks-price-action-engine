"""The MT5 adapter: bars from MetaTrader 5, and the stateful caller Phase 21 owes.

## What is here and what is not

| Module | What it does |
|---|---|
| `errors.py` | four failure types, kept apart because the recovery differs |
| `timeframes.py` | `ENUM_TIMEFRAMES` decoding, and the one period that cannot be measured |
| `series.py` | newest-first → oldest-first, and the forming-bar freeze |
| `feed.py` | the connection; the only module that names `MetaTrader5` |
| `session.py` | a stateful caller, which closes the Phase 19 fade finding |

**`mql5/Include/AlBrooks/` does not exist.** Phase 21's other half is an MQL5 port
of the engine, and it can only be written and *validated* on a machine with a
MetaTrader terminal and MetaEditor. `docs/algorithms/MT5_ADAPTER.md` §5 states
what is blocked on that and why nothing here pretends otherwise. The parity
harness therefore still reports `UNVERIFIED` — which is a statement that nothing
was compared, not a pass and not a failure.

## The two obligations this package discharges

1. **Direction.** MT5 series are newest-first; the engine is oldest-first
   throughout. `series.to_oldest_first()` is the only path from an MT5 payload to
   a `BarSeries`, and it *raises* on a payload that is not in MT5's order rather
   than sorting it. A reversed series still analyses, and analyses confidently,
   which is what makes silent correction the wrong instinct.

2. **The freeze.** `NON_REPAINT_CONTRACT.md` §4 makes dropping the forming bar the
   adapter's job, because the engine has deliberately no forming-bar flag.
   `series.freeze_closed_bars()` does it by **time** — `bar.time + period <= now` —
   rather than by position, since "the last row" is a guess that is wrong at every
   bar boundary and silently wrong.

## What this package will not do

It sends no orders, sizes no positions, and reads no account state. `ROADMAP.md`
records why: a trade plan is not an order, position sizing needs an account risk
policy rather than a chart, and nothing in this project has been validated against
outcomes. This is a **bar source** and a caller, and the only thing either
produces is a reading.
"""

from __future__ import annotations

from albrooks.adapters.mt5.errors import (
    HistoryUnavailable,
    MT5AdapterError,
    MT5Unavailable,
    SymbolNotFound,
    TimeframeUnsupported,
)
from albrooks.adapters.mt5.feed import FrozenSeries, MT5Feed
from albrooks.adapters.mt5.series import (
    ASCENDING,
    CLOCK_CALLER,
    CLOCK_LOCAL,
    CLOCK_SERVER,
    DESCENDING,
    NO_FORMING_BAR,
    FreezeReport,
    SeriesOrderError,
    detect_order,
    freeze_closed_bars,
    is_closed,
    normalize_order,
    to_series,
)
from albrooks.adapters.mt5.session import (
    WINDOW_FLOOR,
    WINDOW_SHORT,
    AnalysisSession,
    SessionResult,
)
from albrooks.adapters.mt5.timeframes import (
    D1,
    H1,
    H2,
    H3,
    H4,
    H6,
    H8,
    H12,
    M1,
    M2,
    M3,
    M4,
    M5,
    M6,
    M10,
    M12,
    M15,
    M20,
    M30,
    MN1,
    TIMEFRAMES,
    W1,
    canonical_name,
    period_seconds,
    timeframe_from_name,
)

#: The named timeframe constants are re-exported rather than left behind
#: `timeframes`, because a caller writing `closed_bars("EURUSD", M15, 300)` should
#: not have to know which submodule a constant lives in, and `M15` is a thing a
#: reader of a chart says out loud.
__all__ = [
    "ASCENDING",
    "CLOCK_CALLER",
    "CLOCK_LOCAL",
    "CLOCK_SERVER",
    "D1",
    "DESCENDING",
    "H1",
    "H12",
    "H2",
    "H3",
    "H4",
    "H6",
    "H8",
    "M1",
    "M10",
    "M12",
    "M15",
    "M2",
    "M20",
    "M3",
    "M4",
    "M5",
    "M6",
    "MN1",
    "M30",
    "NO_FORMING_BAR",
    "TIMEFRAMES",
    "W1",
    "WINDOW_FLOOR",
    "WINDOW_SHORT",
    "AnalysisSession",
    "FreezeReport",
    "FrozenSeries",
    "HistoryUnavailable",
    "MT5AdapterError",
    "MT5Feed",
    "MT5Unavailable",
    "SeriesOrderError",
    "SessionResult",
    "SymbolNotFound",
    "TimeframeUnsupported",
    "canonical_name",
    "detect_order",
    "freeze_closed_bars",
    "is_closed",
    "normalize_order",
    "period_seconds",
    "timeframe_from_name",
    "to_series",
]
