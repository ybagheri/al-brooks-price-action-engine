# Al Brooks Price Action Engine — Living Roadmap

This roadmap documents the implementation progress across all 24 development
phases (0 through 23).

It answers four separate questions, and each is kept distinct because they are
different claims:

| Section | Question |
|---|---|
| [Where the project stands](#where-the-project-stands) | What is the state right now? |
| [Phase Checklist](#phase-checklist) | What is built and verified, phase by phase? |
| [Deliberately Not Built](#deliberately-not-built) | What will not be built, and why? |
| `CHANGELOG.md` → *Known limitations* | What is built but imperfect? |

## Status Legend
- `[x]` Completed & Verified
- `[ ]` In Progress / Pending

---

## Where the project stands

**22 of 24 phases are complete.** Phases 0 through 20 and 22 are done and verified
by the test suite. Phase 21 is partially delivered and Phase 23 remains.

### The engine is finished; the platform it runs on is not

Everything from bar normalization through to a gated, explained `BUY` / `SELL` /
`WAIT` decision exists, is closed-bar only, and is tested:

```text
bars -> features -> swings/legs -> context -> structures -> setups (11 detectors)
     -> evidence -> trade plan -> decision -> vetoes
```

| Layer | State |
|---|---|
| Bar-by-bar features, swings, legs, pivots | Complete |
| Market context and price-action structures | Complete |
| H1/H2, L1/L2, doubles, breakouts, reversals, measured moves, fading | Complete |
| Setup registry (11 detectors) and evidence model | Complete |
| Trade plans and the decision engine | Complete |
| Multi-timeframe alignment and the HTF veto | Complete |
| Non-repaint contract (`RPC-1`..`RPC-18`) | Complete |
| Backtesting interface | Complete — path geometry and outcome, **no P&L by design** |
| Golden fixtures | Complete — five hand-authored charts, hand-derived expectations |
| LLM serialization | Complete — 91.3% reduction, and no score leaves as a bare number |

### Phase 21 is half delivered, and the half that is missing needs hardware

**The MT5 adapter, the forming-bar freeze and the stateful session are built and
tested. The MQL5 port is not, and cannot be from where this was written.**

| Phase | What it adds | State |
|---|---|---|
| **21 — MT5 Adapter & MQL5 Layer** | `src/albrooks/adapters/mt5/` **shipped**; `mql5/Include/AlBrooks/` **blocked** | Needs MetaEditor and a terminal to write *and validate* a second implementation — which is what Phase 20 defined the contract for |
| **22 — AI / LLM Interface** | `src/albrooks/serialization/json.py`, `examples/llm_analysis.py` | **Complete.** Needed a stable serialized contract to hand an agent, and it now has one |
| **23 — Bilingual Documentation** | Expanded English and Persian documentation | Not started. Documentation-only; owes no new code path |

The port is not a deferral dressed up as a plan. An MQL5 implementation of this
scope — eleven detectors, the market-state classifier, the plan geometry and the
decision engine, reproducing a 33-field canonical vector — can only be *validated*
by compiling it with MetaEditor and running it against a live terminal. Neither
exists on the machine this was written on. Shipping thousands of lines of
never-compiled MQL5, or hand-writing a `"producer": "mql5"` sidecar to turn the
harness green, would put a false claim in the one place this project is most careful
about. So the parity status is unchanged and honest: **`UNVERIFIED`**.

`docs/algorithms/MT5_ADAPTER.md` §5 lists exactly what a real completion still owes,
and `tests/unit/test_phase21_adapter.py` asserts the empty `mql5/` state, so the day
a real sidecar lands the documentation has to move in the same change.

### The one thing that is not on this list

**No performance claim is made anywhere in this project, and no phase above adds
one.** Phases 18 and 19 make that concrete: the backtest module reports counts
and path statistics and refuses to produce a win rate, and the golden suite
establishes what the engine *names* rather than whether any setup works. What
would be required to change that — chiefly a stated null — is set out in
`docs/algorithms/VALIDATION.md` §9. A reader looking for evidence that these
setups have an edge will not find it here, and that absence is deliberate and
documented rather than an oversight.

**The same is true of parity, and it is worth saying in the same breath.** Phase
20 built the harness that will prove an MQL5 port agrees with this one, and
**zero cases have been compared** because no MQL5 build exists. The harness is
built to be unable to report agreement it has not earned — see *Deliberately Not
Built* below — and `docs/PYTHON_MQL5_PARITY.md` §7 says so in the document a
reader of that phase will open first.

---

## Phase Checklist

- [x] **Phase 0 — Repository Audit**
  - **Objective**: Inspect reference project `FM-indicator`, document reusable algorithms, technical debt, and migration strategy.
  - **Deliverable**: `docs/FM_INDICATOR_AUDIT.md`.
  - **Status**: Completed.

- [x] **Phase 1 — Architecture Foundation**
  - **Objective**: Package metadata, configuration, normalized bar representations, serialization, core models, CI workflow.
  - **Status**: Completed. The `Analyzer.analyze()` pipeline is wired; `docs/architecture/ARCHITECTURE.md` §7 documents the order and the reasons for it.

- [x] **Phase 2 — Bar-by-Bar Engine**
  - **Objective**: Objective per-bar features (body, wicks, close location, doji, inside/outside, barbwire, overlap, pressure).
  - **Deliverable**: `src/albrooks/price_action/bars.py`, `docs/algorithms/BAR_BY_BAR.md`, tests.
  - **Status**: Completed.

- [x] **Phase 3 — Swings, Pivots and Legs**
  - **Objective**: Fractal swing detection, legs, pivots, delayed confirmation without lookahead.
  - **Deliverable**: `src/albrooks/core/swings.py`, `src/albrooks/core/legs.py`, tests.
  - **Status**: Completed.

- [x] **Phase 4 — Market Context Engine**
  - **Objective**: Systematic proxies for TREND, CHANNEL, TRADING_RANGE, BREAKOUT_MODE, TRANSITION.
  - **Deliverable**: `src/albrooks/context/market_state.py`, tests.
  - **Status**: Completed.

- [x] **Phase 5 — Price-Action Structures**
  - **Objective**: Trend legs, channels, micro gaps, exhaustion, wedges, pressure.
  - **Deliverable**: `src/albrooks/core/structures.py`, tests.
  - **Status**: Completed.

- [x] **Phase 6 — H1/H2 and L1/L2 Engine**
  - **Objective**: Systematic pullback counting, candidate/provisional/confirmed/invalidated states.
  - **Deliverable**: `src/albrooks/setups/h1_h2.py`, `src/albrooks/setups/l1_l2.py`, tests.
  - **Status**: Completed.

- [x] **Phase 7 — Double Tops / Double Bottoms**
  - **Objective**: Major double tops/bottoms, micro double tops/bottoms, double tests.
  - **Deliverable**: `src/albrooks/setups/double.py`, tests.
  - **Status**: Completed.

- [x] **Phase 8 — Breakout Engine**
  - **Objective**: Breakout state machine (NONE -> PENDING -> BREAKOUT -> FOLLOW_THROUGH / FAILED), second-leg traps.
  - **Deliverable**: `src/albrooks/setups/breakout.py`, `src/albrooks/setups/failed_breakout.py`, tests.
  - **Status**: Completed.

- [x] **Phase 9 — Reversal / MTR Engine**
  - **Objective**: Major Trend Reversal, Minor Trend Reversal, climax exhaustion, reversal signal bars.
  - **Deliverable**: `src/albrooks/setups/reversal.py`, tests.
  - **Status**: Completed.

- [x] **Phase 10 — Measured Move Engine**
  - **Objective**: Generic MM framework (Leg 1 = Leg 2, Range projection, Channel projection, Gap projection, Inverse projection).
  - **Deliverable**: `src/albrooks/setups/measured_move.py`, `docs/algorithms/MEASURED_MOVES.md`, tests.
  - **Status**: Completed.

- [x] **Phase 11 — Fading Measured Move (FM)**
  - **Objective**: Port and refine FM lifecycle (PROJECTED, POTENTIAL, DEVELOPING, CONFIRMED, COMPLETED, INVALIDATED).
  - **Deliverable**: `src/albrooks/setups/fading_measured_move.py`, `docs/algorithms/FADING_MEASURED_MOVE.md`, tests.
  - **Status**: Completed.

- [x] **Phase 12 — General Setup Registry**
  - **Objective**: Plugin-style setup detector protocol, setup registry.
  - **Deliverable**: `src/albrooks/setups/registry.py`, `src/albrooks/setups/base.py`, tests.
  - **Status**: Completed. `SetupContext` is the common denominator for the eleven
    detectors and `adapt()` bridges their five different signatures, so none of
    them was rewritten. `docs/algorithms/SETUP_ENGINE.md` documents why the
    registry does not rank, and §9 of the architecture doc is asserted as a test
    rather than left as a comment. The registry does not yet *replace* the
    analyzer's direct detector calls; Phase 16 finished that half of the claim.

- [x] **Phase 13 — Setup Evidence Model**
  - **Objective**: Structured multi-factor evidence, weights, warnings, confidence heuristics.
  - **Deliverable**: `src/albrooks/evaluation/evidence.py`, `src/albrooks/evaluation/scoring.py`, tests.
  - **Status**: Completed. One `EvidenceFactor` shape for the five vocabularies,
    with a `basis` recording *why* each weight is the number it is
    (`MEASURED` / `LIFECYCLE` / `ASSERTED`) so a lifecycle position is never
    scored as though it sat on a continuum. The score is reproducible from its
    own factors and balances sources equally, so the chattier source cannot
    dominate on count alone. Per
    `docs/architecture/CONCEPT_TAXONOMY.md` §6 it is called an *evidence score*
    and the payload carries `is_probability: false`. Consumed by the pipeline
    from Phase 15, and extended in Phase 16 with the fading-measured-move lifecycle.

- [x] **Phase 14 — Trade Plan Engine**
  - **Objective**: Platform-independent trade plan (entry, stop, target, R:R, invalidation, management notes).
  - **Deliverable**: `src/albrooks/trade/plan.py`, `docs/algorithms/TRADE_PLAN.md`, tests.
  - **Status**: Completed. A `TradePlan` is entry, stop, target and the arithmetic
    between them — and **every one of the three prices carries a basis** saying
    where it came from, which is Phase 13's `basis` field applied to prices. A
    stop derived from a swing low and a stop derived from an ATR multiple are the
    same number meaning different things, so the second raises
    `VOLATILITY_FALLBACK_STOP` and leaves `has_structural_stop` False rather than
    passing as structure. Adding a setup family is a row in `ANATOMY_BY_FAMILY`,
    not a new builder, which holds `ARCHITECTURE.md` §9's one-change rule at this
    layer too. `is_valid` means the three prices are on the correct sides of each
    other and nothing more: every merit judgement is a warning left for the
    decision engine, because gating here would do that layer's work without the
    explanation machinery that makes its output auditable. The three issues that
    are decidable from the numbers alone are checked in `TradePlan.__post_init__`
    rather than by the builder, so a plan cannot be assembled that omits them.
    Wired into `Analyzer.analyze()` by Phase 15, the phase that needed it.

- [x] **Phase 15 — Decision Engine**
  - **Objective**: Transparent decision pipeline (BUY, SELL, WAIT, NO_TRADE) with structural vetoes and explainability.
  - **Deliverable**: `src/albrooks/decision/engine.py`, `src/albrooks/decision/veto.py`, `docs/algorithms/DECISION_ENGINE.md`, tests.
  - **Status**: Completed. This is where the ranking `ROADMAP.md` records as
    deliberately absent now belongs, and the whole design is about making that
    ranking auditable rather than authoritative: the criteria are declared in
    `RANKING_BASIS`, applied as `(-evidence_value, -reward_to_risk,
    candidate_id)`, and **echoed in every decision's output**, so a run over the
    same findings always agrees with itself and a reader never has to open a file
    to know why one plan won. `BUY` means "of the plans that passed every gate, this
    one had the most evidence by those criteria" — there is no `confidence` field
    and `Decision.to_dict()` carries `is_probability: false`.
    `NO_TRADE` and `WAIT` are kept distinct (nothing to say vs. something to say
    and a condition unmet), `enable_decision=False` answers `NO_TRADE` and never
    an inferred trade, and with every candidate vetoed **nothing is ranked** —
    picking the least bad of them would be a recommendation the project has not
    earned. Nine gates, eight blocking and one advisory; no gate short-circuits,
    every detail names both numbers compared, and a vetoed decision says which
    four keys to turn. The six config keys declared in Phase 1 are finally read,
    and each one is asserted to change an outcome.
    Wired into `Analyzer.analyze()`: `layers["trade_plans"]` and
    `layers["decision"]` are now `True` and `unimplemented_layers` is empty for a
    normal analysis, which is what that field has always existed to say.

- [x] **Phase 16 — Multi-Timeframe Architecture**
  - **Objective**: Synchronized HTF bias, timestamp alignment, strict no-lookahead contracts.
  - **Deliverable**: `src/albrooks/engine/pipeline.py`, `docs/algorithms/MULTI_TIMEFRAME.md`, tests.
  - **Status**: Completed. The layer is the narrower one it should be: a
    higher-timeframe *read*, not a higher-timeframe strategy. Alignment works in
    **close** times, because `Bar.time` is the open time and a high bar is not
    knowable until its last low bar closes; the newest usable high bar is
    `floor((i + 1) / ratio) - 1`, which is deliberately *not* `i // ratio`, and a
    test makes the forming high bar extreme and shows the bias does not move. The
    bar step is the **mode** of the timestamp gaps rather than the mean, so one
    weekend gap cannot become the bar period, and nothing parses a timeframe
    string - `ratio` is the caller's, cross-checked and reported if it disagrees.
    Timestamps that are missing or non-monotonic stop the alignment and say so,
    rather than producing a bias that reads as a neutral market.
    The bias is a **veto input, not a signal**: it *withholds* a decision that
    runs against it, and never inverts one, because knowing an M15 long disagrees
    with an H1 bear is not knowing it is a short. A directional read needs the
    higher proxy share to reach `htf_min_strength` (default 0.60, against a clean
    trend's 0.67), so a range or a chop cannot manufacture a conflict; the same
    fixture is asserted to veto at 0.30 and not at the default.
    **This phase also finished the pipeline work deferred since Phase 12**:
    `Analyzer.analyze()` now reads the setup registry instead of calling four
    detectors directly, so there is one detection path, `setups` covers the
    doubles and fading measured moves the pipeline never ran, and a run reports
    which detectors ran, were skipped, or failed.

- [x] **Phase 17 — Real-Time / Non-Repaint Contract**
  - **Objective**: Formal closed-bar guarantees, historical freeze, delayed confirmation validation.
  - **Deliverable**: `docs/algorithms/NON_REPAINT_CONTRACT.md`, tests.
  - **Status**: Completed. The closed-bar promise was scattered across
    `ARCHITECTURE.md` §6, four algorithm specifications and a dozen tests named
    after it. A claim spread across thirteen files is a claim nobody can check, so
    it is now **eighteen numbered guarantees** (`RPC-1`..`RPC-18`), each with the
    reason it exists, how it is enforced, and the name of the test that enforces
    it. Four of them are new work rather than a citation:
    `RPC-7` checks each of the eleven registered detectors *individually*, driven
    off `build_default_registry()` so a detector added later is covered by
    construction; `RPC-15` is the historical freeze, including while a forming bar
    *mutates*, which is the property a live consumer actually depends on; `RPC-16`
    proves the truncation is load-bearing by showing that passing the forming bar
    as if closed changes the answer; and `RPC-18` makes the document itself
    accountable by parsing it and failing if a guarantee names a test that does not
    exist. The contract also states what it does **not** promise, and documents
    that there is deliberately no forming-bar flag: freezing a live series is the
    adapter's obligation, which is why `RPC-14` and `RPC-15` say what happens when
    it does its job and `RPC-16` what happens when it does not.

- [x] **Phase 18 — Backtesting Interface**
  - **Objective**: Lightweight event-driven validation (MFE, MAE, time to target/stop, outcome metrics).
  - **Deliverable**: `src/albrooks/backtest/events.py`, tests.
  - **What it does**: `replay()` walks a series one closed bar at a time, calls
    `analyze(bars, last_closed=k)`, and records what the path after each decision
    did: which level came first, how many bars it took, and the maximum favourable
    and adverse excursion. Five outcomes, of which two are things that happened and
    are therefore not tidied away: `AMBIGUOUS`, where one bar contained both levels
    and OHLC cannot order them, and `INVALID_ENTRY`, a fill that arrived already
    through the stop. Neither is dropped from the sample.
  - **What it deliberately does not do**: no P&L, equity curve, expectancy, profit
    factor or win rate. Every one of those is a claim about the future, and
    nothing in this project has been validated against outcomes, so a green equity
    curve here would be arithmetically easy and evidentially worthless. Phase 19
    then built the golden fixture dataset and pointedly did *not* do that
    validation either — see its entry below. `sample_share()` exists and is
    deliberately not called a win rate.
  - **Three decisions that are policies rather than defaults to be argued about
    later**: a bar containing both levels is `AMBIGUOUS` and is resolved only at
    *reporting* time, with `STOP_FIRST` as the pessimistic default; the fill
    defaults to the next bar's open, the first price that existed once the decision
    could be acted on, rather than the signal bar's close; and overlapping signals
    are `SKIP`ped, because three decisions in twelve bars are usually one trend
    counted three times. `AMBIGUOUS` is never overwritten on the event itself, so
    the raw record survives the policy that reads it.
  - **Where the decision/outcome line falls**: the event's levels equal the plan
    from `analyze(bars, last_closed=k)` exactly and are unchanged when later bars
    are appended, and the outcome is a function of the horizon rather than of the
    data after it. The one honest exception is stated rather than hidden: with
    `horizon=None` a path runs to the end of the series, so a `NEITHER` can
    legitimately become a `TARGET_FIRST`, and a test asserts that this happens.
  - **Two defects found and fixed while testing this phase**, both recorded in
    `docs/algorithms/BACKTESTING.md` §6. Excursions were measured to the end of the
    horizon, which credited a stopped-out trade with everything the market did
    after it was no longer in the trade. And level-touching used one helper for both
    the target and the stop, reading the *favourable* extreme in both cases, so a
    long's stop was never tested and every reported "stop hit" was fabricated. The
    tests that now guard this build forward windows by hand rather than going
    through a fixture, because a fabricated reading from a fixture looks plausible.
  - **`caveats` travels inside the result** rather than only in the documentation, so
    a report cannot leave without them, and two of them are added dynamically: no
    horizon means excursions cover the rest of the data rather than a holding
    period, and `SKIP` with no horizon holds a position open until a level is
    actually reached.
  - **Whether a signal conflicts is answered by the open position's own outcome**,
    not by the horizon it was given. An earlier version of the loop treated a
    position as open until its horizon expired, which silently discarded every
    signal that followed a quick exit — a sample edited before anyone looked at it.

- [x] **Phase 19 — Validation Dataset**
  - **Objective**: Golden fixtures (`golden_fm_001`, `golden_h2_001`, `golden_breakout_001`, `golden_mtr_001`, `golden_double_001`).
  - **Deliverable**: `tests/fixtures/golden/`, tests.
  - **What it is**: five hand-authored charts, one per named concept, each with an
    expectation derived by hand from the bars and the documented gates. **It is a semantic
    regression suite, not a validation study** — it establishes what the engine *names*,
    and nothing about whether any setup works. There is no out-of-sample test, no
    parameter fit and no sample large enough to support one; `VALIDATION.md` §9 lists
    what would be needed, and the largest missing piece is a stated null.
  - **It is deliberately not a snapshot.** A golden file that stores the engine's output
    cannot tell a fix from a regression: it fails on both, passes on neither, and is
    updated by pasting whatever the code printed — which makes the human check optional.
    Instead each fixture pins specific values, states a `basis` for every one of them,
    and carries a list of **falsifiers**: bar edits whose effect the derivation
    predicts. Those are assertions about causality, and a snapshot structurally cannot
    have them. Twelve across the five fixtures.
  - **Provenance is enforced, not trusted.** Every pinned value needs a stated reason,
    each block of expectations must contain at least one piece of arithmetic, and every
    expectation is checked against an allow-list of behavioural fields so
    over-specification cannot creep in. An unrecognised `must_not` claim is a *failure*,
    not a skip.
  - **ATR is the one pinned value, and it is cross-checked.** It is Wilder smoothing over
    14 bars: checkable by hand, tedious fifty times over. So the fixtures pin it, and the
    suite re-derives it with an independent implementation and asserts agreement —
    two readings of the same definition, rather than one agreeing with itself. Everything
    downstream is written as a formula (`stop = extreme_price - 0.25 * atr`), so those
    claims hold for any ATR.
  - **Three findings, all recorded rather than fixed**, and the reasoning for each is in
    `VALIDATION.md` §5:
    - **The fade lifecycle is unreachable through the pipeline.** The registry calls
      `create_setups`, which only seeds; `track_fading_measured_moves` is never called by
      the engine. A live consumer sees `PROJECTED` / `age 0` for a projection the market
      has already reached. Fixing it means giving a stateless detector a stateful
      responsibility, which belongs with the MT5 adapter in Phase 21 — not with a test
      fixture. The honest boundary is pinned too: truncate before the target and the
      pipeline's reading is correct.
    - **The pullback window is a configuration choice, not a reading of price.** The
      detector calls *the first bar with a higher high* the first leg, so in a clean
      uptrend the "pullback" is just the last `max_pb_bars` bars. `golden_h2_001` pins
      the config and supplies a flat top, which is what makes a higher high meaningful.
    - **Two of the three disagreements were my own derivations being wrong**, not engine
      defects: a retest named at the wrong bar, and a falsifier that expected to delete a
      double top where it actually moves it earlier in the window. Both are recorded in
      the fixtures, and both were fixed by correcting the derivation.
  - `docs/algorithms/VALIDATION.md`, promoted to a required document in CI, and
    `tests/unit/test_phase19_golden.py` — 47 tests.

- [x] **Phase 20 — Python / MQL5 Parity**
  - **Objective**: Closed-bar parity validation harness between Python and MQL5 components.
  - **Deliverable**: `tests/parity/`, `docs/PYTHON_MQL5_PARITY.md`.
  - **What it is**: the *contract* two implementations would be compared against.
    A **canonical vector** — 33 declared fields across eight groups: the analysed
    bar, ATR, the market state, the swings with both their bar index and their
    **confirmation** index, the detected setups, the trade-plan geometry with the
    basis of every level, and the decision with its reason code. Every field
    carries a declared comparison class, and the classes are not uniform on
    purpose: an index that differs by one is a repaint bug, a price that differs
    in the fifteenth digit is a summation order, and only the second gets a
    tolerance (`RELATIVE_TOLERANCE = 1e-9`). The worst observed deviation is
    reported for every case, pass or fail, so two runs that both passed with very
    different margins do not read the same.
  - **What it deliberately does not do**: compare anything. **No MQL5 build
    exists, `tests/parity/mql5/` is empty, and zero of the three cases have been
    compared.** A run today reports `UNVERIFIED`, which is neither a pass nor a
    failure, and a test asserts that shipped state rather than letting the
    document and the code drift apart.
  - **The cycle this phase broke, and how**: the roadmap as first written had
    Phase 20 needing an MQL5 build to compare against and Phase 21 depending on
    Phase 20, so neither could start. The resolution was to split *contract* from
    *fill*: Phase 20 owns the canonical form, the comparison policy, the cases
    and the report, and Phase 21 owns the MQL5 build and the first sidecars. The
    alternative — port first, comparison second — means writing the specification
    from the port's own behaviour, which is how a parity harness ends up asserting
    only what both sides already agree on.
  - **Three refusals, which are the design rather than the packaging**:
    a sidecar whose `producer` is not `mql5` is not parity evidence (which is what
    makes the committed Python-produced vectors in `tests/parity/reference/` safe
    to keep); a sidecar covering a strict subset of the scope is refused, so
    "we agree on the three fields we implemented" cannot pass; and a sidecar
    written against a different schema is refused, because two sides implementing
    different contracts can agree on everything they both check.
  - **`AGREED` requires every case to have been compared.** Half a case set is not
    half a pass, and a boolean cannot say "these two agreed and that one was never
    run", so a partially filled run is `FAILED`. `UNVERIFIED` has its own exit code
    and CI's `--allow-unverified` is asserted by a test to exist exactly while the
    shipped state is `UNVERIFIED`, so neither can be removed without the other.
  - **Two things it will not assert**: the parity vector is closed-bar stable,
    which is `RPC-1` restated for the thing the port has to reproduce — except for
    `bars_processed`, the one field that describes the *input* rather than the
    analysis, and the document says so rather than leaving the exception to be
    discovered. And list **order** is not compared, because an MQL5 registry is not
    this registry; list **count** is, which is the difference that changes
    behaviour.
  - `docs/PYTHON_MQL5_PARITY.md`, `tests/parity/README.md`,
    `tests/unit/test_phase20_parity.py` — 56 tests, and a CI step.

- [ ] **Phase 21 — MT5 Adapter & MQL5 Layer** — **partially delivered.** The
  checkbox stays open, and the reason is stated rather than negotiated.
  - **Objective**: MQL5 include headers, MT5 python connector, indicator & EA templates.
  - **Deliverable**: `src/albrooks/adapters/mt5/` **shipped**;
    `mql5/Include/AlBrooks/` **blocked on MetaEditor**.
  - **Shipped** — `src/albrooks/adapters/mt5/`: `MT5Feed` (the only module that
    names `MetaTrader5`, and it imports it lazily so the package imports on a
    machine with no terminal), `normalize_order()` for the series direction,
    `freeze_closed_bars()` for the forming bar, `ENUM_TIMEFRAMES` decoding, and
    `AnalysisSession`. `docs/algorithms/MT5_ADAPTER.md`, 60 unit tests and 8
    read-only live-terminal checks.
  - **Corrected against a live terminal, and the correction is part of the
    deliverable.** All 54 original tests passed while three defects were live:
    `copy_rates` **does not exist** in the Python bindings, the payload is
    **oldest-first** rather than newest-first, and the server clock ran **+3.1
    hours** ahead of the local one, discarding 13 of 50 M15 bars. The general
    lesson is recorded in `MT5_ADAPTER.md` §10 because it is the more useful half:
    **a fake encodes the author's assumptions**, and fifty-four green tests
    certified agreement with a mental model of MetaTrader rather than with
    MetaTrader. `tests/integration/test_phase21_live_mt5.py` now checks what a fake
    cannot — which functions exist, which direction arrives, and whether `RPC-2`
    holds on a real series. It skips without a terminal, and a skip is not a pass.
  - **The direction check was the wrong one.** It refused anything that was not
    newest-first, which is the MQL5 native convention rather than the bindings' —
    so it would have raised on every real payload. What matters is **monotonicity,
    not direction**: both single directions are legitimate conventions and both are
    now normalised, with the direction observed *returned* rather than discarded. A
    payload that is neither ascending nor descending is still refused, because
    inferring the caller's intent from a broken sequence is the guess that produces
    a confident wrong answer.
  - **The freeze uses the terminal's clock.** The 3.1-hour skew is *directional*:
    a local clock behind the server over-freezes (13 bars lost, annoying), and one
    ahead would keep a still-forming bar — a look-ahead. So neither is acceptable
    and the server clock is read by default, with `FreezeReport.clock` recording
    which was used.
  - **The freeze decides by time, not by position.** `bar.time + period <= now`,
    because `Bar.time` is the *open* time. "Drop the last row" is wrong at every
    bar boundary and silently wrong across a weekend or a session break, and both
    failures look like a working adapter until a comparison fails for no visible
    reason. Three tests hold it down, and the two that pin the shortcut's failures
    are the ones a positional freeze would fail: a call in the instant after a bar
    closed keeps **every** bar, and a series whose newest bar closed hours ago does
    not shrink.
  - **A calendar month is refused rather than assumed.** `MN1` has no fixed period,
    so `period_seconds()` raises `TimeframeUnsupported` instead of assuming 30 days
    — a freeze that is wrong on two days of every month is a look-ahead that *looks
    like a correct answer*. A caller who knows the period supplies it.
  - **A mis-ordered payload is refused, not sorted.** `PYTHON_MQL5_PARITY.md` §3.1
    calls the series direction *the single likeliest divergence in the whole port*,
    and the reason is that a reversed series still analyses: swings, a market state,
    a decision and a set of plans, all internally consistent and all about the
    wrong direction. Sorting would hide the caller's bug behind a working result.
    **Measured:** the two MetaTrader APIs disagree — the Python bindings are
    oldest-first, MQL5 native is newest-first — so both are accepted and
    normalised, and only a payload that is *neither* is refused.
  - **The Phase 19 finding is closed.** `AnalysisSession` calls
    `track_fading_measured_moves`, so the lifecycle a live consumer could not see
    — `PROJECTED` with `age 0` forever, for a projection the market had already
    reached and rejected — is now reachable. It **re-derives** rather than
    accumulating, and that is the load-bearing decision: an incremental state
    machine would break `RPC-1`, since a session that has seen bars 21..40 and then
    answers for bar 20 is holding state derived from bars the caller declared
    unavailable. The pipeline still reports `PROJECTED` — the registry is stateless
    and that is its contract, and the session adds a caller rather than editing it —
    so `SessionResult.fade_source` says which reading is which and a test asserts
    **both**.
  - **Not shipped** — `mql5/Include/AlBrooks/`, and the sidecars that would fill the
    parity harness's `mql5/` directory. **This is still blocked**, and running a
    real terminal sharpened rather than removed the reason: a live Alpari MT5 build
    6230 found three defects in 54 passing tests, so an MQL5 port validated only by
    inspection would carry the same class of error at a larger scale.
    `docs/PYTHON_MQL5_PARITY.md` §8 lists what it owes, and
    `docs/algorithms/MT5_ADAPTER.md` §5 and §10 repeat it. A test asserts that
    `mql5/` does not exist and that the parity run still reports `UNVERIFIED`, so
    the day a real sidecar lands the documentation has to move in the same change.

- [x] **Phase 22 — AI / LLM Interface**
  - **Objective**: Stable JSON serialization for LLM agents, diagnostic output, example script.
  - **Deliverable**: `src/albrooks/serialization/json.py`,
    `examples/llm_analysis.py`, `docs/algorithms/AI_INTERFACE.md`, 43 tests.
  - **A reduction with a measured justification, not a reformatting.**
    `AnalysisResult.to_dict()` is 73,769 characters for a 60-bar series and
    **88.9% of that is `bar_features`** — 28 numeric fields per bar. A model
    handed the raw payload spends its attention on per-bar arithmetic and has
    almost none left for the decision. `brief()` produces **6,384 characters, a
    91.3% reduction, ~1,600 estimated tokens**, and the example script prints that
    comparison so the claim is checkable rather than asserted.
  - **An LLM is the riskiest consumer in this project, and the interface is built
    around that.** Handed `{"action": "BUY", "evidence_score": 0.85}`, a model
    reads a probability, because that is what those shapes mean everywhere else.
    It is not: `CONCEPT_TAXONOMY.md` §5 classifies nothing here as `STATISTICAL`,
    because nothing has been validated against outcomes. Four mechanisms make the
    misreading *structurally hard* rather than merely discouraged, and each is
    tested:
  - **No score leaves as a bare number.** Every such value is an object carrying
    `is_probability: false` and a sentence saying what it is, so there is nothing
    to pattern-match. A test walks the whole payload and asserts no number
    appears under a score-like key unless its parent carries a label — so a
    section added later is covered by construction.
  - **The refusals are enforced on every call.** `confidence`, `pnl`, `win_rate`,
    `expectancy`, `profit_factor` and six more are refused at *any depth* by
    `_assert_refusals()`, which runs inside `brief()` rather than only in tests.
    The suite tests every key, and proves the guard fires against real output by
    injecting a simulated future `confidence` field. Same pattern Phase 18 uses on
    the backtest module.
  - **The caveats cannot be dropped.** No flag suppresses them, and a test
    asserts the specific misreadings are addressed rather than merely that
    caveats exist. `PROVENANCE` declares `is_validated: false`,
    `is_a_recommendation: false` and `is_financial_advice: false` explicitly
    rather than by absence.
  - **A reduction says so.** `truncated` is on every call, listing each dropped
    section with a reason and an item count, and an *empty* list is still a claim
    that is tested as such. Sections are dropped **whole** — half a stop price is
    a different stop, so a payload that is wrong rather than incomplete is the one
    outcome this cannot produce.
  - **Prices are not rounded by default.** The fixture's stop is
    `106.68656533354194`; rounding it to 2dp moves the stop through the level it
    protects. `float_digits` exists for display and records `is_lossy: true`.
  - **The instructions come *after* the data, deliberately.** A model reads the
    data first, so framing placed first would compete for attention with 6,000
    characters of numbers; placed last it is the final thing in the context.
  - **The schema version is separate from the parity contract.**
    `albrooks-llm/1` is a single-implementation payload for a reader;
    `albrooks-parity/1` is a two-implementation comparison contract with
    per-field tolerance classes. They will drift, and sharing a version would make
    "the fields moved" indistinguishable from "the market moved".
  - **Deterministic by construction.** Sorted keys and shortest-round-trip float
    repr, so the same analysis always produces byte-identical JSON. That is what
    makes a regression on the *payload* visible at all, and it is why
    `tests/fixtures/golden/` can stay a hand-derived suite rather than becoming a
    snapshot — a snapshot of a non-deterministic output fails on every run.
  - **What it will not do**: no field readable as a probability, no suppressible
    caveats, no silent truncation, no model call in the example, and **no
    `summary` or `signal` field** — anything a consumer would call "the signal"
    would be an interpretation this project has not earned.

- [ ] **Phase 23 — Comprehensive Bilingual Documentation**
  - **Objective**: Complete English and Persian documentation suite (`README.md`, `README_FA.md`, algorithm specs).
  - **Deliverable**: `docs/`, `README.md`, `README_FA.md`.

---

## Deliberately Not Built

The other two lists above say what *is* done and what *remains*. This one records
what is **not going to be built**, and why — because a project whose premise is
honest self-reporting should not leave its exclusions implicit either.

Each entry states the thing, the reason, and what would have to change.

### Competing setups are ranked, and the ranking is not an edge

A measured-move target and a reversal leg count are different kinds of claim, so
the layers below the decision engine deliberately refuse to compare them:

- The registry returns findings in **registration order**, which is deterministic
  and is not a ranking (`docs/algorithms/SETUP_ENGINE.md` §5).
- `evaluation.compare()` orders bundles **for display only**; nothing downstream
  may treat its order as a recommendation
  (`docs/algorithms/EVIDENCE_MODEL.md` §6).
- A `TradePlan` is reported in full and is not sorted by reward:risk
  (`docs/algorithms/TRADE_PLAN.md` §2).

**Phase 15 is the exception, and it is a narrow one.** `decision.decide()` sorts
eligible candidates by `(-evidence_value, -reward_to_risk, candidate_id)`, and
that ordering is the answer. It is a ranking of transparent criteria with nothing
behind it: no outcome has ever been checked against them
(`docs/algorithms/DECISION_ENGINE.md` §6). The criteria are declared in
`RANKING_BASIS` and echoed in every decision's output precisely so the ranking can
be argued with.

Two things are still refused, and they are the refusals that matter:

- **The least bad candidate is never promoted.** With every candidate vetoed the
  answer is `WAIT` with the failing gates named. Ranking a fourth-best trade
  because the first three failed would be a recommendation, not a comparison.
- **A contested reading is never resolved by arithmetic.** Two directions within
  `conflict_ppts` of each other is `WAIT` / `EVIDENCE_CONFLICT`, not the
  numerically larger one.

*Changes when:* a validation phase (19/20) calibrates the criteria against
outcomes. Until then, the criteria are `HEURISTIC` in `CONCEPT_TAXONOMY.md` §4 and
`Decision.to_dict()` carries `is_probability: false`.

### No score in this project is a probability

`CONCEPT_TAXONOMY.md` §5 classifies no value here as `STATISTICAL`, because
nothing has been statistically validated. The evidence score is a mean of
observed factor weights; `0.8` does not mean "right 80% of the time".
`EvidenceScore.to_dict()` and `Decision.to_dict()` both carry
`is_probability: false` so downstream consumers are told rather than left to know.

This now covers the decision layer as well as the evaluation layer. There is
deliberately **no `confidence` field anywhere in this project**, and the gate is
named `min_score` rather than `min_confidence` for the reason
`CONCEPT_TAXONOMY.md` §6 gives.

*Changes when:* a validation phase (19/20) calibrates against historical data.
Per the taxonomy, the method, sample and confidence intervals must be documented
there **before** any of these labels may change.

### The decision layer abstains rather than guessing

Five situations produce no direction, and each has its own reason code so a
caller can tell them apart:

| Situation | Answer |
|---|---|
| `enable_decision=False` | `NO_TRADE` / `DECISION_DISABLED` |
| No volatility reference | `NO_TRADE` / `NO_ANALYSIS` - no gate could be evaluated |
| Nothing found | `NO_TRADE` / `NO_CANDIDATES` |
| Everything gated | `WAIT` / `ALL_CANDIDATES_VETOED` |
| Two sides within `conflict_ppts` | `WAIT` / `EVIDENCE_CONFLICT` |
| Higher timeframe reads the other way | `WAIT` / `AGAINST_HIGHER_TIMEFRAME` |

`NO_TRADE` and `WAIT` stay distinct because "I have nothing to say" and "I have
something and it does not meet the conditions" call for different behaviour from a
caller. Collapsing them would make an empty result read as a judgement.

`enable_decision=False` is the one setting where a plausible-looking `BUY` would be
indefensible - the user asked for no decision - so it is checked before anything
else and can never be overridden by a strong candidate.

*Changes when:* never, as long as the abstention is the honest answer. What *can*
change is how many candidates survive the gates.

### A trade plan is not an order, and it is not sized

`trade/plan.py` produces entry, stop, target, R:R, an invalidation sentence and
management notes. It produces **no order type, no lot size, no position sizing,
no slippage and no session filter**, and the fields are asserted absent by a
test.

Position sizing in particular is a deliberate omission rather than a gap. It
requires an account risk policy - what fraction of equity may one idea risk - and
that is a statement about the account and the operator, not about the chart. This
project has no validated edge to size against, so a lot size computed here would
be a number with nothing behind it.

*Changes when:* the execution layer (Phase 21) needs a sizing policy, and it will
need a backtest and golden fixtures to have any basis for one. Both now exist
(Phases 18 and 19), and neither supplies the missing ingredient: real labelled
data. `VALIDATION.md` §9 says what would.

### A plan's R:R is a gate, not a merit judgement

`reward_to_risk` is arithmetic: `reward / risk`. The decision layer reads it
through `min_rr` and reports the comparison, and that is as far as it goes - no
value of `min_rr` makes a plan good. Setting it to 3.0 does not improve a 3.1
plan; it makes fewer plans eligible, which is a different thing.

The plan layer itself does not gate on it at all: `plan_max_stop_atr` produces a
**warning** (`STOP_WIDE`), not a veto, and the plan is still returned and still
`is_valid`.

*Changes when:* a validation phase (19/20) has outcomes to say which
reward:risk ratios behaved differently. Until then `min_rr = 1.0` is a
convention, and `docs/algorithms/DECISION_ENGINE.md` §5 labels it `HEURISTIC`.

### A double top/bottom's own measured target is not computed

`DoublePattern` records `bar1`/`bar2` and `price1`/`price2` but not the
neckline-to-extreme height a double target needs. This project will not invent a
geometry the detector did not record, so a double's target is a swing or a
volatility multiple and every such plan carries `DOUBLE_TARGET_NOT_MEASURED`.

*Changes when:* `setups/double.py` records the height. That is a Phase 7
extension, and it would make the plan's target structural rather than derived.

### `max_failed_attempts` counts two things, not "failed attempts"

The gate's name says more than it measures. It counts the plan's terminal flag
plus every evidence factor in `ADVERSE_EVIDENCE_CODES`, which today is
`BREAKOUT_TRAP` and `SECOND_LEG_TRAP` - the only negative observations the Phase 13
adapters emit. An `INVALIDATED` pullback is *excluded* by its adapter rather than
scored, so it never reaches a count.

The list was left narrow rather than widened to match the name. A count that looks
comprehensive and is not is worse than a narrow one that says so, and the veto's
`detail` always lists the codes it counted so the basis is visible.

*Changes when:* the evidence model can count failures. The fading-measured-move
lifecycle arrived in Phase 16; a count of *failed* fades still needs the terminal
states to be recordable rather than excluded, which is a change to the adapters
rather than a wider constant here.

### `max_late_atr` measures staleness, not wrongness

The gate compares `abs(close - entry) / atr` against `max_late_atr` and says the
plan is **out of date**: price has moved away from the level the plan was built on.
It does not say the plan is wrong, and a plan that has drifted can still work - it
is just not the entry that was described.

*Changes when:* a higher-timeframe *structure* analysis exists, not merely a
higher-timeframe read. Phase 16 supplies the read: a directional bias from the
higher series' market-state proxy, gated on `htf_min_strength`. It has no
higher-timeframe swings, legs or setups of its own, so it is context and nothing
more.

### The multi-timeframe veto is one blunt rule

`AGAINST_HIGHER_TIMEFRAME` knows exactly one thing: the higher timeframe's
market-state proxy reads the other way. That is enough to *withhold* a signal and
not enough to *reverse* one, so it withholds.

A genuine counter-trend trade is indistinguishable from a mistake at this
resolution. `htf_opposition_veto=False` exists precisely because the default is a
choice rather than a finding, and `docs/algorithms/MULTI_TIMEFRAME.md` §11 records
it as the layer's largest false-positive risk.

*Changes when:* a higher-timeframe *structure* analysis exists - HTF swings, legs
and setups rather than a single bar's classification - at which point "the higher
timeframe disagrees" could be resolved into something more specific than yes or no.

### Parity is defined, and unproven

Phase 20 built the harness that will prove an MQL5 port agrees with this engine.
**It has not proved it, and it cannot be read as having tried.** `tests/parity/`
ships three cases, an empty `mql5/` directory, and a runner whose verdict today is
`UNVERIFIED` — a distinct status from both a pass and a failure, because nothing
was compared.

The harness is built so this state cannot be mistaken for a result:

- `claims_parity` is true only for `AGREED`, which needs **every** case compared
  and matching.
- A sidecar that did not come from an MQL5 build is not counted at all, so the
  committed Python-produced vectors cannot be compared against themselves and
  called agreement.
- `UNVERIFIED` is its own exit code, so a CI job does not have to choose between
  failing over a build nobody has written and passing silently.

*Changes when:* Phase 21 writes the first real sidecars — which requires
  MetaEditor and a terminal, so it has not happened. The expectation should be
  that the first run **fails**: a port's ATR seed, series direction, swing
  tie-break and null convention are four easy places to diverge, which is why each
  is in scope, and the disagreements should be recorded rather than tuned away.
  Two of the four are now *half*-addressed on the Python side — the series
  direction is refused rather than sorted, and the ATR seed is Wilder's — and
  neither is a parity result. **A hand-written `"producer": "mql5"` file would be
  worse than no MQL5 code at all**, because the harness would then be reporting an
  agreement it never measured.

### A new *layer* is not covered by the non-repaint contract for free

A setup detector added through the registry is covered by `RPC-7` **by
construction**, because the closure test iterates `build_default_registry()`. A new
*layer* is not: it inherits the contract only by asserting `RPC-1` for itself -
analyse at bar `k` with and without future bars, and compare.

That asymmetry is stated rather than papered over, and
`docs/algorithms/NON_REPAINT_CONTRACT.md` §7 says the same. It is the only
coverage this project can offer without pretending a property it has not checked.

### `engine.state.NOT_IMPLEMENTED` is unused

The constant `NOT_IMPLEMENTED = "NOT_IMPLEMENTED_YET"` is defined and referenced
nowhere. Its stated purpose — distinguishing "not detected" from "never looked
for" — is actually served by the `layers` map, and `unimplemented_layers` reads
that. The constant is retained as a reserved marker, not because it is live.

*Changes when:* something needs a per-*value* not-implemented marker, as opposed
to the per-*layer* one already implemented.

### `examples/llm_analysis.py` makes no model call

The example produces the payload and prints it. There is no API call, no key and
no network, and that is deliberate: the testable part of an LLM interface is the
*shape of the payload*, and adding a model call would make the example depend on
a key, a connection, and a model's mood on the day.

It also means the example cannot be mistaken for a demo of "ask an AI and get a
trade". It demonstrates a serialization and its refusals. Whether any particular
model reads the payload correctly is **not measured**, and adding that claim would
be the same error the interface is built to prevent.

*Changes when:* an evaluation exists that says something about it. There is none,
and `VALIDATION.md` §9 is where one would have to start.

### `mql5/` does not exist, and that is a statement about the hardware

There is no MQL5 port of this engine in the repository. `tests/parity/mql5/` is
empty, all three cases name no sidecar, and a parity run still reports
`UNVERIFIED`.

This is **not** a deferral dressed up as a plan. An MQL5 implementation of this
scope can only be *validated* by compiling it with MetaEditor and running it
against a live MetaTrader terminal, and neither exists on the machine this was
written on. The two ways to make the status read better would both be worse than
the status itself: shipping thousands of lines of never-compiled MQL5 under a
directory named `AlBrooks`, or hand-writing a `"producer": "mql5"` sidecar to turn
a green run into a red one. The second is precisely the dishonesty the Phase 20
harness was built to detect, and committing it would turn the harness into a
decoration.

What *was* built is the half that needs no MetaEditor: the adapter, the freeze and
the stateful session. `tests/unit/test_phase21_adapter.py` asserts that `mql5/`
does not exist and that parity is still `UNVERIFIED`, so the state is a fact the
suite checks rather than a claim the documentation makes.

*Changes when:* someone runs MetaEditor. `docs/PYTHON_MQL5_PARITY.md` §8 has the
ordered list, and the expectation is that the first run fails.

### Not started at all

`src/albrooks/serialization/` still contains only an empty `__init__.py` — a
placeholder for Phase 22, not a partial implementation. `src/albrooks/adapters/`
is no longer one: `adapters/mt5/` is populated and is on the path a live consumer
takes, though nothing in the engine reads it. `src/albrooks/trade/`,
`src/albrooks/decision/` and `src/albrooks/engine/pipeline.py` are populated and
read by `Analyzer.analyze()` - Phases 14, 15 and 16 - so nothing below the
adapters layer is a placeholder any more.

