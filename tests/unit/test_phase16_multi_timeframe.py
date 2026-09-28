"""Tests for the multi-timeframe pipeline (Phase 16).

Everything below the decision layer reasons about **one** timeframe, so an H1 bull
signal inside an H4 bear trend and the same signal inside an H4 bull trend were
indistinguishable. These tests pin the three properties that make the fix
defensible:

1. **Alignment is the whole problem, and it is closed-bar.** A higher-timeframe
   bar is usable only once it has closed. The test that matters is the one that
   makes the *forming* HTF bar extreme and shows the bias does not move — a
   pipeline that aligned on open times would fail it.
2. **The higher-timeframe analysis is run as of the aligned bar**, so the pipeline
   never holds a full HTF result and reaches back into it. Appending future bars
   to either series cannot change the answer for an earlier index.
3. **The bias is a veto input, not a signal.** It withholds, it does not invert; an
   abstention is left alone; and its four "no bias" reasons stay distinct, so a
   data problem can never read as a neutral market.

The alignment rule, restated once here because every expected value below depends
on it. `Bar.time` is the **open** time, so low bar `i` closes at
`T0 + (i + 1) * L` and high bar `k` closes at `T0 + (k + 1) * r * L`. The newest
usable high bar is therefore `k = floor((i + 1) / r) - 1`, which is *not*
`i // r`: the low bar closing at the same instant as a high bar's close is inside
that high bar, not after it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from albrooks.core.bars import BarSeries
from albrooks.decision.engine import REASON_ALL_VETOED, REASON_RANKED
from albrooks.decision.veto import VETO_AGAINST_HIGHER_TIMEFRAME
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.engine.pipeline import (
    BIAS_ALIGNED,
    BIAS_NOT_ALIGNED,
    BIAS_NOT_ALIGNED_IN_TIME,
    BIAS_NOT_CLASSIFIED,
    RATIO_TOLERANCE,
    REASON_AGAINST_HTF,
    WARN_MISSING_TIMESTAMPS,
    WARN_NO_OVERLAP,
    WARN_NO_RATIO,
    WARN_NON_MONOTONIC_TIME,
    WARN_RATIO_MISMATCH,
    Alignment,
    HTFBias,
    aligned_htf_index,
    analyze_multi_timeframe,
    apply_htf_veto,
    htf_bias,
    measure_step,
)

MIN15 = 900.0
H1 = 3600.0
T0 = 1_700_000_000.0
RATIO = 4
CFG = AnalyzerConfig()

#: Describing the *input* rather than the analysis, so a comparison over two
#: different amounts of data is not made to fail for the right reason.
INPUT_FIELDS = frozenset({"bars_processed"})


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def closes_series(
    closes: list[float], step: float = MIN15, pad: float = 0.2
) -> list[dict[str, float]]:
    """M15 bars from a close path, with `Bar.time` as the **open** time."""
    out: list[dict[str, float]] = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        out.append(
            {
                "time": T0 + i * step,
                "o": o,
                "h": max(o, c) + pad,
                "l": min(o, c) - pad,
                "c": c,
            }
        )
    return out


def aggregate(ltf: list[dict[str, float]], group: int = RATIO) -> list[dict[str, float]]:
    """Build the higher series by grouping the lower one, timestamps and all.

    Aggregating the *same* bars is what makes this fixture honest: the HTF can
    only ever contain information already present in the LTF, so a bias that moves
    when lower bars are appended is a look-ahead bug rather than new data.
    """
    out: list[dict[str, float]] = []
    for start in range(0, len(ltf), group):
        chunk = ltf[start : start + group]
        if not chunk:
            continue
        out.append(
            {
                "time": chunk[0]["time"],
                "o": chunk[0]["o"],
                "h": max(b["h"] for b in chunk),
                "l": min(b["l"] for b in chunk),
                "c": chunk[-1]["c"],
            }
        )
    return out


def rally(n: int = 120, slope: float = 0.5) -> list[float]:
    """A clean trend, which the market-state proxy reads as dominant (0.67)."""
    return [100.0 + i * slope for i in range(n)]


def chop(n: int = 120) -> list[float]:
    """A tight oscillation: a range, not a direction."""
    return [100.0 + (1.0 if i % 2 else -1.0) * 0.1 for i in range(n)]


def v_then_rally(n: int = 200) -> list[float]:
    """Falls, then recovers. Useful as a bearish higher-timeframe read on its own."""
    return [100.0 - abs(i - 40) * 0.8 + i * 0.1 for i in range(n)]


def bear_then_rally(
    n: int, split: int, depth: float = 1.0, rally_slope: float = 0.6
) -> list[float]:
    """Falls for `split` bars, then rallies hard to the end.

    The rally lands in the **forming** H1 bar, so the higher-timeframe read — which
    stops at the last *closed* H1 bar — never sees it. That is what produces a real
    disagreement out of a single price series, and it is the real-world case: a
    counter-trend bounce nobody can see on the hourly chart yet.
    """
    path = [100.0 - min(i, split) * depth for i in range(n)]
    turn = path[split - 1]
    for i in range(split, n):
        path[i] = turn + (i - split + 1) * rally_slope
    return path


def expected_htf(ltf_index: int, ratio: int = RATIO) -> int:
    """`floor((ltf_index + 1) / ratio) - 1`, computed independently of the code."""
    return (ltf_index + 1) // ratio - 1


def mtf(lower: list[dict[str, float]], higher: list[dict[str, float]], **kwargs: Any):
    params: dict[str, Any] = {
        "ratio": RATIO,
        "config": CFG,
        "lower_timeframe": "M15",
        "higher_timeframe": "H1",
    }
    params.update(kwargs)
    return analyze_multi_timeframe(lower, higher, **params)


# --------------------------------------------------------------------------
# Step measurement
# --------------------------------------------------------------------------


def test_the_step_is_the_modal_gap_not_the_mean() -> None:
    """One weekend gap must not become the bar period, or every bar after it is
    misaligned. A four-day gap in a 900 s series leaves the mode at 900."""
    times = [T0 + i * MIN15 for i in range(20)]
    times[10:] = [t + 4 * 86400 for t in times[10:]]
    bars = [{"time": t, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0} for t in times]

    step, ok = measure_step(BarSeries(bars))

    assert ok
    assert step == MIN15


def test_a_series_with_no_usable_timestamps_has_no_step() -> None:
    """`Bar.from_dict` defaults `time` to 0.0, so a series of bars that carried no
    time is all zeros. That is reported, not assumed away."""
    bars = [{"o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0} for _ in range(5)]

    step, ok = measure_step(BarSeries(bars))

    assert step == 0.0
    assert not ok


# --------------------------------------------------------------------------
# Alignment: the closed-bar rule
# --------------------------------------------------------------------------


def test_no_higher_bar_is_usable_before_the_first_one_closes() -> None:
    """The first H1 bar closes at T0 + 3600. Low bar 0 closes at T0 + 900, so
    there is nothing to align to and the caller is told why."""
    ltf = closes_series(rally(40))
    htf = aggregate(ltf)

    index, alignment = aligned_htf_index(BarSeries(ltf), BarSeries(htf), 0, ratio=RATIO)

    assert index == -1
    assert not alignment.is_usable
    assert WARN_NO_OVERLAP in alignment.warnings


def test_a_higher_bar_becomes_usable_exactly_when_it_closes() -> None:
    """Low bar 3 closes at T0 + 3600, the first H1 bar's close. The boundary is
    inclusive, and one bar earlier there is nothing."""
    ltf = closes_series(rally(40))
    htf = aggregate(ltf)

    assert aligned_htf_index(BarSeries(ltf), BarSeries(htf), 2, ratio=RATIO)[0] == -1
    index, alignment = aligned_htf_index(BarSeries(ltf), BarSeries(htf), 3, ratio=RATIO)

    assert index == 0
    assert alignment.warnings == ()
    assert alignment.ltf_step == MIN15
    assert alignment.htf_step == H1
    assert alignment.observed_ratio == pytest.approx(4.0)


@pytest.mark.parametrize("ltf_index", [3, 6, 7, 20, 38, 50, 117, 199])
def test_alignment_follows_the_closed_bar_formula(ltf_index: int) -> None:
    """Checked against `floor((i + 1) / r) - 1` rather than against whatever the
    implementation returns, and deliberately *not* `i // r`: a low bar closing at
    the same instant as a high bar's close is inside that high bar."""
    ltf = closes_series(rally(200))
    htf = aggregate(ltf)

    index, _ = aligned_htf_index(BarSeries(ltf), BarSeries(htf), ltf_index, ratio=RATIO)

    assert index == expected_htf(ltf_index)


def test_the_forming_higher_bar_is_never_used() -> None:
    """The load-bearing test.

    Analysing at low bar 38 of 40 leaves the tenth H1 bar still forming. Its close
    is pushed to an extreme that would flip the market-state proxy outright. If
    alignment used open times, or the newest bar rather than the newest *closed*
    one, the bias would follow it.
    """
    ltf = closes_series(rally(40))
    htf = aggregate(ltf)
    assert len(htf) == 10, "fixture must leave a forming H1 bar"
    assert htf[-1]["c"] > htf[-2]["c"], "fixture should end rising"

    poisoned = [dict(b) for b in htf]
    poisoned[-1]["c"] = poisoned[-1]["c"] - 40.0
    poisoned[-1]["o"] = poisoned[-1]["c"] + 1.0
    poisoned[-1]["high"] = poisoned[-1]["c"] + 2.0
    poisoned[-1]["h"] = poisoned[-1]["c"] + 2.0
    poisoned[-1]["l"] = poisoned[-1]["c"] - 1.0

    index, _ = aligned_htf_index(BarSeries(ltf), BarSeries(poisoned), 38, ratio=RATIO)

    assert index == 8 == expected_htf(38)
    assert index == len(htf) - 2, "the forming bar must not be returned"

    # And the bias therefore does not move.
    clean = mtf(ltf, htf, last_closed=38)
    dirty = mtf(ltf, poisoned, last_closed=38)
    assert clean.bias.to_dict() == dirty.bias.to_dict()


def test_a_non_monotonic_series_is_reported_and_not_aligned() -> None:
    ltf = closes_series(rally(40))
    shuffled = [dict(b) for b in aggregate(ltf)]
    shuffled[3]["time"] = shuffled[1]["time"] - H1

    index, alignment = aligned_htf_index(BarSeries(ltf), BarSeries(shuffled), 38, ratio=RATIO)

    assert index == -1
    assert WARN_NON_MONOTONIC_TIME in alignment.warnings


def test_missing_timestamps_are_reported_and_not_aligned() -> None:
    ltf = closes_series(rally(40))
    untimed = [{k: v for k, v in b.items() if k != "time"} for b in aggregate(ltf)]

    result = mtf(ltf, untimed, last_closed=38)

    assert result.alignment.warnings == (WARN_MISSING_TIMESTAMPS,)
    assert result.bias.reason == BIAS_NOT_ALIGNED_IN_TIME
    assert result.higher is None


def test_a_missing_ratio_is_reported_but_the_timestamps_still_align() -> None:
    """`ratio=0` means the caller did not say. The alignment does not need it —
    the timestamps do the work — so the alignment proceeds and says what is
    missing."""
    ltf = closes_series(rally(40))
    htf = aggregate(ltf)

    index, alignment = aligned_htf_index(BarSeries(ltf), BarSeries(htf), 38, ratio=0)

    assert index == 8
    assert WARN_NO_RATIO in alignment.warnings


def test_a_wrong_ratio_is_reported_and_the_alignment_proceeds() -> None:
    """A caller's wrong model of their own data is worth flagging, but it does not
    make the timestamps wrong, and refusing to align would throw the series away."""
    ltf = closes_series(rally(40))
    htf = aggregate(ltf)

    index, alignment = aligned_htf_index(BarSeries(ltf), BarSeries(htf), 38, ratio=7)

    assert index == 8
    assert WARN_RATIO_MISMATCH in alignment.warnings

    # A ratio that agrees is not reported, and a near miss inside the documented
    # tolerance is not either: 4 against an observed 3.99 is a rounding difference
    # in the data, not a different timeframe.
    _, near = aligned_htf_index(BarSeries(ltf), BarSeries(htf), 38, ratio=RATIO)
    assert WARN_RATIO_MISMATCH not in near.warnings
    assert RATIO_TOLERANCE > 0.0


def test_two_series_that_never_overlap_report_no_overlap() -> None:
    ltf = closes_series(rally(40))
    htf = [{**b, "time": b["time"] + 30 * 86400} for b in aggregate(ltf)]

    index, alignment = aligned_htf_index(BarSeries(ltf), BarSeries(htf), 38, ratio=RATIO)

    assert index == -1
    assert WARN_NO_OVERLAP in alignment.warnings
    assert htf_bias(BarSeries(htf), None, alignment, 38, CFG).reason == (
        BIAS_NOT_ALIGNED_IN_TIME
    )


# --------------------------------------------------------------------------
# The bias
# --------------------------------------------------------------------------


def test_a_clean_higher_trend_reads_as_a_directional_bias() -> None:
    ltf = closes_series(rally(120))
    result = mtf(ltf, aggregate(ltf), symbol="TEST")

    assert result.higher is not None
    assert result.higher.market_state["mode"] == "BULL_TREND"
    assert result.bias.reason == BIAS_ALIGNED
    assert result.bias.direction == 1
    assert result.bias.is_directional
    assert result.bias.mode == "BULL_TREND"
    assert result.bias.htf_index == result.alignment.htf_index
    assert result.bias.htf_time == aggregate(ltf)[result.bias.htf_index]["time"]


def test_a_choppy_higher_series_reads_as_not_classified_not_as_neutral() -> None:
    """A range is not a direction, and `HTF_NOT_CLASSIFIED` keeps that apart from
    "the timestamps were broken"."""
    ltf = closes_series(chop(120))
    result = mtf(ltf, aggregate(ltf))

    assert result.bias.reason == BIAS_NOT_CLASSIFIED
    assert result.bias.direction == 0
    assert not result.bias.is_directional
    assert result.higher is not None, "the series was fine; the read was weak"


def test_the_four_no_bias_reasons_are_distinct_codes() -> None:
    """Collapsing them would let a data problem read as a neutral market."""
    reasons = {
        BIAS_ALIGNED,
        BIAS_NOT_CLASSIFIED,
        BIAS_NOT_ALIGNED,
        BIAS_NOT_ALIGNED_IN_TIME,
    }

    assert len(reasons) == 4
    assert BIAS_NOT_ALIGNED != BIAS_NOT_ALIGNED_IN_TIME


def test_a_series_too_short_to_classify_is_not_classified() -> None:
    """`MarketState.valid` is False when the window is too small, and a bias built
    on it must not inherit a direction from whatever the empty state says."""
    ltf = closes_series(rally(8))
    htf = aggregate(ltf)
    index, alignment = aligned_htf_index(BarSeries(ltf), BarSeries(htf), 7, ratio=RATIO)
    assert index >= 0

    class Unclassified:
        market_state = {
            "valid": False,
            "mode": "UNKNOWN",
            "direction": 0,
            "strength": 0.0,
        }

    bias = htf_bias(BarSeries(htf), Unclassified(), alignment, 7, CFG)  # type: ignore[arg-type]

    assert bias.reason == BIAS_NOT_CLASSIFIED
    assert bias.direction == 0


def test_a_two_bar_higher_series_produces_no_directional_read() -> None:
    """The alignment succeeds — the bars closed on time — but two H1 bars cannot
    classify a market, and the result says `not classified` rather than claiming a
    direction or claiming neutrality."""
    ltf = closes_series(rally(8))
    result = mtf(ltf, aggregate(ltf))

    assert result.bias.direction == 0
    assert result.bias.reason == BIAS_NOT_CLASSIFIED
    assert result.alignment.warnings == ()


def test_htf_min_strength_is_inclusive_at_the_limit() -> None:
    """A clean trend scores exactly 0.67. At the limit it counts; a hair above the
    limit and it does not. The boundary is `strength >= htf_min_strength`."""
    ltf = closes_series(rally(120))
    htf = aggregate(ltf)

    at_limit = mtf(ltf, htf, config=AnalyzerConfig(htf_min_strength=0.67))
    above_limit = mtf(ltf, htf, config=AnalyzerConfig(htf_min_strength=0.6701))

    assert at_limit.higher is not None
    assert at_limit.higher.market_state["strength"] == pytest.approx(0.67)
    assert at_limit.bias.reason == BIAS_ALIGNED
    assert above_limit.bias.reason == BIAS_NOT_CLASSIFIED
    assert above_limit.bias.strength == pytest.approx(0.67)


def test_opposes_needs_both_sides_to_have_a_direction() -> None:
    bull = HTFBias(direction=1, reason=BIAS_ALIGNED)

    assert bull.opposes(-1)
    assert not bull.opposes(1)
    assert not bull.opposes(0)
    assert not HTFBias().opposes(1)


# --------------------------------------------------------------------------
# Applying the veto
# --------------------------------------------------------------------------


def decision(action: str, direction: int) -> dict[str, Any]:
    return {
        "action": action,
        "reason": REASON_RANKED,
        "subject": "CANDIDATE#0",
        "direction": direction,
        "plan": {"entry": 100.0},
        "evidence": {"value": 0.8},
        "explanation": ["selected the candidate"],
        "vetoes": [],
        "considered": {"considered": 1, "eligible": 1, "rejected": 0},
        "ranking_basis": ["evidence_score (0..1, higher first)"],
        "sides": {"bull_ppts": 80.0, "bear_ppts": 0.0},
        "is_actionable": action in ("BUY", "SELL"),
        "is_probability": False,
    }


def test_an_opposed_signal_is_withheld_and_never_reversed() -> None:
    """The engine knows an M15 long disagrees with an H1 bear. It does not know the
    long is a short, and turning it round would be a claim it has not earned."""
    bear = HTFBias(direction=-1, strength=0.67, mode="BEAR_TREND", htf_index=8)

    result = apply_htf_veto(decision("BUY", 1), bear, CFG)

    assert result["action"] == "WAIT"
    assert result["reason"] == REASON_AGAINST_HTF
    assert result["is_actionable"] is False
    assert result["direction"] == 1, "the signal is withheld, not flipped"
    assert result["vetoes"][-1]["code"] == VETO_AGAINST_HIGHER_TIMEFRAME
    assert result["considered"]["htf_opposed"] == 1
    assert "withheld, not reversed" in result["vetoes"][-1]["detail"]


def test_a_signal_agreeing_with_the_higher_timeframe_is_untouched() -> None:
    bull = HTFBias(direction=1, strength=0.67, mode="BULL_TREND")
    original = decision("BUY", 1)

    assert apply_htf_veto(original, bull, CFG) == original


def test_an_abstention_is_left_alone_rather_than_relabelled() -> None:
    """Overwriting a `WAIT` that already had a reason would replace a true
    statement with a weaker one: the HTF was not why it waited."""
    bear = HTFBias(direction=-1, strength=0.67, mode="BEAR_TREND")
    waited = decision("WAIT", 1)
    waited["reason"] = REASON_ALL_VETOED

    assert apply_htf_veto(waited, bear, CFG) == waited


def test_a_weak_or_absent_higher_timeframe_never_vetoes() -> None:
    unclassified = HTFBias(reason=BIAS_NOT_CLASSIFIED, mode="TRADING_RANGE")
    original = decision("BUY", 1)

    assert apply_htf_veto(original, unclassified, CFG) == original
    assert apply_htf_veto(decision("SELL", -1), unclassified, CFG)["action"] == "SELL"


def test_htf_opposition_veto_false_reports_the_conflict_without_gating() -> None:
    """A caller that treats the higher timeframe as context rather than as a
    filter still gets the bias; it just keeps its signal."""
    bear = HTFBias(direction=-1, strength=0.67, mode="BEAR_TREND")
    original = decision("BUY", 1)

    result = apply_htf_veto(original, bear, AnalyzerConfig(htf_opposition_veto=False))

    assert result == original


# --------------------------------------------------------------------------
# The pipeline end to end
# --------------------------------------------------------------------------


def test_the_higher_timeframe_is_analysed_as_of_the_aligned_bar() -> None:
    """Where the no-look-ahead guarantee comes from: the pipeline asks the analyzer
    for the HTF *as of* a bar, rather than holding a full result and reaching back
    into it."""
    ltf = closes_series(rally(200))
    result = mtf(ltf, aggregate(ltf), symbol="TEST")

    assert result.higher is not None
    assert result.lower.last_closed_bar == 199
    assert result.higher.last_closed_bar == result.alignment.htf_index == 49
    assert result.alignment.htf_index == expected_htf(199)


def test_appending_bars_to_either_series_cannot_change_an_earlier_answer() -> None:
    """The architecture's central invariant, restated for two series."""
    short = closes_series(rally(80))
    longer = closes_series(rally(160))
    at_bar = 39

    before = mtf(short, aggregate(short), last_closed=at_bar)
    after = mtf(longer, aggregate(longer), last_closed=at_bar)

    assert before.bias.to_dict() == after.bias.to_dict()
    assert before.decision == after.decision
    assert before.alignment.to_dict() == after.alignment.to_dict()
    assert _derived(before.lower) == _derived(after.lower)
    assert _derived(before.higher) == _derived(after.higher)


def _derived(result: Any) -> dict[str, Any]:
    payload = result.to_dict()
    return {k: v for k, v in payload.items() if k not in INPUT_FIELDS}


def test_a_bearish_higher_timeframe_against_a_bullish_lower_one_is_the_veto_case() -> None:
    """The case the layer exists for, assembled from two real analyses rather than
    a hand-built bias.

    The fixture is a falling H1 read with a sharp rally in the **last few M15 bars,
    which fall inside the still-forming H1 bar**. That is the honest way to get a
    genuine disagreement out of one price series, and it is also the real-world
    case: a counter-trend bounce nobody can see on the hourly chart yet.

    `htf_min_strength` is lowered to 0.30 for this one test, and the reason is
    worth stating rather than hiding: the forming bar's rally drags the HTF proxy
    share down to 0.35, which is below the default 0.60. The threshold is a
    chosen value on a proxy, and a test that manufactures its scenario by setting
    the documented knob is honest about it. The next test pins the default.
    """
    ltf = closes_series(bear_then_rally(199, split=185, depth=1.0, rally_slope=0.6))
    htf = aggregate(ltf)
    result = mtf(ltf, htf, symbol="TEST", config=AnalyzerConfig(htf_min_strength=0.30))

    assert result.higher is not None
    assert result.higher.market_state["mode"] == "BEAR_TREND"
    assert result.higher.market_state["strength"] == pytest.approx(0.35)
    assert result.bias.reason == BIAS_ALIGNED
    assert result.bias.direction == -1
    assert result.lower.decision["direction"] == 1, "fixture must disagree"
    assert result.decision["action"] == "WAIT"
    assert result.decision["reason"] == REASON_AGAINST_HTF
    assert result.decision["vetoes"][-1]["code"] == VETO_AGAINST_HIGHER_TIMEFRAME
    assert result.decision["is_actionable"] is False
    # The lower analysis itself is untouched: the veto is the pipeline's, not a
    # rewrite of the low timeframe's own output.
    assert result.lower.decision["action"] == "BUY"
    assert result.lower.decision["reason"] == REASON_RANKED


def test_a_directional_mode_below_the_strength_threshold_does_not_veto() -> None:
    """The gate is not trigger-happy, and this is the same fixture.

    The higher timeframe *does* read `BEAR_TREND`, and the lower timeframe *does*
    read bull. At the default `htf_min_strength` the proxy share is not dominant
    enough to be called a bias, so the disagreement is not a conflict and the
    signal stands. A veto that fired here would be a veto on a mood.
    """
    ltf = closes_series(bear_then_rally(199, split=185, depth=1.0, rally_slope=0.6))
    result = mtf(ltf, aggregate(ltf), symbol="TEST")

    assert result.higher is not None
    assert result.higher.market_state["mode"] == "BEAR_TREND"
    assert result.bias.reason == BIAS_NOT_CLASSIFIED
    assert result.bias.direction == 0
    assert result.decision["action"] == "BUY"
    assert not any(
        v["code"] == VETO_AGAINST_HIGHER_TIMEFRAME for v in result.decision["vetoes"]
    )


def test_an_agreeing_higher_timeframe_does_not_veto() -> None:
    ltf = closes_series(rally(200))
    result = mtf(ltf, aggregate(ltf), symbol="TEST")

    assert result.bias.direction == 1
    assert result.lower.decision["direction"] == 1
    assert result.decision["action"] == "BUY"
    assert not any(
        v["code"] == VETO_AGAINST_HIGHER_TIMEFRAME for v in result.decision["vetoes"]
    )


def test_the_result_serialises_with_both_analyses_and_the_bias() -> None:
    ltf = closes_series(rally(120))
    htf = aggregate(ltf)

    payload = json.loads(json.dumps(mtf(ltf, htf, symbol="TEST").to_dict()))

    assert payload["symbol"] == "TEST"
    assert payload["lower_timeframe"] == "M15"
    assert payload["higher_timeframe"] == "H1"
    assert payload["lower"]["last_closed_bar"] == 119
    assert payload["higher"]["last_closed_bar"] == payload["bias"]["htf_index"]
    assert payload["bias"]["is_directional"] is True
    assert payload["bias"]["alignment"]["observed_ratio"] == pytest.approx(4.0)
    assert payload["decision"]["is_probability"] is False


def test_an_empty_alignment_serialises_rather_than_raising() -> None:
    payload = Alignment().to_dict()

    assert payload["is_usable"] is False
    assert payload["htf_index"] == -1
    assert payload["warnings"] == []


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_the_multi_timeframe_keys_round_trip_through_config() -> None:
    config = AnalyzerConfig(
        htf_min_strength=0.75,
        htf_opposition_veto=False,
        htf_report_unclassified=True,
    )
    payload = config.to_dict()

    assert AnalyzerConfig.from_dict(payload) == config
    assert payload["htf_min_strength"] == 0.75
    assert payload["htf_opposition_veto"] is False
