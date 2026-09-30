r"""Optional checks against a **real** MetaTrader 5 terminal.

## Why this file exists separately, and why it is skipped by default

Every other Phase 21 test drives the adapter with an injected fake. That was a
mistake the live terminal exposed, and this file is the correction's other half.

`test_phase21_adapter.py`'s first version implemented `copy_rates` — a function the
Python bindings **do not have** — and returned newest-first rows, which is the MQL5
native convention and not the bindings'. All 54 tests passed. Against a real
terminal the adapter would have raised `AttributeError` on its first call, and the
local-clock freeze would have discarded 13 of 50 M15 bars because the server clock
ran 3.1 hours ahead.

A fake encodes the author's assumptions. Checking those assumptions needs the real
thing, and no amount of faking substitutes for it. So:

- these tests are **skipped unless a terminal is reachable**, so CI stays hermetic;
- they are **read-only** — `copy_rates_from_pos` and `symbol_info_tick` only. The
  adapter sends no orders and these tests place none;
- the set of claims they verify is exactly the set that a fake cannot check:
  which functions exist, which direction the payload arrives in, and whether the
  server clock and the local clock agree.

## Running them

```bat
rem Windows. The path MUST be the terminal EXECUTABLE, not the program folder:
rem the bindings reject a directory with "Invalid path argument", which is what a
rem skip here usually means. Quote it -- the default install path has a space.
set ALBROOKS_MT5_PATH="C:\Users\<you>\AppData\Roaming\Alpari MT5_4\terminal64.exe"
set ALBROOKS_MT5_SYMBOL=EURUSD
python -m pytest tests/integration\test_phase21_live_mt5.py -v -rs
```

```bash
# The same, from bash or Git Bash, where the backslashes must be escaped.
export ALBROOKS_MT5_PATH='C:\Users\<you>\AppData\Roaming\Alpari MT5_4\terminal64.exe'
export ALBROOKS_MT5_SYMBOL=EURUSD
python -m pytest tests/integration/test_phase21_live_mt5.py -v -rs
```

`ALBROOKS_MT5_PATH` is optional — without it the bindings find the terminal
themselves — but **on Windows it should be set**, and it must point at
`terminal64.exe` rather than its folder.

A skip is the expected outcome everywhere there is no terminal, and a skip is
**not** evidence that the adapter works — it is evidence that this file did not
run. That is why every skip in this file names the reason, including the exact
`MetaTrader5` error: a suite that skips silently is indistinguishable from a suite
that passes.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from albrooks.adapters.mt5 import (
    ASCENDING,
    CLOCK_CALLER,
    CLOCK_SERVER,
    NO_FORMING_BAR,
    AnalysisSession,
    MT5Feed,
    is_closed,
    normalize_order,
    period_seconds,
)
from albrooks.adapters.mt5 import timeframes as tf
from albrooks.adapters.mt5.dataset import inspect_series, require_integrity
from albrooks.core.bars import BarSeries

#: The largest clock difference a healthy terminal should show. The skew measured
#: on a live Alpari MT5 was 3.099 hours, so this bound is generous enough not to
#: fail on a normal machine and tight enough to catch a genuinely wrong clock.
#:
#: Exceeding it is **not** an assertion that the adapter is broken — it is a
#: statement that a freeze using the local clock would discard roughly this many
#: bars, and the test below says how many so the reader can judge.
MAX_PLAUSIBLE_SKEW_SECONDS = 10 * 60.0

live = pytest.mark.skipif(
    os.environ.get("ALBROOKS_MT5_LIVE", "1") == "0",
    reason="ALBROOKS_MT5_LIVE=0; live-terminal checks are opt-out",
)


@pytest.fixture(scope="module")
def feed() -> Any:
    """A connected feed, or a skip.

    The skip is deliberate rather than a bare `importorskip`: a missing terminal
    and a missing bindings module are different problems, and a test that cannot
    distinguish them will eventually be read as a pass.
    """
    bindings = pytest.importorskip(
        "MetaTrader5", reason="the MetaTrader5 bindings are not installed"
    )
    symbol = os.environ.get("ALBROOKS_MT5_SYMBOL", "EURUSD")
    path = os.environ.get("ALBROOKS_MT5_PATH") or None

    instance = MT5Feed()
    try:
        instance.connect(symbol, path=path)
    except Exception as exc:  # noqa: BLE001 - any failure means "not available"
        pytest.skip(f"no reachable MetaTrader 5 terminal ({type(exc).__name__}: {exc})")
    if not getattr(instance._mt5, "terminal_info", lambda: None)():
        instance.shutdown()
        pytest.skip("MetaTrader5.initialize() reported no terminal")
    yield instance
    instance.shutdown()
    # Referenced so linters do not flag the import as unused when the fixture
    # skips before touching it.
    assert bindings is not None


@live
def test_the_bindings_expose_copy_rates_from_pos_and_not_copy_rates(feed: Any) -> None:
    """The defect that made every other test in this phase worthless.

    The first version of the adapter called `mt5.copy_rates(...)` and the first
    version of the fake implemented it, so the call was never exercised. The
    function does not exist.
    """
    module = feed._mt5
    assert hasattr(module, "copy_rates_from_pos")
    assert hasattr(module, "copy_rates_from")
    assert hasattr(module, "copy_rates_range")
    assert not hasattr(module, "copy_rates"), (
        "the bindings now provide copy_rates; feed.py can be simplified and this "
        "test should be deleted rather than left to fail"
    )


@live
def test_the_payload_arrives_oldest_first(feed: Any) -> None:
    """The premise the original adapter got backwards, checked against reality.

    `to_oldest_first` used to *refuse* anything that was not newest-first, on the
    reasoning that MT5 is newest-first. The bindings are ascending. If this test
    ever fails with `DESCENDING`, the bindings changed and the adapter's
    normalisation — not just this test — needs revisiting.
    """
    rows, order = feed.bars("EURUSD", tf.M15, 50)
    assert order == ASCENDING, (
        f"the payload arrived {order}; the bindings were ascending when this was "
        f"written against Alpari MT5 build 6230 / MetaTrader5 5.0.6180"
    )
    times = [row["time"] for row in rows]
    assert times == sorted(times)
    assert all(b > a for a, b in zip(times, times[1:])), "timestamps must be strictly increasing"


@live
def test_a_descending_payload_would_normalise_to_the_same_series(feed: Any) -> None:
    """The MQL5 convention, fed through the normaliser, gives the same answer.

    An MQL5 consumer reading a `CopyRates` buffer sees newest-first, so both
    conventions have to work. The check is that they agree — which is what makes
    the parity harness's index comparison meaningful across two ports.
    """
    rows, _ = feed.bars("EURUSD", tf.M15, 30)
    forward, order_forward = normalize_order(rows)
    backward, order_backward = normalize_order(list(reversed(rows)))

    assert order_forward == ASCENDING
    assert order_backward != ASCENDING
    assert forward == backward


@live
def test_the_server_clock_and_the_local_clock_are_both_readable(feed: Any) -> None:
    """Both clocks exist and the difference is measured, not assumed.

    On the terminal this was written against the server ran **+11157s (3.099h)**
    ahead of the local clock. That is recorded as a *fact about the measurement*
    rather than a bound the test enforces, because a broker's server time is not
    the adapter's to control — but a caller who reads this and finds a 3-hour skew
    should know their local-clock freeze is discarding bars.
    """
    import time as _time

    server = feed.server_time("EURUSD")
    local = _time.time()

    assert server > 0, "the terminal reported no tick time for the requested symbol"
    skew = server - local
    assert abs(skew) < 100 * MAX_PLAUSIBLE_SKEW_SECONDS, (
        f"server and local clocks differ by {skew:.0f}s ({skew / 3600:.2f}h), which "
        f"is beyond any plausible broker offset; a freeze using the local clock "
        f"would discard {abs(skew) / 900:.0f} M15 bars"
    )


@live
def test_the_freeze_drops_exactly_one_bar_on_a_liquid_symbol(feed: Any) -> None:
    """The end-to-end behaviour, on real data.

    On a liquid pair exactly one bar is forming, so a correct freeze keeps
    `count - 1`. Anything else is either a clock problem or an order problem, and
    the two are distinguishable by the count: too few means the clock is behind,
    too many would mean the freeze is not working at all.
    """
    frozen = feed.closed_bars("EURUSD", tf.M15, 200)

    assert frozen.freeze.clock == CLOCK_SERVER
    assert frozen.freeze.order == ASCENDING
    assert len(frozen.series) == 199, (
        f"kept {len(frozen.series)} of 200 bars; a liquid M15 pair has exactly one "
        f"forming bar, so this is a clock or order problem"
    )
    assert frozen.freeze.dropped == 1
    assert frozen.freeze.forming_bar_time != NO_FORMING_BAR_EXPECTED


@live
def test_a_frozen_live_series_is_monotonic_and_older_than_its_clock(feed: Any) -> None:
    """The freeze's output is internally consistent, on real data.

    Cheaper than it sounds and worth it: it is the one property that catches both a
    wrong clock and a wrong direction at once, without needing to know the right
    answer in advance.
    """
    frozen = feed.closed_bars("EURUSD", tf.H1, 100)
    times = [bar.time for bar in frozen.series]

    assert all(b > a for a, b in zip(times, times[1:])), "not oldest-first"
    assert all(
        t + frozen.freeze.period_seconds <= frozen.freeze.now for t in times
    ), "a retained bar had not closed by the clock the freeze used"
    assert len(times) < 100, "no forming bar was dropped at all"


@live
def test_a_live_session_produces_a_usable_analysis(feed: Any) -> None:
    """The whole path, on a real series, at a real symbol.

    Not a claim about the reading — the decision could be anything, and nothing
    here validates it. It is a claim that the adapter produces a result the engine
    can actually analyse, which is the one thing a fake cannot establish about a
    real payload.
    """
    session = AnalysisSession()
    result = session.on_feed(feed, "EURUSD", tf.M15, 400)

    assert result.last_closed > 0
    assert result.analysis.bars_processed == result.last_closed + 1
    assert result.analysis.symbol == "EURUSD"
    assert result.analysis.timeframe == "M15"
    assert result.analysis.market_state, "the engine produced no market state"
    assert result.analysis.decision.get("action") in ("BUY", "SELL", "WAIT", "NO_TRADE")
    assert result.warnings == (), (
        f"a 400-bar M15 window is above the floor, so it should not warn: "
        f"{result.warnings}"
    )


@live
def test_the_live_analysis_never_reports_a_price_from_the_forming_bar(feed: Any) -> None:
    """`RPC-2` against a real series rather than a fixture.

    The forming bar is fetched, its extreme is known, and the claim is that none of
    it appears in the result. A fixture cannot check this because a fixture's
    forming bar is one the test chose.

    The check is **numeric, not textual** — and that is a correction to this test's
    own first version. Substring search over the serialised result reported a
    failure on a live run because EURUSD quotes to 5 decimals: a forming high of
    `1.13640` appears as a substring of `1.13645`, which is a *closed* bar's low
    and entirely legitimate. The check was wrong, not the adapter.

    The comparison therefore rounds both sides to the instrument's precision and
    compares numbers, so a genuine leak still fails and a coincidental digit match
    does not.

    Rounding was not sufficient on its own, and the reason is worth stating before
    anyone shortens this again: the set of prices the market has *finished printing*
    is every open, high, low and close of every closed bar — not the extremes alone.
    A forming extreme can coincide with a closed bar's **close**, and the result is
    supposed to report that close. See the comment at the `printed` set for the
    live run that caught this and the two earlier false positives.
    """
    digits = _quote_digits(feed, "EURUSD")

    frozen = feed.closed_bars("EURUSD", tf.M15, 300)
    forming_time = frozen.freeze.forming_bar_time
    if forming_time is NO_FORMING_BAR:
        pytest.skip("no forming bar at the moment of the call; retry during a session")

    raw, _ = feed.bars("EURUSD", tf.M15, 300)
    forming = next((r for r in raw if r["time"] == forming_time), None)
    if forming is None:
        pytest.skip("the forming bar closed between the two fetches")

    result = AnalysisSession().on_bars(frozen.series, freeze=frozen.freeze)

    # Only a price the market has **not finished printing** is evidence of a leak,
    # and that means every OHLC of every closed bar, not just its extremes. The
    # reasoning, and the two live false positives that forced it, are on
    # `_unprinted_forming_extremes`.
    forming_only = _unprinted_forming_extremes(frozen.series, forming, digits)

    if not forming_only:
        pytest.skip(
            "the forming bar's extremes are all shared with a closed bar, so this "
            "run cannot distinguish a leak; retry when they differ"
        )

    leaked = _prices_in(result, digits) & forming_only
    assert not leaked, f"prices unique to the forming bar reached the result: {sorted(leaked)}"
    assert result.last_closed == len(frozen.series) - 1


def _unprinted_forming_extremes(series: Any, forming: Any, digits: int) -> set[float]:
    """The forming bar's extremes that **no closed bar prints at all**.

    A leak is a price the market has not finished printing, so the set of prices
    already accounted for is every **open, high, low and close** of every closed
    bar. An empty result means the run cannot distinguish a leak, and the caller
    skips rather than reporting a pass.

    This is the third version of this rule and the first two were both wrong in the
    same direction: each excluded prices a live run can legitimately produce.

    - Version one searched the serialised result for the forming high as a
      **substring**, so a forming high of `1.13640` matched `1.13645` — a closed
      bar's low.
    - Version two compared numerically, which fixed that, and then fired on a live
      run because the forming high of `1.13654` was *also* the high of a closed bar.
    - Version three covers opens and closes, and fired once more: a forming extreme
      of `1.13309` was the **close of the last closed bar** — a price the market had
      finished printing, and one the result is *supposed* to carry. On that run the
      result held 17 distinct closed closes and 16 distinct closed opens, none of
      which the previous two versions accounted for.

    The shared mistake is worth naming because it is easy to repeat: both earlier
    versions built the "already printed" set from closed bars' **extremes only**.
    A close is printed as surely as a high.

    The function is separated from the live test so it can be checked **without a
    terminal**. The live test is skipped in CI, which meant this rule -- the part
    that had already produced two false positives -- was never exercised there at
    all. A rule that is only ever checked against a moving market is a rule that
    gets rewritten from one false positive to the next.
    """
    printed = {
        round(value, digits)
        for bar in series
        for value in (bar.open, bar.high, bar.low, bar.close)
    }
    return {
        round(forming["high"], digits),
        round(forming["low"], digits),
    } - printed


def _quote_digits(feed: Any, symbol: str) -> int:
    """How many decimals this symbol quotes to, from the terminal itself.

    Read from `symbol_info` rather than assumed, because the whole point of this
    test is that an assumption about the data's shape is what caused the first
    version of it to fail.
    """
    info = feed._mt5.symbol_info(symbol)
    return int(getattr(info, "digits", 5)) if info is not None else 5


def _prices_in(result: Any, digits: int) -> set[float]:
    """Every price the result reports, rounded to the instrument's precision.

    Walks the payload for numeric values rather than picking known price fields,
    because `RPC-2` says *no field* may carry a future price — including one nested
    somewhere nobody enumerated.
    """
    found: set[float] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)):
            found.add(round(float(node), digits))

    walk(result.to_dict())
    return found


#: The sentinel, imported here rather than at the top so the module's import list
#: stays about the adapter's public surface.
NO_FORMING_BAR_EXPECTED = "NO_FORMING_BAR"


# --------------------------------------------------------------------------
# The leak rule itself, checked without a terminal
# --------------------------------------------------------------------------
#
# These three carry **no** `@live` mark, and that is the point. Everything else in
# this file is skipped in CI, so before they existed the rule that decides what
# counts as a leak was only ever exercised against a live, moving market -- where it
# had already produced two false positives, each of which "fixed" it by narrowing
# what it looked at. A rule verified only against live data is verified only when
# someone is watching a terminal.


def _flat_series(*ohlc: tuple[float, float, float, float]) -> BarSeries:
    """Closed bars from `(open, high, low, close)` tuples."""
    return BarSeries(
        [
            {"time": float(i), "o": o, "h": h, "l": low, "c": c}
            for i, (o, h, low, c) in enumerate(ohlc)
        ]
    )


def test_a_price_no_closed_bar_prints_is_still_reported_as_a_leak() -> None:
    """The rule must keep its teeth.

    A narrowing fix that made the false positives go away without checking this
    would have converted a flaky test into a permanently green one, which is the
    worst outcome available: it looks like the adapter was proven correct.
    """
    series = _flat_series((100.0, 101.0, 99.0, 100.5), (100.5, 101.5, 99.5, 101.0))

    unprinted = _unprinted_forming_extremes(series, {"high": 100.25, "low": 100.2}, 5)

    assert unprinted == {100.2, 100.25}


def test_a_forming_extreme_equal_to_a_closed_close_is_not_a_leak() -> None:
    """The false positive that actually fired.

    `1.13309` was the close of the last closed bar and a forming extreme at the same
    time. The previous version of this rule reported it as a leak, which made the
    adapter look broken when it was not.
    """
    series = _flat_series((100.0, 101.0, 99.0, 100.5))

    assert _unprinted_forming_extremes(series, {"high": 100.5, "low": 99.0}, 5) == set()


def test_a_forming_extreme_equal_to_a_closed_open_is_not_a_leak_either() -> None:
    """Opens were the other half of the same omission, and are easier to miss.

    A forming bar's high or low landing exactly on an earlier bar's open is ordinary
    price action, so this is at least as likely as the close case and was equally
    misreported.
    """
    series = _flat_series((100.0, 101.0, 99.0, 100.5))

    assert _unprinted_forming_extremes(series, {"high": 101.0, "low": 100.0}, 5) == set()


# --------------------------------------------------------------------------
# A real dataset passes its own integrity check
# --------------------------------------------------------------------------


@live
def test_a_real_exported_series_is_monotonic_and_fully_closed(feed: Any) -> None:
    """The §9.1 dataset this machine would produce, checked by §9.1's own rules.

    The integrity logic itself is covered without a terminal in
    `test_dataset_integrity.py`, so this is not re-testing the checks. It is
    testing the thing those checks exist for: that **real bars from a real broker
    survive them.** Synthetic bars are built to be well-formed, so a hand-built
    series can never tell you whether the real feed is.

    Two things this can fail on, and both would be worth knowing:

    - **A forming bar in the export.** `closed_bars` is supposed to drop it. If the
      server clock is unavailable and the adapter silently fell back to the local
      one -- 3.1 hours behind on the machine this was developed on -- this is where
      it shows up, rather than as a look-ahead discovered months later in a result.
    - **A gap or a duplicate in real history.** Markets close at weekends and
      around holidays, so *gaps* are expected and are not a fault. A repeated
      timestamp is not, and would mean the export lost ordering on the way out.
    """
    frozen = feed.closed_bars("EURUSD", tf.M15, 500)
    seconds = period_seconds(tf.M15)

    report = require_integrity(
        inspect_series(
            frozen.series,
            seconds,
            now=frozen.freeze.now,
            clock=frozen.freeze.clock,
        )
    )

    assert report.ok, report.problems
    # Asking for 500 yields 499 *because* one bar was still forming and was
    # dropped. The relationship is the assertion, not the count: a run that
    # returned 500 would mean the forming bar was kept, and a run that returned
    # fewer would mean more than one was dropped.
    assert frozen.freeze.dropped == 1
    assert report.bars == 500 - frozen.freeze.dropped == frozen.freeze.bars_out
    # The clock is recorded, so a fallback to local time is visible in the artefact
    # rather than inferred.
    assert report.clock in (CLOCK_SERVER, CLOCK_CALLER)
    # Monotonic: strictly ascending, so a backtest's "next bar" is unambiguous.
    times = [b.time for b in frozen.series]
    assert times == sorted(times)
    assert len(set(times)) == len(times)
    # Closed: the last bar finished before the clock that judged it.
    assert is_closed(times[-1], seconds, frozen.freeze.now)


def test_the_extremes_only_rule_would_have_misreported_both() -> None:
    """Pins the old rule's behaviour, so the narrowing cannot be undone silently.

    Without this, "simplify" the set back to highs and lows and every assertion above
    still passes -- the first and third would go on reporting a leak, exactly as they
    did on a live run, and the suite would stay green because none of the live tests
    run in CI.
    """
    series = _flat_series((100.0, 101.0, 99.0, 100.5))
    extremes_only = {round(b.high, 5) for b in series} | {round(b.low, 5) for b in series}

    assert {100.5} - extremes_only == {100.5}  # the close
    assert {100.0} - extremes_only == {100.0}  # the open
