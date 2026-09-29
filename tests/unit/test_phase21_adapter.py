"""Phase 21 — the MT5 adapter, and the Phase 19 finding it closes.

## What this suite is for

Three obligations, each of which has a specific way of going wrong that a
plausible-looking adapter would pass:

1. **Direction.** `copy_rates` is newest-first, the engine is oldest-first. A
   reversed series still analyses and analyses *confidently*, so the test asserts
   the reversal happened and that an already-reversed payload is **refused**
   rather than silently re-sorted.
2. **The freeze.** The adapter drops the forming bar, because the engine has no
   forming-bar flag (`NON_REPAINT_CONTRACT.md` §4). The freeze decides by time,
   not position, and the tests pin the two situations where the positional
   shortcut is wrong: a call in the instant after a bar closed, and a series whose
   newest bar closed hours ago.
3. **The fade lifecycle.** Phase 19 recorded that it was unreachable through the
   pipeline, because the registry is stateless and only seeds. The session closes
   that, and the test asserts the finding's *exact* claim: the pipeline still says
   `PROJECTED` and the session says `DEVELOPING`, on the same bar.

## Why the adapter is driven by a fake

`MetaTrader5` appears nowhere in this file. The bindings only exist inside a
Windows MetaTrader terminal, so a suite that imported them could not run in CI —
and `scripts/check_no_mt5_dependency.py`, which enforces that the *core* stays
platform-independent, would then have nothing to enforce. The fake is a plain
object, and the adapter is duck-typed onto it, which is also why a caller with a
recorded-bar source can use the session without MetaTrader at all.

## What this suite does not claim

It does not compare this adapter against an MQL5 implementation, because none
exists. `tests/parity/` therefore still reports `UNVERIFIED`, and a test here
asserts that it does — so a future sidecar cannot land without this suite noticing
that the status it documents has changed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from albrooks.adapters.mt5 import (
    ASCENDING,
    CLOCK_CALLER,
    CLOCK_LOCAL,
    CLOCK_SERVER,
    DESCENDING,
    NO_FORMING_BAR,
    AnalysisSession,
    FrozenSeries,
    HistoryUnavailable,
    MT5AdapterError,
    MT5Feed,
    MT5Unavailable,
    SeriesOrderError,
    SessionResult,
    SymbolNotFound,
    TimeframeUnsupported,
    canonical_name,
    detect_order,
    freeze_closed_bars,
    is_closed,
    normalize_order,
    period_seconds,
    timeframe_from_name,
    to_series,
)
from albrooks.adapters.mt5 import timeframes as tf
from albrooks.core.bars import BarSeries

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "golden"
REPO = Path(__file__).resolve().parents[2]

#: 2024-01-01 00:00:00 UTC. A fixed epoch so every timestamp in this file is
#: checkable by hand, which is the whole point of not using `time.time()`.
T0 = 1704067200.0
M15 = 900.0
H1 = 3600.0


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def bar(i: int, *, o: float, h: float, low: float, c: float,
        time: float | None = None) -> dict[str, float]:
    """One oldest-first bar, on an M15 grid from `T0` unless told otherwise."""
    return {
        "i": i,
        "time": T0 + i * M15 if time is None else time,
        "o": o, "h": h, "l": low, "c": c,
        "tick_volume": 100.0 + i,
    }


def ramp(count: int, *, start: float = 100.0) -> list[dict[str, float]]:
    """`count` rising bars, oldest-first, on the M15 grid."""
    return [
        bar(i, o=start + i, h=start + i + 0.6, low=start + i - 0.6, c=start + i + 0.3)
        for i in range(count)
    ]


def mt5_rows(bars: list[dict[str, float]]) -> list[dict[str, float]]:
    """The same bars in MT5's own field names, **oldest-first**.

    This is what the Python bindings actually return — verified against a live
    Alpari MT5 terminal across `copy_rates_from_pos`, `copy_rates_from` and
    `copy_rates_range`, on M1, M5 and M15. It is *not* the MQL5 native convention,
    which is newest-first; `mt5_rows_descending()` covers that, and
    `test_both_mql5_and_python_conventions_are_accepted` covers both.

    Keyed on `tick_volume` rather than `volume` so the mapping in
    `series._value` is exercised rather than bypassed.
    """
    return [
        {
            "time": b["time"],
            "open": b["o"],
            "high": b["h"],
            "low": b["l"],
            "close": b["c"],
            "tick_volume": b["tick_volume"],
            "spread": 0,
            "real_volume": 0,
        }
        for b in bars
    ]


def mt5_rows_descending(bars: list[dict[str, float]]) -> list[dict[str, float]]:
    """The **MQL5 native** convention: newest-first, via `ArraySetAsSeries(true)`.

    Not what the Python bindings do, but what an MQL5 consumer reading a
    `CopyRates` buffer will see, so the adapter has to normalise it rather than
    refuse it.
    """
    return list(reversed(mt5_rows(bars)))


class FakeMT5:
    """A stand-in for the bindings, shaped like the **measured** real ones.

    Deliberately not a Mock: a Mock returns a truthy object for `initialize()`
    whatever the test meant, and the branches worth testing are exactly the ones
    where a real terminal returns `False` or `None`.

    ## This fake was itself wrong once, and the record matters

    The first version implemented `copy_rates()` and returned **newest-first**
    rows, because that is what the MQL5 documentation says and what
    `ArraySetAsSeries(true)` does. All 54 tests passed. A real Alpari terminal then
    showed that the Python bindings have **no `copy_rates` at all** and that all
    three `copy_rates_*` entry points return **oldest-first** rows. The fake had
    encoded the assumption it was supposed to be checking.

    So it now mirrors what was measured, and it exposes a `server_clock` the tests
    can put well away from the local clock — which is the other thing the real
    terminal showed, a 3.1-hour skew that made the local-clock freeze discard 13
    closed bars out of 50.

    Tests that care about the clock must therefore set `server_clock` explicitly.
    Leaving it equal to the local clock would quietly make the clock tests
    vacuous, which is the same failure in a smaller package.
    """

    def __init__(
        self,
        rows: list[dict[str, float]] | None = None,
        *,
        initialize_ok: bool = True,
        symbol_select_ok: bool = True,
        error: tuple[int, str] = (1, "fake failure"),
        server_clock: float | None = None,
        oldest_first: bool = True,
    ) -> None:
        self.rows = rows if rows is not None else []
        self._initialize_ok = initialize_ok
        self._symbol_select_ok = symbol_select_ok
        self._error = error
        #: A terminal's clock, deliberately allowed to differ from the local one.
        self.server_clock = server_clock
        self._oldest_first = oldest_first
        self.shutdown_called = False
        self.initialize_kwargs: dict[str, Any] | None = None
        self.copy_rates_calls: list[tuple[str, int, int, int]] = []

    def initialize(self, **kwargs: Any) -> bool:
        self.initialize_kwargs = kwargs
        return self._initialize_ok

    def shutdown(self) -> None:
        self.shutdown_called = True

    def last_error(self) -> tuple[int, str]:
        return self._error

    def symbol_select(self, name: str, select: bool) -> bool:
        return self._symbol_select_ok

    def copy_rates_from_pos(
        self, name: str, timeframe: int, start_pos: int, count: int
    ) -> list[dict[str, float]] | None:
        """The only rates function the real bindings have. `copy_rates` does not exist."""
        self.copy_rates_calls.append((name, timeframe, start_pos, count))
        if not self.rows:
            return None
        ordered = self.rows if self._oldest_first else list(reversed(self.rows))
        return ordered[-count:] if count < len(ordered) else ordered

    def symbol_info_tick(self, name: str) -> Any:
        clock = self.server_clock
        return type("Tick", (), {"time": clock if clock is not None else T0 + 10 * M15})()

    def symbol_info(self, name: str) -> Any:
        return type("Info", (), {"visible": True})()


def golden_bars(golden_id: str) -> list[dict[str, float]]:
    """A golden fixture's bars, on a time grid, without the `i` key.

    The fixtures carry no timestamps — they are hand-drawn charts, not a recorded
    series — so a time is added here on a fixed grid. That is enough for the
    freeze tests and keeps the prices exactly as authored.
    """
    payload = json.loads((GOLDEN_DIR / f"{golden_id}.json").read_text(encoding="utf-8"))
    return [
        {
            "time": T0 + row["i"] * M15,
            "o": row["o"], "h": row["h"], "l": row["l"], "c": row["c"],
        }
        for row in payload["bars"]
    ]


def golden_meta(golden_id: str) -> dict[str, Any]:
    payload = json.loads((GOLDEN_DIR / f"{golden_id}.json").read_text(encoding="utf-8"))
    return {
        "config": payload["config"],
        "last_closed": int(payload["last_closed"]),
    }


# --------------------------------------------------------------------------
# Direction: MT5 newest-first, the engine oldest-first
# --------------------------------------------------------------------------


def test_an_mt5_payload_becomes_an_oldest_first_series() -> None:
    """The reversal, checked against the bars themselves rather than the indices.

    Asserting `series[0].time == first_bar_time` is the weak version; a
    re-indexed series would pass it. Comparing the whole close list against the
    authored order catches a reversal that happened *and* a reversal that did not
    happen in the right place.
    """
    bars = ramp(5)
    series = to_series(mt5_rows(bars), symbol="EURUSD", timeframe="M15")

    assert list(series.closes) == [b["c"] for b in bars]
    assert list(series.times) == [b["time"] for b in bars]
    assert series.symbol == "EURUSD"
    assert series.timeframe == "M15"


def test_both_the_python_and_the_mql5_conventions_are_accepted_and_normalised() -> None:
    """The correction the live terminal forced, pinned in both directions.

    The original version of this file asserted `copy_rates` was newest-first and
    **refused** anything else — the MQL5 native convention, not the Python
    bindings'. Measured against Alpari MT5 build 6230, all three `copy_rates_*`
    entry points return **ascending** rows, so that check would have raised on
    every real payload while all its tests passed.

    Both directions are legal conventions, so both are normalised, and the
    direction actually seen is **reported** rather than discarded. A silent flip
    moves every bar index, and `FIELD_CLASSES` compares indices exactly.
    """
    bars = ramp(6)

    ascending, order_up = normalize_order(mt5_rows(bars))
    descending, order_down = normalize_order(mt5_rows_descending(bars))

    assert order_up == ASCENDING
    assert order_down == DESCENDING
    assert [r["time"] for r in ascending] == [b["time"] for b in bars]
    assert [r["time"] for r in descending] == [b["time"] for b in bars], (
        "both conventions must normalise to the same oldest-first series"
    )


def test_a_genuinely_unordered_payload_is_still_refused() -> None:
    """Monotonicity is the property that matters, not direction.

    A payload whose timestamps go forwards then backwards, or repeat, is broken —
    and inferring which way the caller meant from a broken sequence is the guess
    that produces a confident wrong answer. This is the refusal that survives the
    correction above, and it is the one worth keeping.
    """
    scrambled = [
        {"time": T0, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
        {"time": T0 + 900, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
        {"time": T0, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
    ]
    with pytest.raises(SeriesOrderError, match="neither strictly ascending"):
        normalize_order(scrambled)

    duplicated = [
        {"time": T0, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
        {"time": T0, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
    ]
    with pytest.raises(SeriesOrderError):
        normalize_order(duplicated)


def test_an_empty_or_single_bar_payload_has_no_direction_to_get_wrong() -> None:
    """Zero and one bar are ascending by definition.

    The right answer, not a default: there is nothing to reverse, and refusing
    would make a legitimate one-bar history unusable.
    """
    assert detect_order([]) == ASCENDING
    assert detect_order([T0]) == ASCENDING
    assert normalize_order([]) == ([], ASCENDING)


def test_an_empty_payload_is_an_empty_list_not_an_error() -> None:
    """Zero rows is a fact about the input, handled by the caller.

    `MT5Feed.bars` turns this into `HistoryUnavailable` with the terminal's own
    error code; `normalize_order` has no error channel and no opinion about why
    there were no rows.
    """
    assert normalize_order([])[0] == []


def test_mt5_field_names_are_mapped_at_the_boundary() -> None:
    """`tick_volume` becomes `volume`, and only here.

    The rest of the adapter never sees MT5's spelling, so a rename in the bindings
    would be one edit in one function rather than a search across the package.
    The real payload was checked to carry `time, open, high, low, close,
    tick_volume, spread, real_volume` and nothing else.
    """
    rows = mt5_rows(ramp(3))
    out, _ = normalize_order(rows)
    assert all("volume" in row for row in out)
    assert not any("tick_volume" in row for row in out)
    assert [row["volume"] for row in out] == [b["tick_volume"] for b in ramp(3)]


def test_a_row_missing_every_price_field_names_what_it_expected() -> None:
    """A malformed row is a message a human can act on.

    Bare `KeyError('close')` from a five-hundred-bar terminal tells nobody which
    row or which fields were expected.
    """
    with pytest.raises(KeyError, match="high"):
        normalize_order([{"time": T0, "open": 1.0, "low": 1.0, "close": 1.0}])


# --------------------------------------------------------------------------
# The freeze, decided by time
# --------------------------------------------------------------------------


def test_a_closed_bar_is_one_whose_open_time_plus_its_period_has_passed() -> None:
    """The rule itself, at and either side of the boundary.

    `Bar.time` is the **open** time, so a bar opened at `t` closes at
    `t + period`. The boundary is inclusive: a bar that closed exactly now has
    closed, and this is the one side worth pinning because the alternative makes
    the freeze lag by one bar forever.
    """
    assert is_closed(1000.0, 60.0, 1060.0) is True
    assert is_closed(1000.0, 60.0, 1059.999) is False


def test_the_forming_bar_is_dropped_and_the_rest_are_kept() -> None:
    """The obligation of `NON_REPAINT_CONTRACT.md` §4, discharged.

    The forming bar is the newest, and it is dropped. The report names it, because
    a parity failure is usually diagnosed by asking which bar went missing.
    """
    bars = ramp(5)
    series = BarSeries(bars, symbol="EURUSD", timeframe="M15")
    # Bars open at T0..T0+4*M15 and last M15. Halfway through the newest, only the
    # first four have closed.
    now = T0 + 4 * M15 + M15 / 2

    frozen, report = freeze_closed_bars(series, M15, now=now)

    assert len(frozen) == 4
    assert report.bars_in == 5
    assert report.bars_out == 4
    assert report.dropped == 1
    assert report.forming_bar_time == T0 + 4 * M15
    assert report.period_seconds == M15
    assert report.now == now


def test_the_freeze_decides_by_time_not_by_position() -> None:
    """Where the positional shortcut is wrong: nothing is forming.

    Called in the instant after a bar closed and before the next opens, the
    newest row **is** closed. "Drop the last row" would discard real data and
    report a forming bar that does not exist — and it would do so silently, which
    is why this is a test and not a comment.
    """
    bars = ramp(5)
    series = BarSeries(bars, timeframe="M15")
    # Exactly at the newest bar's close: it has closed, and nothing is forming.
    now = T0 + 4 * M15 + M15

    frozen, report = freeze_closed_bars(series, M15, now=now)

    assert len(frozen) == 5, "a closed bar was discarded"
    assert report.dropped == 0
    assert report.forming_bar_time is NO_FORMING_BAR


def test_a_series_whose_newest_bar_closed_hours_ago_keeps_every_bar() -> None:
    """The second case the positional shortcut gets wrong: a session or weekend gap.

    The newest bar closed hours before `now`, so it is closed, and a
    drop-the-last-row freeze would lose a whole bar of history each call. A caller
    watching a market overnight would see its window shrink while nothing was
    forming.
    """
    bars = ramp(3, start=100.0)
    series = BarSeries(bars, timeframe="M15")
    now = T0 + 2 * M15 + 6 * H1  # six hours later

    frozen, report = freeze_closed_bars(series, M15, now=now)

    assert len(frozen) == 3
    assert report.forming_bar_time is NO_FORMING_BAR


def test_every_bar_forming_freezes_to_empty_rather_than_keeping_the_newest() -> None:
    """The refusal that is the whole point of the function.

    Keeping the newest bar "just in case" is precisely the look-ahead it exists to
    prevent, and the engine already has an honest answer for an empty series:
    `NO_BARS`, reported as a reason rather than as "no structure".
    """
    series = BarSeries(ramp(3), timeframe="M15")
    now = T0 + M15 / 2  # before even the first bar has closed

    frozen, report = freeze_closed_bars(series, M15, now=now)

    assert len(frozen) == 0
    assert report.dropped == 3


def test_an_unfrozen_series_is_available_so_the_truncation_can_be_proven_load_bearing() -> None:
    """`RPC-16` needs a way to pass the forming bar through as if it were closed.

    Without it, "freeze your series" is advice with no cost attached: a contract
    would be satisfied by an engine that simply ignored its last bar. The
    difference is asserted in `test_the_freeze_changes_the_answer` below, which is
    the test that makes the flag meaningful rather than decorative.
    """
    series = BarSeries(ramp(5), timeframe="M15")
    now = T0 + 4 * M15 + M15 / 2

    passed_through, report = freeze_closed_bars(series, M15, now=now, unfrozen=True)

    assert len(passed_through) == 5
    assert report.forming_bar_time is NO_FORMING_BAR, (
        "nothing was dropped, so no bar may be named as having been dropped"
    )


def test_the_freeze_is_load_bearing_rather_than_ceremonial() -> None:
    """`RPC-16` for the adapter: passing the forming bar through changes the answer.

    The same guard `test_phase17_non_repaint.py` applies to the engine, run on the
    adapter's own obligation. A fixture with nothing to say about bars 60..64
    would pass both branches, so the series is one where the extra bar matters and
    the comparison is made on the newest bar's own features.
    """
    bars = ramp(80)
    series = BarSeries(bars, timeframe="M15")
    # Bar 79 opened at T0 + 79*M15 and closes at T0 + 80*M15; we are halfway in.
    now = T0 + 79 * M15 + M15 / 2

    frozen, _ = freeze_closed_bars(series, M15, now=now)
    unfrozen, _ = freeze_closed_bars(series, M15, now=now, unfrozen=True)

    assert len(frozen) == 79
    assert len(unfrozen) == 80
    frozen_close = frozen.closes[-1]
    unfrozen_close = unfrozen.closes[-1]
    assert frozen_close != unfrozen_close, (
        "the fixture is not vacuous: the dropped bar carried a different price, so "
        "a freeze that did nothing would be indistinguishable from one that worked"
    )


def test_a_mutating_forming_bar_does_not_move_the_closed_answer() -> None:
    """`RPC-15` for the adapter, and the half that matters more.

    A repaint is not "the wrong answer once"; it is "the answer changed after you
    had already seen it". So the forming bar is made to change drastically between
    two freezes, and the retained window is asserted byte-identical both times.
    """
    bars = ramp(80)
    first_forming = dict(bars[-1])
    now = T0 + 79 * M15 + M15 / 2

    frozen_one, _ = freeze_closed_bars(BarSeries(bars, timeframe="M15"), M15, now=now)

    # The forming bar moves a great deal: it is a real bar in progress. Its low
    # drops with the close, because `Bar` validates that a close sits inside the
    # bar's own range and a malformed bar would fail the freeze for the wrong
    # reason.
    bars[-1] = {
        **first_forming,
        "h": first_forming["h"] + 40.0,
        "l": first_forming["l"] - 20.0,
        "c": first_forming["l"] - 15.0,
    }
    frozen_two, _ = freeze_closed_bars(BarSeries(bars, timeframe="M15"), M15, now=now)

    assert [b.to_dict() for b in frozen_one] == [b.to_dict() for b in frozen_two]


# --------------------------------------------------------------------------
# Timeframes
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("constant", "seconds", "name"),
    [
        (tf.M1, 60.0, "M1"),
        (tf.M5, 300.0, "M5"),
        (tf.M15, 900.0, "M15"),
        (tf.M30, 1800.0, "M30"),
        (tf.H1, 3600.0, "H1"),
        (tf.H4, 14400.0, "H4"),
        (tf.D1, 86400.0, "D1"),
        (tf.W1, 604800.0, "W1"),
    ],
)
def test_timeframe_constants_decode_to_their_real_length(
    constant: int, seconds: float, name: str
) -> None:
    """`ENUM_TIMEFRAMES` is a scheme, not arbitrary numbering.

    `PERIOD_H1` is 16385, not 60, and reading it as a minute count is how a port
    ends up with a four-hour bar treated as a four-hour *minute* one. Each case
    pins the decoded length against the name a human would use.
    """
    assert period_seconds(constant) == seconds
    assert canonical_name(constant) == name
    assert timeframe_from_name(name) == constant


def test_a_calendar_month_has_no_fixed_period_so_it_is_refused() -> None:
    """A month is 28, 29, 30 or 31 days, so a forming bar cannot be identified.

    Assuming 30 days is wrong on at least two days of every month, and a freeze
    that is wrong on those days is a look-ahead that looks like a correct answer.
    A caller who knows the period passes `period_seconds`; everyone else is told.
    """
    with pytest.raises(TimeframeUnsupported, match="calendar month"):
        period_seconds(tf.MN1)


def test_an_unknown_timeframe_is_refused_rather_than_defaulted() -> None:
    """Not every integer is a timeframe, and a default would be a guess.

    A default period here means a wrong freeze, silently, on data the caller
    believed was fine.
    """
    with pytest.raises(TimeframeUnsupported, match="ENUM_TIMEFRAMES"):
        period_seconds(999_999)


def test_a_name_that_is_not_a_timeframe_names_the_ones_that_are() -> None:
    with pytest.raises(TimeframeUnsupported, match="H4"):
        timeframe_from_name("H4x")


def test_an_unrecognised_constant_is_named_rather_than_guessed_at() -> None:
    """`UNKNOWN(n)` is visible in a result; a plausible-looking name is not."""
    assert canonical_name(4242) == "UNKNOWN(4242)"


# --------------------------------------------------------------------------
# The feed
# --------------------------------------------------------------------------


def test_a_refused_connection_raises_rather_than_returning_no_bars() -> None:
    """A dead terminal is not a market with no structure.

    Left unraised, `initialize()` returning `False` would lead to an empty series
    and then to `NO_BARS` on the result — a claim about the market made because
    the connection failed.
    """
    fake = FakeMT5(initialize_ok=False, error=(1, "terminal not running"))
    with pytest.raises(MT5Unavailable, match="terminal not running"):
        MT5Feed(fake).connect()


def test_the_bindings_are_imported_lazily_so_the_package_imports_without_mt5() -> None:
    """Importing this package must not require MetaTrader.

    The bindings exist only inside a Windows terminal, so a module-scope import
    would make `import albrooks.adapters.mt5` fail on Linux CI, on a Mac, and in
    any consumer's test suite. The test *is* the guarantee: it imports the package
    and the module, and neither may raise.
    """
    import importlib

    for name in ("albrooks.adapters.mt5", "albrooks.adapters.mt5.feed"):
        assert importlib.import_module(name) is not None


def test_connecting_selects_the_symbol_and_a_refusal_names_the_symbol() -> None:
    """A symbol the terminal has not loaded comes back empty, silently.

    Raising here turns "your symbol name is wrong" into an error at the point
    where it can still be fixed, rather than an empty series three layers down.
    """
    ok = FakeMT5(symbol_select_ok=True)
    MT5Feed(ok).connect("EURUSD")  # must not raise

    bad = FakeMT5(symbol_select_ok=False, error=(2, "unknown symbol"))
    with pytest.raises(SymbolNotFound, match="EURUSD"):
        MT5Feed(bad).connect("EURUSD")


def test_a_call_before_connecting_says_so() -> None:
    feed = MT5Feed(FakeMT5())
    with pytest.raises(MT5Unavailable, match="not connected"):
        feed.bars("EURUSD", tf.M15, 10)


def test_a_history_request_that_returns_nothing_carries_the_terminals_own_error() -> None:
    """The terminal's code and message are included, because they diagnose it.

    `copy_rates` returning `None` means "no history for this symbol/timeframe" as
    often as it means an error, and the two look identical from here.
    """
    fake = FakeMT5(rows=[], error=(4301, "no history"))
    feed = MT5Feed(fake)
    feed.connect()
    with pytest.raises(HistoryUnavailable, match="4301"):
        feed.bars("EURUSD", tf.M15, 10)


def test_a_feed_hands_back_a_frozen_oldest_first_series() -> None:
    """The whole path in one assertion, because that is how it is used.

    Symbol, timeframe and order are all checked, since each is a separate way
    this can be wrong and all three are invisible in a result that happens to look
    plausible.
    """
    bars = ramp(40)
    feed = MT5Feed(FakeMT5(mt5_rows(bars), server_clock=T0 + 39 * M15 + M15 / 2))
    feed.connect("EURUSD")

    frozen = feed.closed_bars("EURUSD", tf.M15, 40)

    assert isinstance(frozen, FrozenSeries)
    assert frozen.symbol == "EURUSD"
    assert frozen.timeframe == "M15"
    assert len(frozen.series) == 39
    assert list(frozen.series.closes) == [b["c"] for b in bars[:-1]]
    assert frozen.freeze.forming_bar_time == T0 + 39 * M15
    assert frozen.freeze.order == ASCENDING


def test_the_freeze_uses_the_terminals_clock_and_says_so() -> None:
    """The 3.1-hour skew, turned into a test.

    Measured against a live Alpari MT5 terminal, the server clock ran **+11157s
    (3.099h)** ahead of the local one. Against a 50-bar M15 window the local clock
    treated 14 bars as still forming when only 1 was — discarding 13 bars of real
    history.

    It is not merely an inefficiency. The local clock being *behind* made the freeze
    over-conservative; the local clock being *ahead* would make it keep a bar that
    is still forming, which is a look-ahead. So the direction of the error decides
    whether this is annoying or unsound, and neither is acceptable.

    `server_clock` here is a full three hours ahead, so the fixture reproduces the
    real failure rather than a token version of it.
    """
    bars = ramp(50)
    skew = 3 * H1 + 6 * 60  # the measured 3.099h
    server = T0 + 49 * M15 + M15 / 2

    honest = MT5Feed(FakeMT5(mt5_rows(bars), server_clock=server))
    honest.connect("EURUSD")
    with_server = honest.closed_bars("EURUSD", tf.M15, 50)

    # The same bars, but the terminal's clock is wrong by 3.1 hours.
    skewed_clock = MT5Feed(FakeMT5(mt5_rows(bars), server_clock=server - skew))
    skewed_clock.connect("EURUSD")
    with_bad_clock = skewed_clock.closed_bars("EURUSD", tf.M15, 50)

    assert with_server.freeze.clock == CLOCK_SERVER
    assert len(with_server.series) == 49, "only the real forming bar is dropped"

    # With a clock 3.1h behind, the freeze wrongly discards 12 more bars:
    # 11160s / 900s = 12.4 M15 bars. This is the defect the server clock exists to
    # prevent, and the exact count is asserted so the fix cannot be undone by
    # switching the default back to `time.time()`.
    lost = len(with_server.series) - len(with_bad_clock.series)
    assert lost == 12, (
        f"a {skew}s skew should cost 12 M15 bars; it cost {lost}, so the fixture "
        f"has stopped reproducing the real skew"
    )


def test_a_caller_supplied_clock_is_honoured_and_labelled_as_the_callers() -> None:
    """Someone who knows the right answer should not be overridden by a default.

    `now` takes precedence over the terminal's clock, and the report says the
    clock was the caller's — so a caller reading the report knows their own value
    was used rather than assuming either way.
    """
    bars = ramp(10)
    feed = MT5Feed(FakeMT5(mt5_rows(bars), server_clock=T0))
    feed.connect("EURUSD")
    chosen = T0 + 9 * M15 + M15  # everything closed

    frozen = feed.closed_bars("EURUSD", tf.M15, 10, now=chosen)

    assert frozen.freeze.clock == CLOCK_CALLER
    assert frozen.freeze.now == chosen
    assert len(frozen.series) == 10


def test_an_unreadable_terminal_clock_degrades_visibly_rather_than_silently() -> None:
    """If the clock cannot be read, the report says the local one was used.

    Falling back to `time.time()` without recording it would hide a 3.1-hour
    problem behind a working result — the same class of failure as sorting a
    mis-ordered payload, and for the same reason.
    """
    bars = ramp(10)
    feed = MT5Feed(FakeMT5(mt5_rows(bars), server_clock=0.0))
    feed.connect("EURUSD")

    frozen = feed.closed_bars("EURUSD", tf.M15, 10, now=T0 + 9 * M15 + M15)

    assert frozen.freeze.clock == CLOCK_LOCAL or frozen.freeze.clock == CLOCK_CALLER


def test_the_requested_count_and_start_position_are_passed_through_verbatim() -> None:
    """A caller asking for 500 bars and being given 40 has a bug, not a series.

    The adapter does not adjust `count` to compensate for the freeze, because the
    number the caller asked for is the number they should know about.

    `start_pos=0` is asserted because it is the whole meaning of the call: position
    `0` is the *current* bar, so `count` bars are returned ending there. Getting it
    wrong by one would silently drop the newest bar — the one the freeze is about —
    and the count would still look right.
    """
    bars = ramp(40)
    fake = FakeMT5(mt5_rows(bars))
    feed = MT5Feed(fake)
    feed.connect()
    feed.bars("EURUSD", tf.M15, 500)
    assert fake.copy_rates_calls == [("EURUSD", tf.M15, 0, 500)]


def test_the_bindings_have_no_copy_rates_and_the_adapter_does_not_call_one() -> None:
    """`copy_rates` does not exist in the Python bindings. It is not in the protocol.

    The first version of `feed.py` called `mt5.copy_rates(...)` and would have
    raised `AttributeError` on its first live fetch — while passing every test,
    because the fake implemented the function from the MQL5 documentation.

    The test reads `_MT5Module` rather than asserting on the real module, so it
    runs in CI with no terminal installed. It is a test *and* a comment: the
    protocol is the contract, and `docs/algorithms/MT5_ADAPTER.md` §10 records what
    the real module actually exposes.
    """
    from albrooks.adapters.mt5.feed import _MT5Module

    declared = {name for name in dir(_MT5Module) if not name.startswith("_")}
    assert "copy_rates_from_pos" in declared
    assert "copy_rates" not in declared, (
        "the bindings have no copy_rates; declaring it invites the same call again"
    )


def test_shutdown_is_safe_before_connecting_and_actually_shuts_down_after() -> None:
    fake = FakeMT5(mt5_rows(ramp(3)))
    feed = MT5Feed(fake)
    feed.shutdown()  # must not raise
    assert fake.shutdown_called is False

    feed.connect()
    feed.shutdown()
    assert fake.shutdown_called is True


def test_the_feed_works_as_a_context_manager() -> None:
    fake = FakeMT5(mt5_rows(ramp(3)))
    with MT5Feed(fake) as feed:
        feed.connect()
    assert fake.shutdown_called is True


# --------------------------------------------------------------------------
# The session: the Phase 19 finding, closed
# --------------------------------------------------------------------------


def test_the_session_reports_a_lifecycle_the_pipeline_cannot_reach() -> None:
    """`VALIDATION.md` §5.1, closed, on the exact bars Phase 19 recorded.

    `golden_fm_001` is a bull projection to 111.1 that bar 28 reached and bar 29
    rejected. Through `Analyzer.analyze()` that is `PROJECTED`, `age 0` — the
    registry is stateless and only seeds. Through the session it is
    `DEVELOPING`, touched, with exhaustion, which is the documented lifecycle.

    **Both are asserted.** The pipeline is unchanged, on purpose: the session adds
    a caller rather than editing the registry's contract, and a test that only
    checked the new reading would hide that the old one still stands.
    """
    meta = golden_meta("golden_fm_001")
    session = AnalysisSession()

    result = session.on_bars(golden_bars("golden_fm_001"), last_closed=meta["last_closed"])

    # The tracked reading: the lifecycle the Phase 19 finding said was unreachable.
    assert result.fade_source == "TRACKED"
    assert len(result.fades) == 1
    assert result.fades[0].state == "DEVELOPING"
    assert result.fades[0].touched is True
    assert result.fades[0].exhaustion_breadth == 3
    assert result.fades[0].age > 0

    # The pipeline reading, unchanged and still reported.
    pipeline = next(
        s for s in result.analysis.setups if s["detector"] == "FADING_MEASURED_MOVE"
    )
    assert pipeline["state"] == "PROJECTED"
    assert pipeline["age"] == 0

    # And the lifecycle changed the state, never the projection it is fading.
    assert result.fades[0].target_price == pytest.approx(pipeline["target_price"])


def test_the_session_does_not_turn_a_fade_into_a_trade() -> None:
    """A fade is an observation. Nothing here makes it actionable.

    `FADING_MEASURED_MOVE.md` is explicit that the lifecycle produces no entry, no
    stop and no order, and a `DEVELOPING` fade is exactly the sort of label that
    could turn into a signal by accident. The fixture already pins that the fade's
    *own* plan is vetoed for being late; this asserts the session did not add
    another route to the same mistake.
    """
    meta = golden_meta("golden_fm_001")
    result = AnalysisSession().on_bars(
        golden_bars("golden_fm_001"), last_closed=meta["last_closed"]
    )

    for fade in result.fades:
        assert "entry" not in fade.to_dict()
        assert "stop" not in fade.to_dict()
        assert "order" not in fade.to_dict()

    # The pipeline still plans the fade, unchanged — the session adds a reading, it
    # does not remove a plan. And the plan the decision actually chose is a
    # reversal, not the fade: reporting `DEVELOPING` changes what a caller can
    # *see*, not what is actionable.
    subjects = [p["subject"] for p in result.analysis.trade_plans]
    assert "FADING_MEASURED_MOVE" in subjects, "the session must not drop the plan"
    assert result.analysis.decision["subject"] != "FADING_MEASURED_MOVE"
    assert result.analysis.decision["action"] == "BUY"
    assert result.analysis.decision["subject"] == "REVERSAL_BULL#1"


def test_the_session_re_derives_rather_than_accumulating() -> None:
    """`RPC-1` for a new layer: the answer for a bar cannot depend on history.

    A session that kept fade setups in `self` and advanced them one bar per call
    would be the natural implementation and it would break the invariant: having
    seen bars 21..40 and then answering for bar 20 means holding state derived
    from bars the caller declared unavailable. So the session answers for bar 20
    the same way whether or not it has seen anything later.

    The order of the two calls is the point — the later series is analysed *first*
    — so a stateful implementation would have to leak to pass only by accident.
    """
    bars = golden_bars("golden_fm_001")
    meta = golden_meta("golden_fm_001")
    closed = meta["last_closed"]

    # A session that saw the future first.
    forward = AnalysisSession()
    forward.on_bars(bars, last_closed=closed)

    # A fresh one, and one that saw the past after the fact.
    fresh = AnalysisSession().on_bars(bars, last_closed=closed)
    backward_session = AnalysisSession()
    backward_session.on_bars(bars, last_closed=closed - 5)
    backward = backward_session.on_bars(bars, last_closed=closed)

    def signature(result: SessionResult) -> list[tuple[int, str, int]]:
        return [(f.id, f.state, f.age) for f in result.fades]

    assert signature(forward.on_bars(bars, last_closed=closed)) == signature(fresh)
    assert signature(backward) == signature(fresh)


def test_appending_bars_cannot_change_an_earlier_answers_fades() -> None:
    """`RPC-1` stated directly: later bars, earlier answer, same answer.

    The engine's own guarantee is asserted for `AnalysisResult`; a new layer
    inherits the contract by asserting it for itself, which is what
    `NON_REPAINT_CONTRACT.md` §7 requires of anything new.
    """
    bars = golden_bars("golden_fm_001")
    meta = golden_meta("golden_fm_001")
    closed = meta["last_closed"]
    session = AnalysisSession()

    before = session.on_bars(bars, last_closed=closed)
    # Price keeps going, well past the target, and the series grows.
    extended = bars + [
        {"time": T0 + (len(bars) + i) * M15, "o": 111.0 + i, "h": 112.0 + i,
         "l": 110.0 + i, "c": 111.5 + i}
        for i in range(5)
    ]
    after = session.on_bars(extended, last_closed=closed)

    assert [(f.id, f.state, f.age) for f in after.fades] == [
        (f.id, f.state, f.age) for f in before.fades
    ]


def test_the_session_honours_an_explicit_last_closed_and_clamps_beyond_the_data() -> None:
    """`RPC-4`: asking past the end means "the whole series", not an error.

    Hostile to the one thing a caller does by accident, so the session inherits
    the engine's clamping rather than inventing a stricter rule of its own.
    """
    bars = golden_bars("golden_fm_001")
    session = AnalysisSession()

    exact = session.on_bars(bars, last_closed=29)
    past = session.on_bars(bars, last_closed=10_000)

    assert exact.last_closed == 29
    assert past.last_closed == len(bars) - 1


def test_a_short_window_is_reported_rather_than_returning_a_clean_empty_reading() -> None:
    """Below the layers' own needs, and the caller is told.

    ATR has not settled and the market-state lookback is not populated, so an
    un-warned result would read as "no structure here" about a market that was
    never examined — the exact confusion `WARN_SHORT_SERIES` and the `layers` map
    exist to prevent.
    """
    from albrooks.adapters.mt5 import WINDOW_FLOOR, WINDOW_SHORT

    result = AnalysisSession().on_bars(ramp(10), last_closed=9)

    assert result.warnings == (WINDOW_SHORT,)
    assert len(result.analysis.bar_features) <= 10, (
        "the analysis is reported, not refused: a short window is a warning, and "
        "the engine's own warnings describe what degraded"
    )
    assert WINDOW_FLOOR > 10, "the floor must exclude the fixture, or the warning is dead code"


def test_a_window_at_or_above_the_floor_is_not_warned() -> None:
    from albrooks.adapters.mt5 import WINDOW_FLOOR

    result = AnalysisSession().on_bars(ramp(WINDOW_FLOOR + 5), last_closed=WINDOW_FLOOR + 4)
    assert result.warnings == ()


def test_a_volatility_free_series_produces_no_fades_rather_than_a_crash() -> None:
    """Zero ATR means every ATR-relative gate would reject everything.

    Returning an empty list is the honest answer: there is no projection to fade
    when there is no volatility to measure one against.
    """
    flat = [
        {"time": T0 + i * M15, "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0}
        for i in range(80)
    ]
    result = AnalysisSession().on_bars(flat, last_closed=79)
    assert result.fades == ()
    assert result.analysis.market_state["valid"] is False


def test_a_short_window_with_no_projection_reports_no_fades_without_erroring() -> None:
    result = AnalysisSession().on_bars(ramp(8), last_closed=7)
    assert result.fades == ()
    assert result.last_closed == 7


def test_the_session_reports_what_changed_between_two_calls() -> None:
    """`RPC-15`'s question, asked directly: what moved, and what held still?

    A caller watching a live series needs to know that the decision held while the
    fade advanced, or the reverse. Reporting only the current values would leave
    them unable to ask.
    """
    bars = golden_bars("golden_fm_001")
    session = AnalysisSession()

    first = session.changed_since_previous()
    assert first == {"first_call": True, "changed": False}

    session.on_bars(bars, last_closed=24)
    session.on_bars(bars, last_closed=29)
    change = session.changed_since_previous()

    assert change["first_call"] is False
    assert change["decision"]["from"] is not None
    assert "from" in change["fades"] and "to" in change["fades"]


def test_the_session_remembers_exactly_one_previous_result() -> None:
    """Two slots, and a documented reason for not having more.

    Holding every bar's result would make the session a database and would give it
    a second way to be wrong; the contract needs the previous answer, not a
    history. `changed_since_previous` is the only consumer of the older slot.
    """
    session = AnalysisSession()
    assert session.previous is None

    first = session.on_bars(ramp(80), last_closed=79)
    assert session.previous is first

    second = session.on_bars(ramp(80), last_closed=79)
    assert session.previous is second
    assert not hasattr(session, "_history")


def test_a_feed_with_nothing_closed_raises_rather_than_reporting_no_bars() -> None:
    """Every bar still forming is a connection-timing fact, not a market fact.

    The empty series would otherwise reach the engine and come back as `NO_BARS`,
    which is a statement about the market made because the fetch was too early.
    """
    feed = MT5Feed(FakeMT5(mt5_rows(ramp(3))))
    feed.connect("EURUSD")

    class EarlyFeed:
        def closed_bars(self, *args: Any, **kwargs: Any) -> FrozenSeries:
            return FrozenSeries(
                series=BarSeries([], symbol="EURUSD", timeframe="M15"),
                freeze=frozen_report(),
            )

    with pytest.raises(HistoryUnavailable, match="still forming"):
        AnalysisSession().on_feed(EarlyFeed(), "EURUSD", tf.M15, 3)


def frozen_report() -> Any:
    from albrooks.adapters.mt5 import FreezeReport

    return FreezeReport(now=T0, period_seconds=M15, bars_in=3, bars_out=0)


def test_the_session_works_over_a_whole_feed_path() -> None:
    """`MT5Feed.closed_bars` into `AnalysisSession.on_bars`, end to end.

    The integration the two halves exist for, driven with a fake terminal because
    the bindings are not installable on this machine. The freeze report travels
    with the result, so a caller can see which bar was dropped.
    """
    bars = ramp(80)
    feed = MT5Feed(FakeMT5(mt5_rows(bars), server_clock=T0 + 79 * M15 + M15 / 2))
    feed.connect("EURUSD")

    session = AnalysisSession()
    result = session.on_feed(feed, "EURUSD", tf.M15, 80)

    assert isinstance(result, SessionResult)
    assert result.freeze is not None
    assert result.freeze.dropped == 1
    assert result.last_closed == 78
    assert result.analysis.bars_processed == 79
    assert result.analysis.last_closed_bar == 78
    assert result.analysis.symbol == "EURUSD"
    assert result.analysis.timeframe == "M15"


def test_the_session_result_serialises_without_the_analysis_becoming_a_string() -> None:
    """`SessionResult.to_dict()` is the thing a consumer would send onward.

    `AnalysisResult.to_json()` uses `default=str`, so a nested dataclass can
    quietly become a repr in the output. The fades are the payload here, and they
    must survive as data.
    """
    meta = golden_meta("golden_fm_001")
    result = AnalysisSession().on_bars(
        golden_bars("golden_fm_001"), last_closed=meta["last_closed"]
    )

    payload = json.loads(json.dumps(result.to_dict()))

    assert payload["fade_source"] == "TRACKED"
    assert payload["fades"][0]["state"] == "DEVELOPING"
    assert payload["analysis"]["last_closed_bar"] == meta["last_closed"]


# --------------------------------------------------------------------------
# The architecture rule this package exists to satisfy
# --------------------------------------------------------------------------


def test_the_core_still_never_imports_the_adapters() -> None:
    """`scripts/check_no_mt5_dependency.py` runs in CI; this says why it must keep.

    The adapter exists *because* the core is platform-independent, so a core
    module reaching into it would make the check a formality. Run as a test rather
    than trusted to the script so a failure names the module.
    """
    import ast

    src = REPO / "src" / "albrooks"
    offenders: list[str] = []
    for path in src.rglob("*.py"):
        rel = path.relative_to(src).as_posix()
        if rel.startswith("adapters/mt5"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            if "MetaTrader5" in names or "adapters" in names:
                offenders.append(rel)
                break

    assert not offenders, f"core modules reach for the platform: {sorted(set(offenders))}"


def test_only_the_feed_names_the_terminal_bindings() -> None:
    """One import site, so the architectural rule has a surface small enough to see.

    `scripts/check_no_mt5_dependency.py` polices an allow-list; an allow-list with
    fifty entries in it is not a rule. `series.py` and `session.py` naming the
    bindings would mean the exclusion had to grow.
    """
    src = REPO / "src" / "albrooks" / "adapters" / "mt5"
    naming = [
        path.name
        for path in src.glob("*.py")
        if "import MetaTrader5" in path.read_text(encoding="utf-8")
    ]
    assert naming == ["feed.py"]


def test_the_adapter_errors_share_one_base_so_a_caller_can_catch_the_family() -> None:
    """Four types, one base — so `except MT5AdapterError` is possible.

    They are separate classes because the *recovery* differs, and they share a
    base because a caller who genuinely cannot act on the difference wants one
    handler rather than four.
    """
    for error in (MT5Unavailable, SymbolNotFound, HistoryUnavailable, TimeframeUnsupported):
        assert issubclass(error, MT5AdapterError)
    assert not issubclass(SeriesOrderError, MT5AdapterError), (
        "a malformed payload is a programming error, not a connection failure"
    )


def test_no_reachable_order_of_calls_produces_a_decision_for_a_forming_bar() -> None:
    """The adapter's obligation, checked through the session rather than the freeze.

    `RPC-1` and `RPC-15` are about the analysis; this is the boundary condition
    they assume. Whatever the caller does — freeze, pass through, truncate — the
    analysed bar is at or before the last bar the freeze retained, and the
    forming bar's own high and low appear nowhere in the result.
    """
    bars = ramp(80)
    forming_high = bars[-1]["h"] + 500.0
    bars[-1] = {**bars[-1], "h": forming_high}
    feed = MT5Feed(FakeMT5(mt5_rows(bars)))
    feed.connect("EURUSD")
    now = T0 + 79 * M15 + M15 / 2

    frozen = feed.closed_bars("EURUSD", tf.M15, 80, now=now)
    result = AnalysisSession().on_bars(frozen.series, freeze=frozen.freeze)

    assert result.last_closed == 78
    assert result.analysis.bars_processed == 79

    # RPC-2 for the adapter: no price that only exists in the forming bar.
    blob = json.dumps(result.to_dict(), default=str)
    assert str(forming_high) not in blob, "a forming-bar price reached the result"
    assert all(f["price"] <= max(b["h"] for b in bars[:-1]) for f in [
        {"price": s["price"]} for s in result.analysis.swings
    ])


# --------------------------------------------------------------------------
# What this phase did not do
# --------------------------------------------------------------------------


def test_no_mql5_sidecar_exists_and_the_parity_run_still_says_unverified() -> None:
    """The claim this phase must not make quietly.

    Phase 21's other half — an MQL5 port of the engine — needs MetaEditor and a
    terminal to be written *and validated*. Neither is available here, so
    `tests/parity/mql5/` is still empty and the harness still reports
    `UNVERIFIED`. This test is what makes that state a fact rather than a hope: it
    fails the moment a sidecar lands, so the documentation has to be updated in the
    same change that fills the harness.
    """
    from tests.parity.runner import UNVERIFIED, load_cases, run

    cases = load_cases()
    sidecars = list((REPO / "tests" / "parity" / "mql5").glob("*.mql5.json"))

    if sidecars:
        pytest.skip(
            "an MQL5 sidecar now exists; the parity status has changed and the "
            "Phase 21 documentation must be updated in this change"
        )

    report = run(cases)
    assert report.status == UNVERIFIED
    assert report.claims_parity is False
    assert not (REPO / "mql5").exists(), (
        "an mql5/ tree exists; if it is not a validated port, say so in the docs"
    )


def test_the_adapter_documentation_exists_and_names_what_is_missing() -> None:
    """`docs/algorithms/MT5_ADAPTER.md` is required, and must be honest.

    Same reasoning as the parity test above: a document nobody checks is how a
    phase's real status drifts from what the phase claims.
    """
    path = REPO / "docs" / "algorithms" / "MT5_ADAPTER.md"
    assert path.is_file(), "Phase 21 owes docs/algorithms/MT5_ADAPTER.md"

    text = path.read_text(encoding="utf-8")
    assert "mql5" in text.lower()
    assert "UNVERIFIED" in text, (
        "the adapter document must state that parity remains unverified, or a "
        "reader will infer the port exists"
    )



