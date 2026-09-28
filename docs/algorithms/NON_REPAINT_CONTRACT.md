# Non-Repaint Contract

## 1. What this document is

The engine has always claimed to be closed-bars only. Until now that claim was
scattered across `ARCHITECTURE.md` §6, four algorithm specifications, and a
dozen tests with names like `test_..._is_free_of_lookahead`. A claim spread
across thirteen files is a claim nobody can check.

This document is the **formal statement** of the contract: eighteen numbered
guarantees, each with the reason it exists, how it is enforced, and the name of
the test that enforces it.

The numbering is the point. A guarantee nobody can cite is a guarantee nobody can
check, and `RPC-17` below makes the document itself accountable: it asserts that
every guarantee named here resolves to a test that **exists**. If a test is
renamed or deleted, this contract fails rather than quietly becoming fiction.

## 2. The vocabulary

| Term | Meaning |
|---|---|
| **closed bar** | a bar whose period has ended. Only these are ever read. |
| **forming bar** | the bar currently in progress. Never read. The engine has no flag for one, and does not need one — see §4. |
| `last_closed` | the newest bar index the engine may read. Oldest-first throughout, so index `0` is the oldest. |
| **confirmation** | the bar at which a right-side-confirmed structure becomes knowable. |
| **freeze** | truncating a live series to its last closed bar before handing it to the engine. |

## 3. The one invariant

Everything below is a consequence of this, stated in `ARCHITECTURE.md` §6:

> The analysis for a given bar index is **identical** whether or not later bars
> exist.

If that holds, a live consumer recomputing on every tick gets the same answer for
bar `k` every time, and a historical replay gets the same answer as the live run
did. Every other guarantee is either that invariant applied somewhere specific, or
a statement about what happens when it cannot be honoured.

## 4. There is no forming-bar flag, and that is the design

`Bar` has no `is_forming` field and `BarSeries` is documented as a sequence of
**closed** bars. The engine cannot be told a bar is forming, by design: a flag
would have to be threaded through every detector, and a detector that forgot to
honour it would be a look-ahead bug that no test could see.

So the **adapter's job** is to drop it:

```text
live bars  ->  [ forming ][closed ...]  ->  freeze  ->  BarSeries(closed only)
```

Phase 21 owns the MT5 adapter, and this is its obligation. `RPC-14` and `RPC-15`
below are the tests that say what happens when it does its job, and what happens
when it does not.

## 5. The guarantees

### RPC-1 — Analysis at a bar index is independent of later bars

**Statement.** For a given `last_closed = k`, `analyze()` returns identical
derived output whether or not bars after `k` exist.
**Why.** It is the invariant of §3, and every other guarantee is a special case.
**Enforced by.** `test_engine_pipeline.py::test_analysis_of_a_bar_is_identical_whether_or_not_future_bars_exist`
**Note.** `bars_processed` is deliberately excluded from that comparison: it
counts the bars *supplied*, so it is a property of the caller's input rather than
of the analysis.

### RPC-2 — No future price reaches the output

**Statement.** No field of a result contains a price that occurs only after
`last_closed`.
**Why.** The strongest available check. Indices can be faked; prices cannot. This
test compares the actual numbers, so it also catches a future price smuggled into
a field carrying no index of its own.
**Enforced by.** `test_engine_pipeline.py::test_no_field_carries_a_price_from_beyond_last_closed`

### RPC-3 — Per-bar features stop at the analysis point

**Statement.** `bar_features` covers exactly bars `0..last_closed`.
**Why.** A real leak. `analyze_series` has no `last_closed` of its own and runs to
the end of whatever series it is given, so the pipeline used to compute features
for bars *after* the analysis point and return future prices inside a
closed-bar-only result. It was found and fixed; the test is the regression.
**Enforced by.** `test_engine_pipeline.py::test_bar_features_stop_at_last_closed`

### RPC-4 — Out-of-range indices are reported, not rejected

**Statement.** `last_closed` past the end is **clamped**; a negative value
produces a reported reason and no analysis.
**Why.** Asking for the whole series is a useful reading, not a mistake. Raising
would make the engine's entry point hostile to the one thing a caller does by
accident.
**Enforced by.** `test_engine_pipeline.py::test_last_closed_past_the_data_is_clamped_not_rejected`,
`test_engine_pipeline.py::test_negative_last_closed_reports_itself`

### RPC-5 — Right-side confirmation is recorded, not hidden

**Statement.** A fractal swing is emitted from the bar that **confirms** it, and
carries `confirmed_bar_index = bar + k`.
**Why.** A structure that needs `k` right-hand bars is unknowable earlier. Emitting
it early is look-ahead; emitting it late without saying so is a lag the caller
cannot see. Recording the confirmation index is what lets a caller reason about
the delay instead of discovering it.
**Enforced by.** `test_phase3_swings_legs.py::test_swing_detection_and_no_repaint`
and the `SwingPoint` model itself.

### RPC-6 — No reported structure comes from after the analysis point

**Statement.** Every swing, leg, pivot and pattern in a result has an index at or
before `last_closed`.
**Why.** The general form of RPC-2 over the structural layers, and the one a
consumer is most likely to trip over: a swing printed on a bar you have not seen.
**Enforced by.** `test_engine_pipeline.py::test_no_reported_structure_comes_from_after_last_closed`,
`test_phase3_pivots.py::test_pivots_have_no_lookahead`,
`test_phase3_pivots.py::test_touches_ignore_bars_after_last_closed`

### RPC-7 — Every registered detector is closed-bar clean

**Statement.** For each of the eleven setup detectors, its findings at index `k`
are identical whether the series continues past `k` or is truncated at `k`.
**Why.** RPC-1 is asserted at the *pipeline* level, which catches a mis-wired
stage but says nothing about a detector that is individually wrong. Driving this
off the registry means a detector added in Phase 20-something is covered by
construction rather than by remembering.
**Enforced by.** `test_phase17_non_repaint.py::test_every_registered_detector_is_closed_bar_clean`
**Note.** Paired with `test_the_detector_closure_fixture_is_not_vacuous`, because
a closure test over a fixture where nothing fires passes forever.

### RPC-8 — The registry honours the contract end to end

**Statement.** `SetupRegistry.run()` over the same context yields the same
findings with future bars present or absent.
**Why.** The registry is the pipeline's only detection path since Phase 16, so a
leak here is a leak everywhere.
**Enforced by.** `test_phase12_setup_registry.py::test_the_registry_honours_the_closed_bar_contract`,
`test_phase12_setup_registry.py::test_the_closed_bar_test_is_not_vacuous`
**Note.** The vacuity guard exists because the first version of that test *was*
vacuous: it compared two near-empty finding lists and still passed with
look-ahead deliberately injected. It is recorded here because a closure test that
cannot fail is worse than no test.

### RPC-9 — Measured moves and their confidence are closed-bar clean

**Statement.** `detect_measured_moves()` and a projection's `confidence` are
unchanged when bars after the analysis point are removed.
**Why.** The measured-move layer reaches furthest into the past of any layer, and
its `confidence` is an aggregate that would happily hide a leak behind a stable
number.
**Enforced by.** `test_phase10_measured_move.py::test_detect_measured_moves_is_free_of_lookahead`,
`test_phase10_measured_move_evidence.py::test_confidence_is_deterministic_and_free_of_lookahead`

### RPC-10 — The fading lifecycle does not read ahead

**Statement.** `create_setups()` / `update_setups()` at index `k` are unchanged
when bars after `k` are removed.
**Why.** The lifecycle advances *backwards* as well as forwards, so it is the one
setup layer whose output legitimately changes as price moves. That makes it the
layer where a leak is easiest to argue away as "the lifecycle moved".
**Enforced by.** `test_phase11_fading_measured_move.py::test_the_lifecycle_does_not_read_bars_after_last_closed`

### RPC-11 — Trade-plan levels come from the analysed window only

**Statement.** A `TradePlan` built at `bar_index = k` is identical when bars after
`k` exist, and its swing stop requires the swing's `confirmed_bar_index` to be at
or before `k`.
**Why.** The second half is the sharp one. A fractal swing is not knowable until
`k` bars after it happens, and letting it set a stop on a plan dated before its own
confirmation is look-ahead wearing a different hat.
**Enforced by.** `test_phase14_trade_plan.py::test_a_plan_cannot_see_a_bar_after_its_own`,
`test_phase14_trade_plan.py::test_a_swing_confirmed_after_the_plan_is_not_used`

### RPC-12 — The decision for a bar is independent of later bars

**Statement.** `decide()` at index `k` is unchanged when bars after `k` are
appended.
**Why.** The lateness gate (`max_late_atr`) compares the plan's entry against the
close at the analysis point, so it is the gate most likely to break this one by
reading the wrong bar.
**Enforced by.** `test_phase15_decision.py::test_the_decision_cannot_see_a_bar_after_its_own`

### RPC-13 — Multi-timeframe closure holds on **both** series

**Statement.** The bias and the decision for a low-timeframe index are unchanged
when bars are appended to the low series **or** the high series.
**Why.** Two series means two opportunities to leak, and the high one is the more
tempting because it is "just context".
**Enforced by.** `test_phase16_multi_timeframe.py::test_appending_bars_to_either_series_cannot_change_an_earlier_answer`

### RPC-14 — A higher-timeframe bar is used only once it has closed

**Statement.** A high bar is usable at low bar `i` only when
`htf.time + htf_step <= ltf.time[i] + ltf_step`, i.e. only when
`k = floor((i + 1) / ratio) - 1`. The forming high bar is never returned.
**Why.** The most likely way to build a multi-timeframe look-ahead bug, and the
one a naive `htf.time < ltf.time` test makes immediately. Note that `k` is
deliberately **not** `i // ratio`: a low bar closing at the same instant as a high
bar's close is *inside* that high bar.
**Enforced by.** `test_phase16_multi_timeframe.py::test_the_forming_higher_bar_is_never_used`
**Note.** The test makes the forming high bar extreme and asserts the bias does not
move, so it fails on the naive implementation rather than passing on both.

### RPC-15 — A frozen series gives the historical answer

**Statement.** Truncating a live series to its last closed bar and analysing that
gives exactly the answer the historical series gives at the same index — and
that stays true while the forming bar *mutates*, so a live consumer recomputing on
every tick sees the same closed-bar answer every time.
**Why.** The historical-freeze property, and the reason a backtest and a live run
can be compared at all. Without it, "the engine is closed-bars only" is a claim
about a code path nobody uses.
**Enforced by.** `test_phase17_non_repaint.py::test_a_frozen_series_gives_the_historical_answer`,
`test_phase17_non_repaint.py::test_a_forming_bar_mutating_does_not_move_the_closed_answer`
**Note.** The second half matters more than the first. A repaint is not "the wrong
answer once"; it is "the answer changed after you had already seen it".

### RPC-16 — The truncation is load-bearing, not ceremonial

**Statement.** Analysing a series that *includes* the forming bar as if it were
closed produces a **different** answer, and the difference is visible.
**Why.** The converse of RPC-15. If passing a forming bar changed nothing, the
contract would be satisfied by an engine that simply ignored its last bar, and
"freeze your series" would be advice with no cost attached.
**Enforced by.** `test_phase17_non_repaint.py::test_passing_a_forming_bar_changes_the_answer`

### RPC-17 — Unmeasurable input is reported, never guessed

**Statement.** A series whose timestamps are missing or non-monotonic stops the
multi-timeframe alignment and says so, with a distinct reason code. Degenerate
input — no bars, no volatility — marks **every** layer as not run.
**Why.** The failure this whole document exists to prevent, one level down: a
silently-guessed alignment produces a bias that reads as a neutral market, and a
silently-empty result reads as "no structure" about a market that was never
examined.
**Enforced by.** `test_phase16_multi_timeframe.py::test_missing_timestamps_are_reported_and_not_aligned`,
`test_phase16_multi_timeframe.py::test_a_non_monotonic_series_is_reported_and_not_aligned`,
`test_engine_pipeline.py::test_no_bars_reports_no_bars`,
`test_engine_pipeline.py::test_a_flat_series_reports_no_volatility_rather_than_no_structure`

### RPC-18 — This contract is checked against the suite

**Statement.** Every guarantee above names a test, every named test exists, and
this document is a **required** CI document, so it cannot go missing.
**Why.** A contract that can drift from the code is worse than no contract, because
it invites reliance. The check is mechanical: the document is parsed, the `RPC-n`
identifiers are collected, the referenced test names are resolved against the
suite's own source, and a missing or renamed test fails here.
**Enforced by.** `test_phase17_non_repaint.py::test_every_guarantee_names_a_test_that_exists`,
`test_phase17_non_repaint.py::test_the_contract_document_is_required_by_ci`

## 6. What this contract does not promise

- **It does not promise the analysis is *good*.** Non-repainting is a property of
  the *process*, not of the *readings*. Every gate in the decision layer is a
  chosen threshold on a transparent number, and nothing in this project has been
  validated against outcomes (`CONCEPT_TAXONOMY.md` §5).
- **It does not promise the same answer across brokers or data vendors.** Bar
  boundaries, session times and `time` conventions differ, and a differently
  aggregated bar is a different input. Parity is Phase 20's subject.
- **It does not promise a signal was stable in hindsight.** A setup that was
  confirmed at bar 40 and invalidated at bar 45 was *correctly* reported twice.
  Non-repainting is about the answer for a given bar, not about a setup never
  being withdrawn later.
- **It says nothing about gaps or a missing series.** Ticks are not modelled; the
  unit is the bar.

## 7. How a new detector or layer inherits the contract

A detector added through the registry is covered by RPC-7 by construction — the
test iterates `build_default_registry()`, so a new registration is covered the
moment it is written. A detector called *directly*, bypassing the registry, is
covered by nothing, which is why `CONTRIBUTING.md` and `ARCHITECTURE.md` §9 both
require the registry route and why `Analyzer` now takes its detectors from it.

A new *layer* is not covered by construction. It inherits the contract by
asserting RPC-1 for itself: analyse at bar `k` with and without future bars, and
compare. That is the whole test, and it is short enough that there is no excuse
for not writing it.
