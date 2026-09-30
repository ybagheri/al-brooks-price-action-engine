# Validation

## 1. What this document is, and what it is not

The roadmap calls this phase "Validation Dataset", and the phrase is a little
dangerous, so the first job of this document is to say plainly what exists and
what does not.

**What exists.** Five hand-authored charts, one per named concept, each with an
expectation derived by hand from the bars and from the documented gates, each
with a stated reason for every value, and each with a list of edits to the bars
whose effect the derivation predicts. `tests/fixtures/golden/`,
`tests/unit/test_phase19_golden.py`.

**What does not exist.** Any statement that these setups work, have an edge, or
are likely to continue. There is no out-of-sample test, no parameter fit, no
walk-forward, no confidence interval, and no sample large enough to support one.
Five charts, hand-built by the author of the code, establish **what the engine
names**. They establish nothing about the market.

So: this is a **semantic regression suite**, not a validation study. A naming
convention that is wrong about the market is still consistent, and these fixtures
would still pass. `test_the_dataset_claims_no_edge_and_no_forecast` checks the
fixtures for the words this project will not use, and the honest answer to "how
do we know these setups are any good?" is *we do not, and here is what we do
know instead*.

## 2. Why a golden file is not a snapshot

The obvious implementation of a golden suite is to store the engine's output and
compare it. This project deliberately does not, and §2 of
`tests/fixtures/golden/README.md` gives the reasons. The short version:

- A snapshot **cannot tell a fix from a regression.** It fails on both and passes
  on neither. Its only signal is "something changed", which a test that only
  reports *that* has not earned its place.
- The way a snapshot gets updated is by running the code and pasting the answer,
  which makes the human check optional. A suite whose failure mode is "paste and
  continue" is a change detector with extra steps.
- A full `AnalysisResult.to_dict()` snapshot pins explanation prose, warning
  ordering and management strings. None of those are behavioural, and all of them
  change for reasons nobody should have to adjudicate.

What replaces it:

| Instead of | This suite has |
|---|---|
| a pinned output blob | pinned values, each with a `basis` saying how it follows from the bars |
| nothing | `falsifiers`: bar edits whose effect the derivation predicts |
| nothing | `must_not`: claims that must hold, each implemented and explained |
| nothing | an independent re-derivation of the one value that is pinned rather than derived |

The falsifiers are the part a snapshot structurally cannot have. They are
assertions about *causality* — "lower this bar's high and the state must become
`PROVISIONAL`" — rather than about a value. Twelve of them, across five
fixtures.

## 3. The provenance guard

The failure mode of a hand-derived suite is that it quietly stops being
hand-derived, one convenient paste at a time. Three tests make that visible:

- **`test_every_expectation_states_a_reason_you_could_check`** — every pinned leaf
  needs a sibling `basis` entry of at least twenty characters, and the reason may
  not be the value restated. A fixture with unannotated expectations can only
  have come from reading the code's output.
- **`test_a_fixture_does_not_store_the_engine_s_whole_output`** — each block of
  expectations is checked against an allow-list of behavioural fields, so
  over-specification cannot creep in one field at a time.
- **`test_each_block_of_expectations_contains_at_least_one_derivation`** — every
  block must anchor at least one claim to a number. Prose is not a derivation.

And one guard on the guards: `test_every_must_not_claim_is_implemented_and_holds`
fails on a `must_not` name no test evaluates, so a fixture cannot introduce a
claim that is never checked.

## 4. ATR, and the honesty about the one pinned number

Every expectation downstream of ATR is written as a formula, so the structural
claims are ATR-independent:

```text
pullback   stop = extreme_price - 0.25 * atr        target = entry + 2.0 * atr
breakout   stop = reference_price - 0.25 * atr       target = entry + 2.0 * atr
reversal   stop = entry - 1.0 * atr                  target = entry + 2.0 * atr
measured   target = B0 + (A1 - A0)
```

The last line needs no ATR at all, which is why `golden_fm_001` asserts the
measured-move target three times: the value, the identity `target = B0 + mm_range`
with `mm_range = A1 - A0` recomputed from the fixture's own bars, and a falsifier
that widens the leg and requires the target to move by exactly that much.

ATR itself is Wilder smoothing over a 14-bar window — checkable by hand, tedious
to do fifty times — so the fixtures pin it. To stop that being circular,
`test_atr_is_recomputed_from_the_bars` implements Wilder's definition
independently in the test file, re-derives ATR for all five fixtures, and asserts
it agrees with both the pinned value and the engine. Two readings of the same
definition that agree is a real check; one reading agreeing with itself is not.

## 5. What the dataset found

Three things, all recorded in the fixtures.

### 5.1 The fade lifecycle was unreachable through the pipeline — now closed for a live consumer

`golden_fm_001` is a bull measured move projecting 111.1, which the market reaches
at bar 28 and rejects at bar 29. `track_fading_measured_moves` reports
`DEVELOPING`, `touched`, three exhaustion conditions — which is correct.

`Analyzer.analyze()` on the same bar reports `PROJECTED`, `age 0`,
`exhaustion_breadth 0`, reason `"projection formed"`.

The cause was in `setups/registry.py`: the `FADING_MEASURED_MOVE` detector
calls `create_setups`, which only seeds. The function that advances the state
machine, `track_fading_measured_moves`, was never called by the engine. So a live
consumer saw `PROJECTED` forever, and the five-state lifecycle documented in
`FADING_MEASURED_MOVE.md` §2 was reachable only by calling the module directly.

This was recorded rather than fixed, and the reason mattered. The registry is a
*stateless* detector contract: given a context, return findings. A stateful
lifecycle does not fit it, and making it fit is an architecture decision — one
that belongs with the MT5 adapter's obligation to maintain state across calls
(Phase 21), not with a test fixture.

A golden fixture that quietly fixed this would be deciding an architectural
question in a JSON file.

**Phase 21 closed it, and the way it was closed is the interesting part.**
`albrooks.adapters.mt5.session.AnalysisSession` is the stateful caller this
deferred to, and it calls `track_fading_measured_moves`. The obvious
implementation — keep the setups in `self` and advance one bar per call — would
have **broken `RPC-1`**: a session that has seen bars 21..40 and then answers for
bar 20 is holding state derived from bars the caller declared unavailable, and its
answer for bar 20 would depend on *when* it was asked. So the session **re-derives**
on every call, which `track_fading_measured_moves` being a deterministic function of
`(bars, last_closed)` makes possible.

The pipeline still reports `PROJECTED`, and that is now a deliberate reading rather
than a defect: the registry is stateless and this is its contract, so the session
adds a caller rather than editing it. `SessionResult.fade_source` says which reading
is which.

The honest boundary is also pinned. Truncate the fixture before the target is
reached and the lifecycle never touches, the pipeline's `PROJECTED` becomes
correct, and the finding is about having reached a target rather than about the
architecture failing for every fade.

### 5.2 The pullback window is a configuration choice, not a reading of price

`detect_h1_h2` calls *the first bar with a higher high* the first leg. In a clean
uptrend every bar makes a higher high, so leg 1 is simply the next up-bar and the
"pullback" is the last `max_pb_bars` bars rather than anything the chart did.

`golden_h2_001` therefore pins `max_pb_bars: 12` and supplies a **flat top** —
bars 40 to 48 all share a high of 114.0 — so a higher high is a meaningful thing
to measure. That is a real property of the detector, and the fixture records it
rather than hiding it behind a convenient chart. The falsifier list includes the
demonstration: delete the resumption bar and the window start moves from 40 to 39,
which pulls an uptrend bar in and changes the first leg entirely.

### 5.3 Two of my own derivations were wrong

The point of recording these is that they were not engine defects.

- `golden_mtr_001` originally named bar 20 as the retest. The retest loop scans
  forward from the cross and takes the first qualifying bar, which is bar 18.
  Both bars qualify; bar 18 is where the scan stops. The fixture now says so, and
  notes that in a decisive rally this leg is easy to pass.
- `golden_double_001`'s "lift the trough" falsifier was expected to remove the
  pattern. It does not: the detector scans every pair in the five-bar window and
  falls back to an earlier pair, so lifting the trough **moves** the double rather
  than deleting it. The test now asserts the move, which is the more useful claim
  — "is there a double top?" has no stable answer in a range, because there is
  always some pair of similar highs; the answerable question is *which* pair, and
  the detector returns the most recent one that clears the separation rule.

A third falsifier was abandoned rather than written: pushing the measured-move
pullback depth below the 0.15 floor to reach the `CHANNEL` family does not work
by editing bars, because raising the pullback low also raises `A1` or relocates
the swing, so the leg grows with it. The test says so and why.

## 6. What each fixture does and does not claim

| Fixture | Claims | Does not claim |
|---|---|---|
| `golden_h2_001` | a confirmed H2 is named, with the right bars, and the plan clears `min_rr` and `max_late_atr` | that an H2 works. `H1_H2_L1_L2.md` says the same. |
| `golden_breakout_001` | the N-bar reference is used when there is no swing, and an unresolved breakout stays `PENDING` | that a breakout continues. `BREAKOUTS.md` §6 says the opposite is not claimed either. |
| `golden_mtr_001` | three of four legs, the fourth named, and the score is `25 * legs` | that four legs would be a better trade, or that 75 is 75% of anything |
| `golden_double_001` | the pattern is found, and no double can ever be ranked | that a double top is a sell signal. `DOUBLE_PATTERNS.md` §5 says it is not. |
| `golden_fm_001` | a bull projection of 111.1 is derived from three swings, and the pipeline cannot see it develop | that a confirmed fade works, or that a fade at a reached target is enterable |

`is_probability` is `False` on every decision in the dataset and
`is_recommendation` is `False` on every plan, and both are asserted.

## 7. The closed-bar contract, applied to the dataset

The goldens inherit `NON_REPAINT_CONTRACT.md`, and two tests say so:

- `test_appending_bars_changes_nothing_about_the_golden_readings` — each fixture
  is analysed as authored and again with five bars appended and `last_closed`
  unmoved. The derived output must be identical. If a golden's answer could see
  the future, none of the expectations above would mean anything.
- `test_the_newest_bar_does_change_the_output_so_the_previous_test_is_not_vacuous`
  — the same fixture re-analysed at the appended bar must differ. A closed-bar
  test where nothing ever moves proves nothing.

## 8. The structural claim worth more than any fixture

`test_a_double_is_never_the_ranked_answer` runs over **all five** fixtures rather
than one. "This double was not ranked" is a weak statement; "no double can be"
is the actual design, because the double families have no evidence adapter, so
every double is blocked with `NO_OWN_EVIDENCE`. Asserting it across the dataset
means a future detector that gave doubles an adapter would fail here rather than
quietly start producing sell signals.

## 9. What would turn this into validation

Not a bigger fixture set. In order:

1. **Real data, not hand-built bars.** Five charts the author drew cannot be
   surprised. The failure modes worth catching are the ones in real series:
   gaps, session boundaries, instrument-specific ranges, and bars where a level
   is grazed exactly.

   **The exporter exists: `scripts/export_bars.py`.** It reads real bars through
   the adapter's own freeze — one implementation of the closed-bar rule, not a
   second one in a script — and writes a JSON file carrying its own provenance:
   the terminal build, the broker server and whether the feed was **demo or live**,
   the symbol's digit precision, the clock the closed-bar test used, and the exact
   span. It records **no account number and no credentials**, because provenance has
   to identify the *feed* and a login identifies a person.

   Two things it refuses rather than handles. It will not substitute a fixture when
   no terminal is reachable, because a dataset that silently contained synthetic
   bars would defeat its own purpose. And it will not write a file whose bars are
   not monotonic or not closed: `inspect_series` in
   `src/albrooks/adapters/mt5/dataset.py` checks that every bar time is strictly
   ascending and that every bar satisfies `bar.time + period <= now` on the
   **server** clock, and the script checks the series **again after reading it back
   from disk**, because a file that was valid in memory and invalid on disk has been
   through a serialisation bug. The verdict is written into the file, so a dataset
   carries its own proof rather than asking to be trusted.

   `datasets/` is gitignored. The data is the broker's to distribute, and the
   provenance travels *inside* the file so it survives being uncommitted — an
   unrecorded sample is exactly what item 2 below complains about.

   **What this does not do.** It produces no labels and no result. Items 2 and 3 are
   human judgements — what a setup *is*, and which bars were available when — and a
   script that generated them would be generating its own evidence.
2. **A labelled sample with a stated provenance.** Where did the labels come from,
   who drew them, and what did they see? `tests/fixtures/golden/` has no answer
   to that and does not pretend to.
3. **Out of sample, always.** Fit on some of it, report on the rest. Reporting
   only the fitted half is the most common way a backtest becomes a curve.
4. **A stated null.** A sample share of target-first events means nothing without
   what the same count would be on random entries into the same levels. **Stated,
   specified and implemented in §9.4 below.** It is the largest of the four, and
   it is the one that must be written *before* the answer is known.
5. **Then, and only then,** a label. Until §9.1 through §9.3 exist, every number in
   this project stays `is_probability: false`, and the backtest module keeps
   refusing to produce a win rate. §9.4 existing does not change that, and §9.4
   cannot change it by itself: a stated null is a *precondition* for a verdict, not
   a verdict.

### 9.4 The null, stated in advance

**The hypothesis.** The engine's share of target-first events is no better than
what the same sample produces when the engine's directional claim is removed and
nothing else is changed.

**What "nothing else is changed" means, precisely.** For every event the engine
produced, the counterfactual keeps

- the same **fill bar** and the same **fill price**,
- the same **risk** and the same **reward** — so the R:R ratio and both ATR-scaled
  distances are preserved exactly, not to a tolerance,
- the same **horizon**, fill policy and ambiguity policy,

and replaces only the **direction**, by reflecting the stop and the target about
the entry price. Which events get reflected is drawn at random, independently per
event, so exactly one thing is destroyed: the engine's ability to pick the side.

The levels are **reflected rather than re-derived** because the plan's stop and
target are themselves a function of the direction the engine chose. Re-deriving
them would hand the null a different trade, and the comparison would no longer
isolate anything.

**Why the direction and not the timing.** "Random entries into the same levels"
admits two readings. Randomising the *timing* would confound the claim about
*when* with the claim about *which way* — and because the levels are
direction-dependent, a randomly-timed entry at an unchanged direction leaves the
directional claim completely intact. The null would then be testing something the
engine never asserted. Randomising direction isolates the one claim the engine
actually makes, and holding the timing at the engine's own choice keeps the
comparison **matched** rather than generous to either side.

**What it is implemented as.** `src/albrooks/backtest/null.py`.
`null_distribution(bars, result, design)` returns the observed tally beside the
null distribution, and `NullDesign` carries every parameter that could bias the
result — `randomizations`, `seed`, `ambiguity_policy` — into the output, so a
number in a document can be re-derived. The seed defaults to a fixed value; a null
that cannot be reproduced is an anecdote.

**What it refuses, and why the refusal is the point.**

- `verdict` is the constant `UNDECIDED`. It is a property with no inputs, so no
  sample can change it — including a sample chosen to flatter the engine.
- `to_dict()` reports `"is_probability": false`, as every other surface here does.
- The comparison statistic is reported as a **count of null draws**, named
  `null_draws_at_or_above_observed`, and is **not** a p-value. Reading a fraction of
  random draws as a p-value is the same substitution this project refuses
  everywhere else, and it would be easy here precisely *because* a number is now
  available.
- A run is refused under `ConflictPolicy.PARALLEL` (the events overlap, so
  independent direction draws are not independent trades) and under
  `CLOSE_AND_REVERSE` (a path is truncated at a bar the event does not record, so
  the counterfactual's window would not be the observed one). Both would still
  produce a number, which is the problem.
- An empty sample is refused rather than scored as `0.0`.

**Why stating it now, with no data, is the whole value.** A null chosen after the
result is known is not a null; it is a rationalisation. Writing it down, running it
on fixtures, fixing the seed and refusing to score it means the comparison is
pinned before any real data exists to bias it — and it means the remaining three
ingredients can be obtained without renegotiating what "better than nothing" means.

**What it does not test.** The null isolates the directional claim. It says
nothing about the engine's timing, its stop placement, its ranking, or whether
these setups are worth trading at all. A null that beat on direction would not be a
licence to trade.


## 10. Source

`tests/fixtures/golden/` — the five fixtures and their schema
`tests/unit/test_phase19_golden.py` — 47 tests
`docs/FM_INDICATOR_AUDIT.md` §"Golden Regression Suite" — where this was first named
