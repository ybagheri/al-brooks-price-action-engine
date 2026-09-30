"""Tests for dataset integrity (`VALIDATION.md` §9.1) — no terminal required.

Every test here is a pure function over a hand-built series, so **this file runs in
CI**. That is the whole reason `inspect_series` was written as a free function
rather than inside the export script: a check that only ever runs against a live
terminal is a check that gets "fixed" from one false positive to the next, which is
what happened three times over to the forming-bar leak test in
`test_phase21_live_mt5.py`.

The order of the tests is the order of the properties, and each one names the way
failing it turns a measurement into a fiction — because "why does this matter" is
the part that decays first, and a check whose reason has been forgotten is a check
someone will eventually relax.
"""

from __future__ import annotations

import pytest

from albrooks.adapters.mt5.dataset import (
    DatasetIntegrityError,
    SeriesIntegrity,
    inspect_series,
    require_integrity,
)
from albrooks.adapters.mt5.series import CLOCK_SERVER
from albrooks.core.bars import BarSeries

M15 = 15 * 60.0


def bars(*ohlc: tuple[float, float, float, float], start: float = 0.0) -> BarSeries:
    """Ascending bars, `period` apart, from `(open, high, low, close)` tuples."""
    return BarSeries(
        [
            {"time": start + i * M15, "o": o, "h": h, "l": low, "c": c}
            for i, (o, h, low, c) in enumerate(ohlc)
        ]
    )


#: Comfortably past the end of the last bar in the fixtures below.
NOW = 10_000.0


def a_clean_series(count: int = 5) -> BarSeries:
    return bars(*[(100.0, 101.0, 99.0, 100.5)] * count)


# --------------------------------------------------------------------------
# A clean series, and what the report carries
# --------------------------------------------------------------------------


def test_a_clean_series_passes_and_reports_the_clock_it_used() -> None:
    """The verdict records *how* it was reached, not just that it was reached.

    The adapter measured a 3.1-hour skew between a real terminal's server clock and
    the local one. A verdict that does not name the clock cannot be compared with a
    later one, and cannot be argued about when the two disagree.
    """
    report = inspect_series(a_clean_series(), M15, now=NOW, clock=CLOCK_SERVER)

    assert report.ok
    assert report.problems == ()
    assert report.bars == 5
    assert report.clock == CLOCK_SERVER
    assert report.now == NOW
    assert report.first_time == 0.0
    assert report.last_time == 4 * M15
    assert require_integrity(report) is report


def test_the_report_serialises_so_a_dataset_can_carry_its_own_verdict() -> None:
    """Provenance has to include the check, not merely the data.

    A dataset nobody recorded as having been verified is indistinguishable from one
    that was verified and failed.
    """
    payload = inspect_series(a_clean_series(), M15, now=NOW).to_dict()

    assert payload["ok"] is True
    assert payload["problems"] == []
    assert payload["clock"] == CLOCK_SERVER or payload["clock"]
    assert payload["bars"] == 5


# --------------------------------------------------------------------------
# 1. Strictly ascending times
# --------------------------------------------------------------------------


def test_a_duplicated_bar_time_is_refused() -> None:
    """A repeated timestamp makes "the next bar" ambiguous.

    `normalize_order` already refuses a mis-ordered *payload*. This refuses a
    mis-ordered *file*, which is the thing that survives a round trip through disk
    and then gets fed to a backtest that resolves the ambiguity silently.
    """
    series = BarSeries(
        [
            {"time": 0.0, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5},
            {"time": 0.0, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5},
        ]
    )

    report = inspect_series(series, M15, now=NOW)

    assert not report.ok
    assert any("duplicated" in p for p in report.problems)


def test_a_descending_bar_time_is_refused() -> None:
    """Newest-first is a legitimate MT5 convention and a broken file.

    `normalize_order` accepts both directions, and correctly. This runs *after*
    normalisation, so descending here means the ordering was lost in storage rather
    than that a convention was used — which is why the two disagree on purpose.
    """
    series = BarSeries(
        [
            {"time": M15, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5},
            {"time": 0.0, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5},
        ]
    )

    report = inspect_series(series, M15, now=NOW)

    assert not report.ok
    assert any("ascending order" in p for p in report.problems)


def test_a_duplicate_and_a_descent_are_reported_separately() -> None:
    """They need different fixes, so they are different faults.

    A duplicate means a bar reached the file twice; a descent means the ordering was
    lost. Reporting only "not ascending" would leave a reader guessing which.
    """
    series = BarSeries(
        [
            {"time": 2 * M15, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5},
            {"time": 2 * M15, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5},
            {"time": 0.0, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5},
        ]
    )

    report = inspect_series(series, M15, now=NOW)

    assert sum("duplicated" in p for p in report.problems) == 1
    assert sum("ascending order" in p for p in report.problems) == 1


# --------------------------------------------------------------------------
# 2. Every bar closed
# --------------------------------------------------------------------------


def test_a_forming_bar_is_refused_and_named_by_its_open_time() -> None:
    """This is `RPC-1` applied to a file, and a look-ahead is the reason.

    A forming bar's high and low are still moving, so any level "reached" inside it
    may never be reached. A dataset containing one measures the future.
    """
    series = bars((100.0, 101.0, 99.0, 100.5), (100.5, 101.5, 99.5, 101.0))
    # The second bar opened at M15 and needs until 2 * M15 to close.
    now = 2 * M15 - 1.0

    report = inspect_series(series, M15, now=now, clock=CLOCK_SERVER)

    assert not report.ok
    assert any("not closed" in p and str(M15) in p for p in report.problems)


def test_a_bar_that_closed_exactly_now_is_closed() -> None:
    """The boundary is inclusive, and the reason is defensible.

    A bar that closed exactly at `now` has closed, and the next observation is what
    a live consumer would read at that same instant. Getting this wrong by one
    second discards a bar or keeps a forming one on every single call.
    """
    series = bars((100.0, 101.0, 99.0, 100.5))
    now = M15

    assert inspect_series(series, M15, now=now).ok


# --------------------------------------------------------------------------
# 3. What `Bar` already guarantees, and what it does not
# --------------------------------------------------------------------------


def test_a_bar_whose_high_is_below_its_close_cannot_be_constructed() -> None:
    """OHLC coherence is refused at construction, which is stronger than checking.

    This is why `inspect_series` has no coherence check of its own. The guarantee
    lives in `Bar.__post_init__`, so a corrupt bar is not merely detected further
    down the pipeline — it is **unrepresentable**, including when a series is built
    from raw dictionaries, which is how every dataset is loaded.

    The test is here to keep that guarantee from being quietly relaxed. If someone
    loosens `Bar`, this fails, and the *absence* of a coherence check in
    `inspect_series` stops being safe.
    """
    with pytest.raises(ValueError, match="close .* outside"):
        BarSeries([{"time": 0.0, "o": 100.0, "h": 100.5, "l": 99.0, "c": 101.0}])


def test_a_bar_whose_open_is_above_its_high_cannot_be_constructed() -> None:
    """The mirror case, and a separate comparison in the same constructor."""
    with pytest.raises(ValueError, match="open .* outside"):
        BarSeries([{"time": 0.0, "o": 102.0, "h": 101.0, "l": 99.0, "c": 100.5}])


def test_a_non_positive_price_is_refused_and_bar_does_not_catch_it() -> None:
    """The one price rule `Bar` does **not** enforce, so this module has to.

    Positivity is representable, and it poisons every ratio the bar appears in —
    ATR above all, being a denominator. One non-positive bar does not make one bad
    ATR; it makes every downstream number involving it meaningless while still
    returning a number.
    """
    # Constructible: `Bar` allows it, which is the whole point of the next assertion.
    series = bars((100.0, 101.0, 0.0, 100.5))
    assert len(series) == 1

    report = inspect_series(series, M15, now=NOW)

    assert not report.ok
    assert any("non-positive" in p for p in report.problems)


def test_an_open_equal_to_the_high_is_allowed() -> None:
    """`Bar`'s bounds are inclusive, and a test that rejected them would be wrong.

    A bar that opens at its high and closes at its low is real and common. Tightening
    this to a strict inequality would reject ordinary data and train everyone to
    ignore the check, which is worse than not having it.
    """
    series = bars((101.0, 101.0, 99.0, 99.0))

    assert inspect_series(series, M15, now=NOW).ok


# --------------------------------------------------------------------------
# 4. Not empty
# --------------------------------------------------------------------------


def test_an_empty_series_is_refused_rather_than_scored_as_zero() -> None:
    """The same refusal `events.py` makes, for the same reason.

    An empty sample has no share. Reporting `0.0` for one is a fabricated number,
    and it is fabricated in the direction that looks like a result.
    """
    report = inspect_series(BarSeries([]), M15, now=NOW)

    assert not report.ok
    assert any("empty" in p for p in report.problems)


# --------------------------------------------------------------------------
# The refusal itself
# --------------------------------------------------------------------------


def test_require_integrity_raises_and_lists_every_fault_at_once() -> None:
    """One run should say everything wrong with a file, not one thing per run.

    A caller fixing a dataset should not have to re-export five times to discover
    five separate problems.
    """
    series = BarSeries(
        [
            {"time": 0.0, "o": 100.0, "h": 101.0, "l": 0.0, "c": 100.5},  # non-positive
            {"time": 0.0, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5},  # duplicate
        ]
    )

    with pytest.raises(DatasetIntegrityError) as excinfo:
        require_integrity(inspect_series(series, M15, now=NOW))

    message = str(excinfo.value)
    assert "duplicated" in message
    assert "non-positive" in message
    assert "2 bar(s)" in message  # the count is of bars scanned, not a fault


def test_the_error_names_the_clock_so_a_wrong_one_is_visible() -> None:
    """A failure on the wrong clock is a different failure from one on the right.

    The skew between the server and local clocks was 3.1 hours, which is thirteen
    M15 bars. A verdict that does not say which clock produced it cannot be
    distinguished from one produced on the other.
    """
    with pytest.raises(DatasetIntegrityError) as excinfo:
        require_integrity(inspect_series(BarSeries([]), M15, now=NOW, clock=CLOCK_SERVER))

    assert CLOCK_SERVER in str(excinfo.value)


def test_a_clean_report_is_returned_unchanged_so_the_verdict_can_be_kept() -> None:
    """A writer needs the report it just proved, not a bare `None`."""
    report = inspect_series(a_clean_series(), M15, now=NOW)

    assert require_integrity(report) is report
    assert isinstance(report, SeriesIntegrity)
