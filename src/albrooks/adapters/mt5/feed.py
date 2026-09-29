"""The MT5 connection: the one place `MetaTrader5` is named.

`scripts/check_no_mt5_dependency.py` allows this package — and only this package —
to import the terminal's bindings, and the check runs in CI. That is the whole
reason the import lives in a module of its own rather than being spread across the
adapter: the architectural rule is enforced by a script rather than by
convention, and a rule enforced by a script only holds if the surface it polices
is small enough to see.

## The import is lazy, and that is not an optimisation

`import MetaTrader5` happens inside `MT5Feed.connect()`, not at module import.
Two reasons, one practical and one about what the module *is*:

- The bindings only exist inside a MetaTrader terminal on Windows. Importing them
  at module scope would make `import albrooks.adapters.mt5` fail on Linux CI, on
  a Mac, and in any consumer's test suite — turning "this project has an optional
  MT5 adapter" into "this project does not import on most machines".
- A module that cannot be imported is a module that cannot be tested. The suite
  drives this adapter with an injected fake, and a top-level import would make
  that impossible without a terminal.

`MT5Unavailable` is raised when the import fails, so a caller sees one error type
for "no terminal" whether the bindings are missing or the terminal is down.

## Three things the live terminal corrected

This module was first written against the *documented* API and against the
MQL5-native convention, and running it against a real terminal (Alpari MT5, build
6230, `MetaTrader5` 5.0.6180) found all three:

1. **There is no `copy_rates`.** The Python bindings expose `copy_rates_from_pos`,
   `copy_rates_from` and `copy_rates_range` only. The old code called
   `copy_rates` and would have raised `AttributeError` on the first real fetch.
   `copy_rates_from_pos(symbol, timeframe, 0, count)` is the equivalent: position
   `0` is the current bar, and `count` bars are returned ending there.

2. **The payload is oldest-first, not newest-first.** See `series.py`'s module
   docstring — the MQL5 native `ArraySetAsSeries` convention does not apply to
   these bindings, and the original strict check would have raised on every real
   payload.

3. **The server clock runs ~3.1 hours ahead of the local one.** Using the local
   clock froze 14 of 50 M15 bars when only 1 was forming. `server_time()` below
   exists for that reason, and `closed_bars` uses it by default.

A fake written to the documented API passed all 54 tests and would still have
failed on its first live call. That is recorded in `docs/algorithms/MT5_ADAPTER.md`
§10 rather than quietly fixed, because "the test suite was green" is exactly the
claim that needed checking.

## What this class does not do

It sends no orders, sizes no positions and reads no account state. `ROADMAP.md`
records that as deliberate: a trade plan is not an order, position sizing needs an
account risk policy rather than a chart, and nothing in this project has been
validated against outcomes. This adapter is a **bar source** and nothing else, and
the only thing it writes is a `BarSeries`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from albrooks.adapters.mt5.errors import (
    HistoryUnavailable,
    MT5Unavailable,
    SymbolNotFound,
)
from albrooks.adapters.mt5.series import (
    CLOCK_CALLER,
    CLOCK_LOCAL,
    CLOCK_SERVER,
    FreezeReport,
    freeze_closed_bars,
    normalize_order,
)
from albrooks.adapters.mt5.timeframes import (
    MAX_PERIOD_SECONDS,
    canonical_name,
    period_seconds,
)
from albrooks.core.bars import BarSeries


class _MT5Module(Protocol):
    """The slice of the `MetaTrader5` bindings this adapter uses.

    Declared rather than imported for typing, so `mypy` can check the adapter on a
    machine where the bindings are not installed — which is every machine this is
    developed on except the one that runs MetaTrader. `copy_rates` is deliberately
    absent: the bindings do not provide it, and listing it is what let the first
    version of this module call a function that does not exist.
    """

    def initialize(self, **kwargs: Any) -> bool: ...
    def shutdown(self) -> None: ...
    def last_error(self) -> tuple[int, str]: ...
    def symbol_select(self, name: str, select: bool) -> bool: ...
    def copy_rates_from_pos(
        self, name: str, timeframe: int, start_pos: int, count: int
    ) -> Any: ...
    def symbol_info_tick(self, name: str) -> Any: ...
    def symbol_info(self, name: str) -> Any: ...


#: The symbol used to read the server clock when the requested one has no recent
#: tick. EURUSD is liquid on every retail venue, which is the property that makes
#: its tick time a usable stand-in for "now".
CLOCK_FALLBACK_SYMBOL = "EURUSD"


@dataclass(frozen=True, slots=True)
class FrozenSeries:
    """A frozen `BarSeries` and the report saying how it was frozen.

    Returned together rather than as a bare series because a parity failure is
    usually diagnosed by asking *which bar was dropped and on whose clock*, and a
    caller holding only the series cannot answer that.
    """

    series: BarSeries
    freeze: FreezeReport

    @property
    def symbol(self) -> str:
        return self.series.symbol

    @property
    def timeframe(self) -> str:
        return self.series.timeframe


class MT5Feed:
    """Bars from a running MetaTrader terminal, in this engine's order.

    ```python
    feed = MT5Feed()
    feed.connect("EURUSD", path=r"C:\\...\\terminal64.exe")
    frozen = feed.closed_bars("EURUSD", M15, 300)
    result = AnalysisSession().on_bars(frozen.series, freeze=frozen.freeze)
    ```

    `mt5_module` accepts an injected object with the same shape as the real
    bindings, which is how the test suite exercises every branch of this class
    without a terminal. The `MetaTrader5` name appears nowhere in the tests.
    """

    def __init__(self, mt5_module: Any | None = None) -> None:
        self._mt5 = mt5_module
        self._connected = False

    # -- connection ------------------------------------------------------

    def connect(
        self,
        symbol: str | None = None,
        *,
        path: str | None = None,
        login: int = 0,
        timeout_ms: int = 60_000,
    ) -> None:
        """Initialise the bindings, optionally log in and select a symbol.

        Raises `MT5Unavailable` if the bindings cannot be imported or the terminal
        refuses. `symbol_select` failing raises `SymbolNotFound` rather than being
        ignored, because a series for a symbol the terminal has not loaded comes
        back empty — and an empty series reaching the engine reads as `NO_BARS`, a
        statement about the market, when it is a statement about the connection.
        """
        mt5 = self._load()
        ok = mt5.initialize(path=path, login=login, timeout=timeout_ms)
        if not ok:
            code, message = mt5.last_error()
            raise MT5Unavailable(
                f"MetaTrader5.initialize() failed ({code}: {message}); the terminal "
                f"must be running and logged in"
            )
        self._mt5 = mt5
        self._connected = True
        if symbol is not None:
            self.select_symbol(symbol)

    def shutdown(self) -> None:
        """Release the terminal. Safe to call when never connected."""
        if self._mt5 is not None and self._connected:
            self._mt5.shutdown()
        self._connected = False

    def __enter__(self) -> MT5Feed:
        return self

    def __exit__(self, *exc: object) -> None:
        self.shutdown()

    def select_symbol(self, symbol: str) -> None:
        """Make sure the terminal is streaming `symbol`."""
        mt5 = self._require()
        if not mt5.symbol_select(symbol, True):
            code, message = mt5.last_error()
            raise SymbolNotFound(
                f"symbol_select({symbol!r}) failed ({code}: {message}); check the "
                f"broker's spelling and that the symbol is in Market Watch"
            )

    def _load(self) -> Any:
        """Import the bindings, or raise `MT5Unavailable` naming the reason."""
        if self._mt5 is not None:
            return self._mt5
        try:
            # `MetaTrader5` ships with a MetaTrader terminal and carries no type
            # information, so `mypy` is told to look the other way. The scope is
            # this one module on purpose: silencing it package-wide would remove
            # the check from the code that most needs it, and `feed.py` is
            # duck-typed through `_MT5Module` regardless.
            import MetaTrader5 as mt5  # type: ignore[import-untyped]  # noqa: PLC0415
        except ImportError as exc:
            raise MT5Unavailable(
                "the MetaTrader5 bindings are not importable; they ship with a "
                "MetaTrader 5 terminal on Windows and are not on PyPI for other "
                "platforms"
            ) from exc
        self._mt5 = mt5
        return mt5

    def _require(self) -> Any:
        if self._mt5 is None or not self._connected:
            raise MT5Unavailable("not connected; call connect() first")
        return self._mt5

    # -- bars ------------------------------------------------------------

    def bars(
        self,
        symbol: str,
        timeframe: int,
        count: int,
    ) -> tuple[list[dict[str, float]], str]:
        """`count` most recent bars as oldest-first, and the direction they came in.

        `copy_rates_from_pos(symbol, timeframe, 0, count)` is the call: position `0`
        is the current bar and `count` bars are returned ending there. There is no
        `copy_rates` in these bindings, despite it being the name the MQL5
        documentation uses.

        The second element is the observed direction convention, so a caller can
        log or assert on it rather than assume.
        """
        mt5 = self._require()
        rows: Sequence[Any] | None = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rows is None or len(rows) == 0:
            code, message = mt5.last_error()
            raise HistoryUnavailable(
                f"copy_rates_from_pos({symbol!r}, {timeframe}, 0, {count}) returned "
                f"nothing ({code}: {message}); the symbol may have no history for "
                f"that timeframe. Note that a short request for a symbol with no "
                f"history is indistinguishable from a terminal error here."
            )
        return normalize_order(rows)

    def closed_bars(
        self,
        symbol: str,
        timeframe: int,
        count: int,
        *,
        period_seconds: float | None = None,
        now: float | None = None,
    ) -> FrozenSeries:
        """`count` bars with the forming bar already dropped.

        This is the method the closed-bar contract needs. Two defaults matter:

        - the **server clock** is used unless `now` is supplied, because the local
          one measured 3.1 hours behind a live Alpari terminal and froze 13 extra
          bars;
        - `period_seconds` defaults to the timeframe's own length and is
          overridable for the one case that cannot be derived — a calendar month,
          which has no fixed period. See `timeframes.period_seconds`.
        """
        step = period_seconds if period_seconds is not None else self.period(timeframe)
        rows, order = self.bars(symbol, timeframe, count)
        name = canonical_name(timeframe)
        series = BarSeries(rows, symbol=symbol, timeframe=name)

        if now is None:
            # The server clock, not `time.time()`. The local clock measured 3.1
            # hours behind a live Alpari terminal, which over a 50-bar M15 window
            # discarded 13 closed bars. If the terminal's clock cannot be read at
            # all, the freeze falls back to the local one and *says so* in
            # `FreezeReport.clock` — a visible degradation rather than a silent
            # 13-bar error.
            server = self.server_time(symbol)
            clock = CLOCK_SERVER if server > 0 else CLOCK_LOCAL
            now = server if server > 0 else None
        else:
            clock = CLOCK_CALLER

        frozen, report = freeze_closed_bars(series, step, now=now, clock=clock)
        # The order convention is a property of the payload, not of the freeze, but
        # it belongs in the same report: both are "what the adapter had to assume
        # to produce this", and a reader debugging a parity failure wants both.
        return FrozenSeries(
            series=frozen,
            freeze=FreezeReport(
                now=report.now,
                period_seconds=report.period_seconds,
                bars_in=report.bars_in,
                bars_out=report.bars_out,
                forming_bar_time=report.forming_bar_time,
                clock=report.clock,
                order=order,
            ),
        )

    def frozen_bars(self, *args: Any, **kwargs: Any) -> FrozenSeries:
        """Alias of `closed_bars`, for callers who read the freeze as the point.

        Two names for one function is one too many, and it is here because the
        method's *name* is the contract: "closed" describes the result, "frozen"
        names the obligation being discharged.
        """
        return self.closed_bars(*args, **kwargs)

    @staticmethod
    def period(timeframe: int) -> float:
        """Bar length in seconds, refusing a period that cannot be measured."""
        seconds = period_seconds(timeframe)
        if seconds > MAX_PERIOD_SECONDS:
            raise MT5Unavailable(
                f"timeframe {canonical_name(timeframe)} implies a {seconds:.0f}s "
                f"bar, beyond {MAX_PERIOD_SECONDS:.0f}s; pass period_seconds "
                f"explicitly if that is genuinely the bar length"
            )
        return seconds

    def server_time(self, symbol: str | None = None) -> float:
        """The terminal's clock, as the time of `symbol`'s last tick.


        There is no `TimeCurrent()` in these bindings, so this is a tick time and
        therefore an *approximation*: on a quiet symbol the last tick may be older
        than now, which makes the freeze **conservative** (fewer bars treated as
        closed) — the safe direction, but still worth knowing.

        Falls back to `CLOCK_FALLBACK_SYMBOL` when the requested symbol has no
        recent tick, because a liquid symbol's tick time is a better clock than a
        quiet one. Returns `0.0` if neither yields a time, and the caller's freeze
        then reports `CLOCK_LOCAL` so the degradation is visible rather than
        silent.
        """
        mt5 = self._require()
        for candidate in (symbol, CLOCK_FALLBACK_SYMBOL):
            if not candidate:
                continue
            tick = mt5.symbol_info_tick(candidate)
            value = float(getattr(tick, "time", 0.0) or 0.0) if tick is not None else 0.0
            if value > 0:
                return value
        return 0.0


__all__ = ["CLOCK_FALLBACK_SYMBOL", "FrozenSeries", "MT5Feed"]
