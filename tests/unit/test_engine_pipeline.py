"""Pipeline tests for `Analyzer.analyze()`.

The individual detectors were tested against their own fixtures for Phases 2-10.
These tests cover what only the pipeline can be wrong about: the wiring itself.
A detector that is correct in isolation can still be connected wrongly, called
with the wrong index, fed a stale ATR, or handed a bar range that includes the
future. Those are the failures here, and none of them are visible from any
single detector's tests.

The closed-bar contract is the load-bearing property. It is stated in
`docs/architecture/ARCHITECTURE.md` §6 as a single invariant:

> The analysis for a given bar index is identical whether or not later bars exist.

Two tests below assert exactly that, by appending future bars and re-analysing
the same index.
"""

from __future__ import annotations

import json

import pytest

from albrooks.engine.analyzer import (
    REASON_ATR_UNAVAILABLE,
    REASON_NEGATIVE_LAST_CLOSED,
    REASON_NO_BARS,
    WARN_SHORT_SERIES,
    Analyzer,
)
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.engine.state import AnalysisResult

CFG = AnalyzerConfig(range_lookback=20)

#: Fields describing the *input* rather than the analysis, excluded when
#: comparing two runs over different amounts of data.
INPUT_FIELDS = frozenset({"bars_processed"})


def _derived(result: AnalysisResult) -> dict:
    """Everything the engine inferred, with input-describing fields removed."""
    return {
        k: v for k, v in result.to_dict().items() if k not in INPUT_FIELDS
    }


def _bars(n: int = 60) -> list[dict[str, float]]:
    """A deterministic trending series: rally, pullback, rally.

    Deterministic rather than random so a failure is always reproducible and a
    golden fixture can be written against it later.
    """
    out: list[dict[str, float]] = []
    price = 100.0
    for i in range(n):
        if i < n * 0.33:
            o, h, low, c = price, price + 1.0, price - 1.0, price + 0.8
        elif i < n * 0.5:
            o, h, low, c = price, price + 1.0, price - 1.0, price - 0.4
        else:
            o, h, low, c = price, price + 1.2, price - 0.6, price + 1.0
        price = c
        out.append({"o": o, "h": h, "l": low, "c": c})
    return out


# --------------------------------------------------------------------------
# Bar input
# --------------------------------------------------------------------------


def test_short_and_long_bar_keys_are_both_accepted() -> None:
    """Regression test for a real bug the pipeline exposed.

    `Bar.from_dict` read only `open`/`high`/`low`/`close`, while every detector's
    own `_get_ohlc` and the README both accept the short `o`/`h`/`l`/`c` form. So
    `Analyzer.analyze()` — the documented public entry point — rejected input the
    rest of the engine read happily.
    """
    from albrooks.core.bars import Bar, BarSeries

    short = Bar.from_dict({"o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5})
    long = Bar.from_dict({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5})
    assert (short.open, short.high, short.low, short.close) == (
        long.open,
        long.high,
        long.low,
        long.close,
    )

    # both spellings work through the public entry point
    for bars in (
        [{"o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5}] * 30,
        [{"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5}] * 30,
    ):
        assert Analyzer().analyze(bars).bars_processed == 30

    assert BarSeries([{"o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5}])[0].close == 1.5


def test_long_keys_win_when_a_mapping_carries_both_spellings() -> None:
    """An alias must not silently override the canonical field."""
    from albrooks.core.bars import Bar

    bar = Bar.from_dict({"o": 99.0, "open": 1.0, "h": 2.0, "l": 0.5, "c": 1.5})
    assert bar.open == 1.0


def test_a_bar_missing_every_price_field_says_so() -> None:
    """The error names the field and shows what was supplied, not a bare KeyError."""
    from albrooks.core.bars import Bar

    with pytest.raises(KeyError) as excinfo:
        Bar.from_dict({"time": 1.0, "volume": 3.0})
    message = str(excinfo.value)
    assert "'open'" in message and "'o'" in message
    assert "volume" in message  # shows what was actually supplied


# --------------------------------------------------------------------------
# The pipeline is actually wired
# --------------------------------------------------------------------------


def test_analyze_produces_real_output_not_a_placeholder() -> None:
    """The original bug: analyze() returned hard-coded empties.

    Each assertion is on a layer that a placeholder would have left empty, so
    this fails if any of them is disconnected again.
    """
    result = Analyzer(CFG).analyze(_bars(), symbol="TEST", timeframe="H1")

    assert result.bars_processed == 60
    assert result.last_closed_bar == 59
    assert result.market_state["valid"] is True
    assert result.market_state["mode"] != "UNKNOWN"
    assert result.swings, "no swings detected on a 60-bar trending series"
    assert result.legs, "no legs built from the swings"
    assert result.bar_features, "no per-bar features"
    assert result.measured_moves, "no measured moves on a trending series"
    assert result.trends and result.trends[0]["valid"] is True


def test_the_placeholder_reason_is_gone() -> None:
    """`ENGINE_INITIALIZING` was the old marker; it must not come back."""
    result = Analyzer(CFG).analyze(_bars())
    assert result.decision["reason"] != "ENGINE_INITIALIZING"
    assert "PENDING_PHASE4" not in json.dumps(result.to_dict())


def test_every_specification_layer_is_present_and_reports_whether_it_ran() -> None:
    """An empty layer and an absent layer mean different things.

    The specification names six layers the result did not have at all. They exist
    now, and `layers` records which ran, so a caller can tell "no channel found"
    from "channel detection not implemented".
    """
    result = Analyzer(CFG).analyze(_bars())
    for name in (
        "trends",
        "channels",
        "pullbacks",
        "breakouts",
        "reversals",
        "evidence",
    ):
        assert hasattr(result, name), name
    assert result.layers["swings"] is True
    assert result.layers["trade_plans"] is False
    assert result.layers["decision"] is False
    assert set(result.unimplemented_layers) == {"trade_plans", "decision"}


def test_result_serializes_to_json() -> None:
    """Phase 22 depends on this; a dataclass leaking through would break it."""
    result = Analyzer(CFG).analyze(_bars())
    payload = json.loads(result.to_json())
    assert payload["bars_processed"] == 60
    assert payload["last_closed_bar"] == 59
    assert isinstance(payload["measured_moves"], list)
    assert isinstance(payload["evidence"], list)



# --------------------------------------------------------------------------
# The closed-bar contract
# --------------------------------------------------------------------------


def test_analysis_of_a_bar_is_identical_whether_or_not_future_bars_exist() -> None:
    """The architecture's central invariant, asserted end to end.

    Appending 40 bars after the analysis point must not change a single field.
    This is the test that would catch a detector reading past `last_closed`, and
    it covers every layer at once, which no per-detector test can do.
    """
    bars = _bars()
    analyzer = Analyzer(CFG)
    at_bar = 39

    before = analyzer.analyze(bars, last_closed=at_bar)
    after = analyzer.analyze(bars + _bars(40), last_closed=at_bar)

    # `bars_processed` is excluded deliberately: it counts the bars supplied, so it
    # is a property of the *input*, not of the analysis. Comparing it would fail for
    # the right reason but assert the wrong thing — the caller is expected to know
    # how much data they passed. Everything the engine *derived* must match.
    assert _derived(before) == _derived(after)
    assert before.bars_processed == 60 and after.bars_processed == 100


def test_bar_features_stop_at_last_closed() -> None:
    """Regression test for a real leak found while wiring the pipeline.

    `analyze_series` has no `last_closed` of its own; it always runs to the end of
    the series handed to it. The pipeline initially passed the full series, so a
    caller analysing bar 39 of 60 received per-bar features for bars 40-59 —
    future prices, inside a result the architecture promises is closed-bar only.
    """
    bars = _bars()
    at_bar = 39
    result = Analyzer(CFG).analyze(bars, last_closed=at_bar)

    assert result.bar_features, "features should still be produced for the window"
    assert len(result.bar_features) == at_bar + 1
    assert max(f["index"] for f in result.bar_features) == at_bar


def test_no_field_carries_a_price_from_beyond_last_closed() -> None:
    """The stronger form: no future price may appear anywhere in the result.

    Checks actual numbers rather than bar indices, so it also catches a future
    price smuggled into a field that carries no index of its own.

    Only prices that occur *exclusively* after `last_closed` count as evidence.
    The fixture cycles, so many future prices also appear inside the window; a
    price seen earlier is not a leak however many times it recurs later.
    """
    bars = _bars()
    at_bar = 39

    def prices(rows: list[dict[str, float]]) -> set[float]:
        return {p for b in rows for p in (b["o"], b["h"], b["l"], b["c"])}

    past = prices(bars[: at_bar + 1])
    future_only = prices(bars[at_bar + 1 :]) - past
    assert future_only, "fixture must have prices unique to the future window"

    text = json.dumps(Analyzer(CFG).analyze(bars, last_closed=at_bar).to_dict())
    for price in future_only:
        assert f": {price}" not in text and f": {price}," not in text, price


def test_future_bars_do_change_the_output_for_the_newest_bar() -> None:
    """The converse check, so the test above cannot pass by being inert.

    If appending bars changed nothing even at the newest index, the pipeline
    would be ignoring its input entirely, and the lookahead test above would be
    satisfied for the wrong reason.
    """
    bars = _bars()
    analyzer = Analyzer(CFG)

    short = analyzer.analyze(bars)
    long = analyzer.analyze(bars + _bars(40))

    assert short.to_dict() != long.to_dict()
    assert long.bars_processed == 100


def test_last_closed_past_the_data_is_clamped_not_rejected() -> None:
    """Matches every detector's own behaviour; a raise here would be inconsistent."""
    bars = _bars()
    analyzer = Analyzer(CFG)

    clamped = analyzer.analyze(bars, last_closed=999)
    assert clamped.last_closed_bar == 59
    assert clamped.to_dict() == analyzer.analyze(bars).to_dict()


def test_last_closed_selects_the_analysis_point() -> None:
    bars = _bars()
    analyzer = Analyzer(CFG)

    early = analyzer.analyze(bars, last_closed=29)
    late = analyzer.analyze(bars, last_closed=59)

    assert early.last_closed_bar == 29
    assert late.last_closed_bar == 59
    # both report the full series, since all the bars are present
    assert early.bars_processed == late.bars_processed == 60
    assert early.to_dict() != late.to_dict()


def test_no_reported_structure_comes_from_after_last_closed() -> None:
    """Every swing, leg and projection must be inside the analysed window."""
    bars = _bars()
    at_bar = 45
    result = Analyzer(CFG).analyze(bars, last_closed=at_bar)

    for swing in result.swings:
        assert swing["bar_index"] <= at_bar
        assert swing["confirmed_bar_index"] <= at_bar
    for leg in result.legs:
        assert leg["end_index"] <= at_bar
    for move in result.measured_moves:
        assert move["anchor_bar"] <= at_bar
        if move["reference_leg"] is not None:
            assert move["reference_leg"]["confirmed_index"] <= at_bar


# --------------------------------------------------------------------------
# Degenerate input explains itself instead of claiming an empty market
# --------------------------------------------------------------------------


def test_no_bars_reports_no_bars() -> None:
    """Empty lists here would be a claim about a market that was never observed."""
    result = Analyzer().analyze([])
    assert result.bars_processed == 0
    assert result.market_state["reason"] == REASON_NO_BARS
    assert result.decision["reason"] == REASON_NO_BARS
    assert result.warnings == [REASON_NO_BARS]
    assert not any(result.layers.values()), "no layer should claim to have run"


def test_negative_last_closed_reports_itself() -> None:
    result = Analyzer().analyze(_bars(), last_closed=-5)
    assert result.market_state["reason"] == REASON_NEGATIVE_LAST_CLOSED
    assert not any(result.layers.values())


def test_a_flat_series_reports_no_volatility_rather_than_no_structure() -> None:
    """The failure mode this guards is silent and very misleading.

    Every ATR-relative gate rejects a zero-volatility bar, so a naive pipeline
    returns a clean, empty, entirely plausible-looking result claiming a market
    with no structure. The truth is that there was nothing to measure.
    """
    flat = [{"o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0} for _ in range(40)]
    result = Analyzer(CFG).analyze(flat)

    assert result.market_state["reason"] == REASON_ATR_UNAVAILABLE
    assert result.decision["reason"] == REASON_ATR_UNAVAILABLE
    assert not result.swings
    assert not result.measured_moves
    assert not any(result.layers.values())


def test_a_short_series_warns_that_its_atr_is_not_settled() -> None:
    """Fewer bars than the ATR period is a caveat about the input, not the market."""
    result = Analyzer(CFG).analyze(_bars(8))
    assert WARN_SHORT_SERIES in result.warnings
    # the analysis still runs; it just says so
    assert result.layers["market_state"] is True


def test_a_single_bar_does_not_crash() -> None:
    result = Analyzer().analyze([{"o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0}])
    assert isinstance(result, AnalysisResult)
    assert result.bars_processed == 1


def test_barseries_input_keeps_its_metadata() -> None:
    """A caller who built a BarSeries expects their symbol and timeframe preserved."""
    from albrooks.core.bars import BarSeries

    series = BarSeries(_bars(), symbol="EURUSD", timeframe="M15")
    result = Analyzer(CFG).analyze(series)
    assert result.symbol == "EURUSD"
    assert result.timeframe == "M15"
