# Changelog

All notable changes to this project are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Status: pre-1.0.** The public API may still change. Nothing in this project has
been statistically validated, and no performance claim is made.

## [Unreleased]

### Added
- **Phase 23** — `docs/fa/`: a Persian documentation tree, and
  `tests/unit/test_phase23_bilingual.py` — 15 tests that keep the two languages
  from drifting apart silently. Closes the last phase that needed no external
  tooling.
  - **What actually existed before this**: 24 English documents and **zero**
    Persian ones. `README_FA.md` was a 19-section translation of a 20-section
    English README, and no algorithm or architecture document had a Persian
    counterpart. The gap was not "some translations are thin" but "the
    algorithmic documentation is monolingual".
  - **`docs/fa/README.md` is an index first and a translation second.** It
    records, for all 24 English documents, whether a Persian version exists. The
    two states a reader must not confuse are *"there is a translation"* and
    *"there is not"*, and the index says which is which.
  - **Three documents are translated in full**, chosen by a stated rule rather
    than convenience: a document is translated when it makes a claim a reader
    could **act on**. That is `CONCEPT_TAXONOMY.md` (why no number here is a
    probability), `VALIDATION.md` (what is missing and §9's four prerequisites)
    and `AI_INTERFACE.md` (what the LLM interface refuses to emit). A Persian
    reader acting on `evidence_score` without the first is worse off than a
    reader with no document at all.
  - **The other 21 are recorded as untranslated, and that is a decision.**
    A machine translation of the remaining 4,000 lines would have produced the
    *appearance* of completeness and the *substance* of guesswork, and the
    errors a machine translation introduces are exactly the dangerous kind: a
    score rendered as a confidence, in one word. A partial translation whose
    status is declared is honest where a complete uncertain one is not.
  - **The two trees cannot drift silently.** The English documents are
    unverifiable by anything else, because the tests read the Python and not the
    prose — so the claims this project refuses to make are made in prose, and
    prose is what nothing checks. The suite therefore asserts that every
    English document has a recorded Persian status in **both** directions, that
    one marked translated exists and one marked untranslated does not, that a
    full translation carries the **same numbered sections** as its source, and
    that each names its English source and says which text is authoritative on
    conflict.
  - **The one substantive check is about the rule itself, and its first version
    was wrong.** A translation rendering "evidence score" as "درجهٔ اطمینان" has
    introduced the exact claim `CONCEPT_TAXONOMY.md` §5 exists to prevent. The
    obvious test is a forbidden-phrase scan, and it flagged every line that
    *denied* the claim — because "this is not a probability" contains the words
    "not" and "probability". Seven English lines were false positives, including
    §5 itself. So the property is stated the other way round: **a translated
    document must affirm the rule**, which a translation calling a score a
    confidence would not do. A check that cries wolf gets disabled, and a
    disabled check protects nothing.
  - **Identifiers are not translated.** `OBJECTIVE`, `is_probability`,
    `FORBIDDEN_KEYS` and the other taxonomy labels and field names appear
    verbatim, because a translator who renames a field produces prose that reads
    correctly and cannot be used.
  - Both guards were verified by breaking them: removing a section from a
    translation and flipping a required denial both fail the suite, and both
    restore clean.
- **Phase 22** — `src/albrooks/serialization/json.py`: a stable JSON serialization
  for a language model, `examples/llm_analysis.py` as a runnable demonstration,
  `docs/algorithms/AI_INTERFACE.md` as the specification, and 43 tests. Closes the
  0.1.0 known gap for a missing `examples/` directory.
  - **A reduction with a measured justification, not a reformatting.**
    `AnalysisResult.to_dict()` is 73,769 characters for a 60-bar series and
    **88.9% of that is `bar_features`** — 28 numeric fields per bar. A model handed
    the raw payload spends its attention on per-bar arithmetic and has almost none
    left for the decision. `brief()` produces **6,384 characters: a 91.3% reduction,
    ~1,600 estimated tokens**, and the example script prints that comparison so the
    claim is checkable rather than asserted.
  - **An LLM is the riskiest consumer in this project, and the interface is built
    around that fact.** Handed `{"action": "BUY", "evidence_score": 0.85}` a model
    reads a probability, because that is what those shapes mean everywhere else. It
    is not: `CONCEPT_TAXONOMY.md` §5 classifies nothing here as `STATISTICAL`,
    because nothing has been validated against outcomes. Four mechanisms make the
    misreading *structurally hard* rather than merely discouraged, and each is
    tested.
  - **No score leaves as a bare number.** Every such value is an object carrying
    `is_probability: false` and a sentence saying what it is, so there is nothing
    for a model to pattern-match, and the label travels at the point of use rather
    than in a preamble that gets skipped. A test walks the whole payload and
    asserts no number appears under a score-like key unless its parent is labelled —
    so a section added later is covered by construction.
  - **The refusals are enforced on every call, not documented.** `confidence`,
    `pnl`, `win_rate`, `expectancy`, `profit_factor` and six more are refused at
    *any depth* by `_assert_refusals()`, which runs inside `brief()`. The suite
    tests every key, plus nested, list-contained and renamed variants, and proves
    the guard fires against real output by injecting a simulated future
    `confidence` field into `_decision()`. A guard that has never failed is
    indistinguishable from one that cannot fail. Same pattern Phase 18 uses on the
    backtest module.
  - **The caveats cannot be dropped.** No flag suppresses them, and a test asserts
    the specific misreadings are addressed rather than that caveats merely exist.
    `PROVENANCE` declares `is_validated: false`, `is_a_recommendation: false` and
    `is_financial_advice: false` explicitly rather than by absence, because absence
    is ambiguous and these are the fields a reader is most likely to check.
  - **A reduction says so.** `truncated` is present on *every* call, listing each
    dropped section with a reason and an item count; an *empty* list is still a
    claim and is tested as such. Sections are dropped **whole** — half a stop price
    is a different stop, so a payload that is wrong rather than incomplete is the
    one outcome this cannot produce.
  - **Prices are not rounded by default.** The fixture's stop is
    `106.68656533354194`; rounding to 2dp moves the stop through the level it
    protects. `float_digits` exists for display and records `is_lossy: true`.
  - **The instructions come *after* the data, deliberately.** A model reads the
    data first and the framing second, so framing placed first would compete for
    attention with 6,000 characters of numbers; placed last it is the final thing
    in the context, the position recency favours.
  - **A separate schema version.** `albrooks-llm/1` is a single-implementation
    payload for a reader; `albrooks-parity/1` is a two-implementation comparison
    contract with per-field tolerance classes. They will drift, and sharing a
    version would make "the fields moved" indistinguishable from "the market
    moved". A test asserts the two are distinct.
  - **Deterministic by construction.** Sorted keys and shortest-round-trip float
    repr, so the same analysis always produces byte-identical JSON. That is what
    makes a regression on the *payload* visible, and it is why
    `tests/fixtures/golden/` can stay a hand-derived suite: a snapshot of a
    non-deterministic output fails on every run.
  - `canonical()` keeps the full result with a promise attached — nothing dropped,
    nothing rounded — for diffing and regression.
  - `estimate_tokens()` is labelled an estimate: four characters per token is
    reasonable for English JSON and poor for code or Persian text, and a number in
    the wrong unit would be worse than no number.
- **What the interface refuses**: any field readable as a probability, a
  suppressible caveat, a silent truncation, price rounding by default, a model call
  in the example, and **no `summary` or `signal` field** — anything a consumer would
  call "the signal" would be an interpretation this project has not earned.
- **Phase 22 is complete while Phase 21 is not**, which broke an assumption baked
  into `test_project_status.py`: that completed phases are contiguous. They are
  not and cannot be — Phase 21's MQL5 port is blocked on MetaEditor indefinitely,
  while Phase 22 needed nothing external. The watermark `LAST_COMPLETE_PHASE` is
  replaced by a `COMPLETE_PHASES` set, and the roadmap's progress sentence is
  asserted to agree with its own checkboxes. "Phases 0 through 22 are done" was
  false the moment Phase 22 landed, and a summary sentence that reads as truth and
  is not is the specific failure this project's own test file exists to catch.
- **Phase 21, partially delivered** — `src/albrooks/adapters/mt5/`: the MetaTrader 5
  adapter, and the two obligations `NON_REPAINT_CONTRACT.md` §4 assigns to an
  adapter rather than to the analysis. `docs/algorithms/MT5_ADAPTER.md`, and 54
  tests driven by an injected fake terminal — the `MetaTrader5` name appears nowhere
  in the suite, which is what keeps it runnable on CI.
  - **The series direction.** The engine is oldest-first and MetaTrader is not, but
    *which way* depends on the API: the Python bindings are oldest-first (measured),
    MQL5 native is newest-first. `PYTHON_MQL5_PARITY.md` §3.1 calls this *the single
    likeliest divergence in the whole port*. `normalize_order()` is the only path from
    an MT5 payload to a `BarSeries`; it normalises from either direction, **returns
    the direction it observed** rather than discarding it, and **refuses** a payload
    that is neither ascending nor descending — because a reversed series still
    analyses, confidently and about the wrong direction, and inferring intent from a
    broken sequence is the guess that hides a caller's bug behind a working result.
  - **The forming-bar freeze, decided by time.** `bar.time + period <= now`, because
    `Bar.time` is the *open* time. "Drop the last row" is wrong at every bar boundary
    and silently wrong across a weekend or a session break, and both failures look
    like a working adapter until a comparison fails for no visible reason. Three
    tests pin it, two of them the cases the positional shortcut gets wrong: a call
    with nothing forming keeps **every** bar, and a series whose newest bar closed
    hours ago does not shrink.
  - **An all-forming series freezes to empty**, rather than keeping the newest "just
    in case". The engine already has an honest answer for an empty series — `NO_BARS`,
    as a reason rather than as an empty structure list.
  - **The clock is the terminal's, not the local one.** See the measured 3.1-hour
    skew below. `closed_bars()` reads the server clock by default; a caller-supplied
    `now` takes precedence; and `FreezeReport.clock` records which was used so a
    degradation to the local clock is visible rather than silent.
  - **A calendar month is refused.** `MN1` has no fixed period, so `period_seconds()`
    raises `TimeframeUnsupported` rather than assuming 30 days — a freeze wrong on two
    days of every month is a look-ahead that *looks like a correct answer*. An unknown
    constant is refused for the same reason.
  - **Four error types rather than one**, because the recovery differs: a dead
    terminal, a misspelt symbol, an empty history and an unmeasurable timeframe are
    four different problems. They share a base so a caller who cannot act on the
    difference has one handler.
  - **`AnalysisSession` closes the Phase 19 finding.** It calls
    `track_fading_measured_moves`, so the lifecycle a live consumer could not see —
    `PROJECTED` with `age 0` forever, for a projection the market had already reached
    and rejected — is now reachable. It **re-derives** rather than accumulating, and
    that is the load-bearing decision: an incremental state machine would break
    `RPC-1`, since a session that has seen bars 21..40 and then answers for bar 20
    holds state derived from bars the caller declared unavailable.
  - **The pipeline still reports `PROJECTED`**, deliberately. The registry is
    stateless and that is its contract; the session adds a caller rather than editing
    it. `SessionResult.fade_source` says which reading is which, and a test asserts
    **both**, so the change cannot quietly become "the pipeline now says something
    else".
  - `on_feed()` takes `now` and `period_seconds` rather than leaving them to the
    feed's defaults, so a caller replaying recorded data is not at the mercy of the
    live clock.
- `changed_since_previous()` answers `RPC-15`'s question directly — what moved
  between two bars, and what held still — and reports `first_call` rather than an
  empty change set that would read as "nothing moved".
- **Three defects found by running the adapter against a real terminal, and the
  finding recorded in `MT5_ADAPTER.md` §10 because the shape of it matters more
  than the individual bugs: a fake encodes the author's assumptions.** The original
  54 tests all passed; all three defects would have failed on the first live call.
  - **`copy_rates` does not exist** in the Python bindings. Only
    `copy_rates_from_pos`, `copy_rates_from` and `copy_rates_range` are provided.
    The adapter called `copy_rates` and would have raised `AttributeError`; the
    fake implemented it, because the MQL5 documentation names it.
  - **The payload is oldest-first, not newest-first.** The bindings ignore MQL5's
    `ArraySetAsSeries` convention, and all three `copy_rates_*` entry points return
    ascending rows — measured on M1, M5 and M15. The original strict check
    *refused* anything not newest-first and would therefore have raised on every
    real payload. The property that matters is **monotonicity, not direction**:
    both single directions are legitimate conventions and both are now normalised,
    with the direction observed **returned** rather than discarded so a silent flip
    cannot hide. A payload that is neither ascending nor descending is still
    refused.
  - **The server clock ran 3.099 hours ahead of the local one** (`+11157s`, Alpari
    MT5 build 6230). Over a 50-bar M15 window the local clock treated 14 bars as
    still forming when only 1 was, discarding 13 bars of real history. The failure
    is **directional**: a local clock *behind* the server over-freezes, and one
    *ahead* would keep a still-forming bar — a look-ahead. So `closed_bars()` now
    reads the terminal's clock, and `FreezeReport.clock` records which was used
    (`SERVER` / `CALLER` / `LOCAL`) so a degradation is visible.
  - `tests/integration/test_phase21_live_mt5.py` — 8 read-only checks against a
    real terminal, **skipped** when none is reachable, covering exactly what a fake
    cannot: which functions exist, which direction arrives, whether both
    conventions agree, and whether `RPC-2` holds on a real series. A skip is not a
    pass, and every skip names its reason.
  - **The `RPC-2` check was itself wrong on two live runs, and that is recorded
    too.** It searched the serialised result for the forming bar's high as a
    *substring*, so a forming high of `1.13640` matched `1.13645`, a closed bar's
    low. Making it numeric was necessary and not sufficient: it fired again when
    the forming bar's high of `1.13654` turned out to be *also* a closed bar's
    high. A leak means a price that exists **only** on the forming bar, so the
    check now subtracts the closed bars' own extremes and skips when the forming
    bar's extremes are entirely shared — a run on which the two cases are
    indistinguishable, and claiming otherwise would be the same error in a third
    disguise. A false-positive test is worse than no test, because it teaches you
    to ignore the suite.
- `docs/algorithms/MT5_ADAPTER.md` is a **required** CI document, and it states in
  §5 that `mql5/` does not exist and why.
- **Phase 20** — `tests/parity/`: the Python/MQL5 parity harness, and
  `docs/PYTHON_MQL5_PARITY.md`. A **canonical vector** of 33 declared fields
  across eight groups — analysed bar, ATR, market state, swings with both their
  bar index and their confirmation index, detected setups, plan geometry with
  the basis of every level, and the decision with its reason code — that an MQL5
  port must reproduce to be considered the same engine.
- `tests/parity/cases/`: three hand-drawn cases, each stating the divergence it
  exists to catch. A rising trend with three pushes, a range whose highs recur
  inside every 5-bar window then an upside break, and a bear trend whose rally
  returns toward the origin.
- **A per-field comparison policy rather than one epsilon.** `EXACT_INT`,
  `EXACT_CODE` and `EXACT_BOOL` are compared with `==`; only `NUMBER` carries
  `RELATIVE_TOLERANCE = 1e-9`, with `ABSOLUTE_FLOOR` for references near zero. An
  index differing by one is a repaint bug and a price differing in the fifteenth
  digit is a summation order, and treating them alike would have hidden both. The
  worst observed deviation is reported for every case, pass or fail.
- `docs/PYTHON_MQL5_PARITY.md` — the specification, including the two things the
  scope excludes (prose, and the constant `is_probability` / `is_recommendation`
  markers), the one field that is not closed-bar stable and why it is in scope
  anyway, and what Phase 21 owes.
- **Phase 11** — `src/albrooks/setups/fading_measured_move.py`: the Fading
  Measured Move lifecycle, `PROJECTED -> POTENTIAL -> DEVELOPING -> CONFIRMED
  -> COMPLETED` with `-> INVALIDATED` from any state. Consumes
  `MeasuredMoveProjection` and never the reverse.
- `docs/algorithms/FADING_MEASURED_MOVE.md` — the FM specification, including
  the transition order and its justification.
- `AnalyzerConfig` gained the FM lifecycle keys: `fm_max_bars_forward`,
  `fm_min_body`, `fm_close_pct`, `fm_max_wick`, `fm_require_engulf`,
  `fm_max_active` and `fm_recent_swings`. The `fm_*` flags that already existed
  were previously declared but consumed by nothing.
- `FadingSetup.touched` and `.is_active` distinguish "approached the target" from
  "reached it", and "still progressing" from "finished". A projection may also
  step *backwards* from `DEVELOPING` to `POTENTIAL` when price leaves the target
  zone, which is why the lifecycle reports where price is rather than the
  furthest point it reached.
- Repository-level documentation: `README.md`, `README_FA.md`, `SOURCES.md`,
  `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`, `CHANGELOG.md`.
- `docs/algorithms/MEASURED_MOVES.md` — measured-move specification, including
  the enforced no-lookahead contract.
- `mypy` added to development dependencies and CI.
- `src/albrooks/setups/measured_move_types.py` — `MeasuredMoveLeg`,
  `MeasuredMoveOrigin` and `MeasuredMoveEvidence`, split out so Phase 11 can
  depend on the data model without depending on the projection algorithms.
- `MeasuredMoveProjection` now reports `reference_leg`, `origin`, `evidence` and
  `confidence` for all five projection families. `confidence` is exactly the mean
  of the stored evidence weights, so the scalar is always reproducible from its
  own evidence. It is **not** a probability or a win rate; nothing here has been
  calibrated against outcomes.
- **`Analyzer.analyze()` is wired** (Phase 1 pipeline). It now runs bar features,
  ATR, swings, legs, pivots, market state, trend metrics, channels, measured
  moves, H1/H2 and L1/L2 pullbacks, breakouts, and both reversal directions,
  and returns real analysis instead of a hard-coded placeholder.
- `Analyzer.analyze(..., last_closed=N)` analyses **as of** bar `N`. Everything
  derived is read from bars `0..N` only, and the value used is reported in
  `AnalysisResult.last_closed_bar`.
- `AnalysisResult` gained the specification's `trends`, `channels`, `pullbacks`,
  `breakouts`, `reversals` and `evidence` fields, plus `last_closed_bar` and a
  `layers` map recording which layers actually ran.
- `AnalysisResult.unimplemented_layers` lists the layers a result makes no claim
  about, read from `layers` rather than inferred from an empty list — "nothing
  found" and "not implemented" are different statements.

### Known limitations
- **Phase 21 is half delivered, and the missing half needs *writing*, not hardware.**

  **Correction.** This entry previously said the MQL5 port was "blocked on MetaEditor".
  That was wrong, and it was never checked. MetaEditor 5.0.0.6230 ships beside the
  terminal and compiles in about a second, and the Strategy Tester runs headlessly.
  The whole loop was verified end to end on a throwaway EA: compile, run, write a
  file, read it back from Python. The one non-obvious requirement is that `Login`
  and `Server` must appear in **both** `[Common]` (so the terminal itself logs in)
  and `[Tester]` (so the local agent authorises); with them only in `[Common]` the
  agent fails with `tester agent authorization error`.

  Recorded rather than quietly fixed, because an *unchecked* claim of a hardware
  blocker is a roadmap entry nobody re-examines. It is the same failure as the
  fake-driven adapter tests one level up: a claim about the world that nothing
  checked. The adapter,
  the freeze and the stateful session are built and tested. `mql5/Include/AlBrooks/`
  is **not**, and cannot be from a machine with neither MetaEditor nor a MetaTrader
  terminal — an MQL5 port of eleven detectors, the market-state classifier, the plan
  geometry and the decision engine can only be *validated* by compiling and running
  it. Shipping never-compiled MQL5, or hand-writing a `"producer": "mql5"` sidecar
  to turn the harness green, would be worse than the honest status. The second would
  in particular be the exact dishonesty the Phase 20 harness exists to catch.
- **No MQL5 parity has been established, and the harness cannot be read as having
  tried.** `tests/parity/mql5/` is empty, all three cases name no sidecar, and a
  run reports `UNVERIFIED` — a status distinct from both a pass and a failure,
  because nothing was compared. Zero of three cases have been compared and **no
  parity claim is made anywhere in this project.** The Phase 21 work changes nothing
  here, and `tests/unit/test_phase21_adapter.py` asserts the empty state so the
  documentation has to move in the same change that fills the harness.
- **The clock is the terminal's, and reading it is an approximation.** The bindings
  have no `TimeCurrent()`, so `server_time()` is the time of the last *tick*. On a
  quiet symbol that may be older than now, which makes the freeze conservative (fewer
  bars treated as closed) — the safe direction, but still an approximation. The
  3.1-hour skew measured on Alpari is a property of *that broker*, not a constant,
  which is why the adapter measures the clock rather than hard-coding an offset.
- **The live suite covers one broker and one symbol.** Alpari MT5 build 6230,
  `MetaTrader5` 5.0.6180, EURUSD on M1/M5/M15/H1. A different venue may differ, and
  the three defects in §10 are exactly the kind that hide until a real API disagrees
  with the assumed one.
- **A skip in the live suite is not a pass.** It means the file did not run. That is
  why every skip names its reason including the exact `MetaTrader5` error: a suite
  that skips silently is indistinguishable from one that passes.
- **`WINDOW_FLOOR = 60` is a floor, not a recommendation.** It is derived from the
  default config (`atr_period + 4 * swing_k + state_lookback`, rounded up), so a
  caller who changes those keys and not the floor gets a stale number. A short window
  is reported as `MT5_WINDOW_BELOW_FLOOR` rather than refused, and the engine's own
  `warnings` describe what degraded.
- **A monthly chart needs an explicit `period_seconds`.** `MN1` is refused rather
  than assumed at 30 days, which is correct but does mean the adapter cannot serve a
  monthly series unattended.
- Three refusals keep that state from being mistaken for a result. A sidecar
  whose `producer` is not `mql5` is not counted, which is what makes the
  committed Python-produced vectors in `tests/parity/reference/` safe to keep; a
  sidecar covering a strict subset of the scope is refused; and one written
  against a different schema is refused, because two sides implementing different
  contracts can agree on everything they both check.
- **`AGREED` requires every case to have been compared.** Half a case set is not
  half a pass — a boolean cannot express "these two agreed and that one was never
  run" — so a partially filled run is `FAILED`. `UNVERIFIED` has its own exit
  code (2), and CI's `--allow-unverified` is asserted by a test to exist exactly
  while the shipped state is `UNVERIFIED`, so Phase 21 cannot remove one without
  the other.
- **List order is not compared.** An MQL5 registry is not this registry and
  `SETUP_ENGINE.md` §5 is explicit that registration order is not a ranking, so a
  port whose findings arrive in a different order would pass. List *count* is
  compared, which is the difference that changes behaviour.
- **`bars_processed` is the one field in scope that is not closed-bar stable.** It
  counts the bars the run was *given*, so appending future bars moves it. It is
  left in because the obligation it imposes is an input condition rather than a
  behavioural claim — the port must be fed the same number of bars — and a port
  that silently truncated its series is exactly what it exists to catch.
- **A tolerance is not a proof of identical arithmetic.** `1e-9` is a statement
  about where two implementations may legitimately differ in summation order, and
  it is a weak one. The rest of the scope is compared exactly.
- The two implementations' first comparison is expected to **fail**. A port's ATR
  seed, its series direction, its swing tie-break and its null convention are four
  easy places to diverge, which is why each is in the scope, and the disagreements
  should be recorded rather than tuned away.

### Changed
- `docs/algorithms/MEASURED_MOVE.md` renamed to `MEASURED_MOVES.md` to match the
  documented spec filename.
- `AnalyzerConfig` gained the measured-move family flags
  (`enable_range_mm`, `enable_channel_mm`, `enable_gap_mm`,
  `enable_inverse_mm`, `range_lookback`, `min_gap_atr`).
- The measured-move families are now assembled by one `_build_projection` helper,
  so a new family cannot skip the evidence model by accident. The `CHANNEL`
  shallow-pullback bound is the named constant `CHANNEL_MIN_DEPTH` rather than a
  literal repeated in the gate and the evidence band.
- The pullback and reversal layers report **both** directions rather than one
  winner, because ranking them is a decision. *The decision layer did not exist
  when this was written; it landed in Phase 15, and `decision.decide()` is now
  the single place the comparison happens.*

### Fixed
- A "distance to target" evidence factor was removed during review. In all five
  families the target is exactly one measured range from the reference price, so
  the factor was `mm_range` restated against a different constant — two names for
  one number, whose apparent independence from the scale factor was an artefact of
  the arithmetic. A test pins the relationship.
- **`bar_features` leaked future bars.** `analyze_series` has no `last_closed` of
  its own and always runs to the end of the series it is given, so analysing bar
  39 of 60 returned per-bar features for bars 40-59 — future prices inside a
  result the architecture promises is closed-bar only. The pipeline now slices to
  the analysed window. Two regression tests cover it, including one that checks
  the prices themselves rather than the indices.
- **`Bar.from_dict` rejected the short `o/h/l/c` keys** that every detector's own
  `_get_ohlc` and the README both accept, so `Analyzer.analyze()` — the
  documented entry point — refused input the rest of the engine read happily. A
  bar missing a price field now raises a `KeyError` naming the field and listing
  the keys supplied, instead of a bare one.

### Added
- **Phase 12** — `src/albrooks/setups/base.py` and `registry.py`: a
  `SetupContext`, a one-method `SetupDetector` protocol, a thin `SetupFinding`
  wrapper, an `adapt()` bridge, and a `SetupRegistry` that runs whichever
  detectors are registered.
- The eleven detectors from Phases 2-11 keep the signatures their own phases
  defined. `find_major_double_top` still reads only swings and never sees a bar,
  and the two list-returning detectors are still adapted rather than rewritten.
- `SetupRegistry.run()` distinguishes a detector that **ran and found nothing**
  (`executed`) from one that **could not be measured** (`skipped`, with
  `NO_ATR` / `NO_CLOSED_BARS`). Every detector gates on ATR multiples, so without
  that split a volatility-free series would return a clean, plausible "no
  structure here" for a market that was never examined.
- A detector that raises is recorded as a `DetectorFailure` and the run
  continues, rather than one broken detector taking down the ten beside it.
  `strict=True` re-raises for callers who would rather stop than receive a
  partial answer.
- `docs/algorithms/SETUP_ENGINE.md` — the setup-engine specification, including
  why the registry deliberately does not rank.
- `tests/unit/test_phase12_setup_registry.py` — 65 tests pinning the properties
  `ARCHITECTURE.md` §9 depends on, rather than the behaviour of any one detector.
  The claim that a detector is addable without editing the analyzer is asserted
  as a test (`test_a_detector_can_be_replaced_without_editing_the_analyzer`)
  instead of left as a comment, and the §6 closed-bar invariant is re-asserted
  through the registry as well as the pipeline.

### Changed
- The `present=` hook on the fading-measured-move adapter is now documented as a
  statement of intent rather than a fix. Writing the Phase 12 tests showed the
  claim in its docstring was wrong: the default rule is
  `payload.get("found", True)`, and `FadingSetup.to_dict()` has no `found` key
  at all, so the default already treats a terminal fade as a finding. The hook
  is kept — it prevents a future `found` field from silently dropping terminal
  fades — and a test now pins the default's behaviour so a future change to it
  has to be made deliberately. The inaccurate claim in the `base.py` module
  docstring was corrected to match.
- The first version of the registry's closed-bar test was **vacuous** and is
  recorded here because it is the kind of gap this project's own testing policy
  is meant to catch. It compared two near-empty finding lists built from a
  perfectly regular zigzag series, and still passed with lookahead deliberately
  injected into the measured-move adapter. The fixture is now a
  rally/pullback/rally series cut at bar 59 of 80, where the measured-move and
  fading-measured-move detectors both actually fire, and the injected lookahead
  is caught. `test_the_closed_bar_test_is_not_vacuous` asserts the fixture
  produces those findings, so the comparison cannot quietly become empty again.

### Fixed
- `pyproject.toml` declared the licence the deprecated way
  (`license = {file = "LICENSE"}` plus the `License :: OSI Approved :: MIT
  License` trove classifier). Both are removed in favour of the SPDX
  `license = "MIT"` string and `license-files = ["LICENSE"]`, and the build
  requirement is raised to `setuptools>=77.0`, which is what understands that
  spelling. This was verified by running the build rather than by reading the
  warning: the previous form emitted a deprecation notice with a hard deadline of
  **2027-Feb-18**, after which the package would no longer build at all. The
  wheel now reports `License-Expression: MIT` and bundles the `LICENSE` file.

### Added
- **Phase 13** — `src/albrooks/evaluation/evidence.py` and `scoring.py`: one
  `EvidenceFactor` shape for the five evidence vocabularies the engine speaks
  (market state, measured move, reversal, pullback, breakout), plus a source-
  balanced aggregator and coarse banding.
- `EvidenceFactor.basis` records **why** a weight is the number it is:
  `MEASURED` (computed from data), `LIFECYCLE` (a discrete state-machine
  position) or `ASSERTED` (present, no magnitude). A pullback's `CONFIRMED` is
  not "0.75 confirmed", and an unquantified observation is not recorded as
  `0.0` — which would read as "measured, and came out nil" and silently drag an
  aggregate down. `ASSERTED` factors take a documented `UNQUANTIFIED_WEIGHT`
  and are flagged, and a bundle reports `quantified_share` so a "score" that was
  really a list of presence flags cannot pass unnoticed.
- `EvidenceScore` averages **within each source first**, then across sources, so
  each contributing source gets an equal say. A flat mean would let the chattier
  source dominate on factor count alone: the reversal adapter emits one factor
  per satisfied leg while the pullback adapter emits exactly one, so a four-leg
  reversal would outweigh a confirmed pullback arithmetically and for no
  substantive reason. The per-source means are retained in `by_source`.
- `AnalyzerConfig` gained `evidence_strong_band` and `evidence_moderate_band`.
  ARCHITECTURE.md §11 requires every heuristic threshold to be configurable
  rather than a literal inside a detector, and the two new bands had nowhere
  else to live.
- `docs/algorithms/EVIDENCE_MODEL.md` — the evidence-model specification,
  including what the aggregate is **not**.

### Changed
- Per `docs/architecture/CONCEPT_TAXONOMY.md` §6, the aggregate is called an
  **evidence score** rather than a confidence, and `EvidenceScore.to_dict()`
  carries `"is_probability": false` so a downstream consumer is told what the
  number is rather than left to know. Nothing in this project has been
  calibrated against outcomes, so no rate can be derived from it.

### Documentation
- `ROADMAP.md` gained a **Deliberately Not Built** section. The roadmap already
  recorded what is done and what remains, but the third category — what is absent
  *on purpose* — existed only as scattered asides in individual spec files, which
  is a poor fit for a project whose premise is honest self-reporting. Each entry
  now states the thing, the reason, and what would have to change.
- Recorded there, every claim verified against the source rather than assumed. Four
  of them have since been **closed** and are annotated below; the rest still stand.
  - The setup registry and `evaluation.compare()` do not rank competing setups.
    **Still true**, and `decision.decide()` is now the single place a ranking happens.
  - No score in this project is a probability. **Still true.**
  - The pipeline never infers a trade (`NO_TRADE` /
    `DECISION_ENGINE_NOT_IMPLEMENTED`). **Closed** (Phase 15) — the pipeline
    answers `BUY` / `SELL` / `WAIT` / `NO_TRADE`, and `NO_TRADE` is now reachable
    only via `enable_decision=False` / `DECISION_DISABLED` or a degenerate input.
  - The six `AnalyzerConfig` keys consumed by nothing — `enable_decision`,
    `min_score`, `min_rr`, `max_late_atr`, `conflict_ppts`,
    `max_failed_attempts`. **Closed** (Phase 15) — all six are read, and each is
    asserted to change a decision outcome.
  - `engine.state.NOT_IMPLEMENTED` is defined and never used; the job it
    describes is actually done by the `layers` map and `unimplemented_layers`.
    **Still unused**, and the ROADMAP records what would change it.
  - `examples/` is empty and untracked, so it does not survive a fresh clone.
    **Corrected**: there is no `examples/` directory at all, so nothing of ours is
    untracked. Phase 22 owns `examples/llm_analysis.py`, and the 0.1.0 known-gap
    entry for missing examples is still open.
  - `decision/`, `trade/`, `adapters/` and `serialization/` hold only empty
    `__init__.py` placeholders. **Partly closed** — `decision/` and `trade/` are
    populated and on the live pipeline path (Phases 14-15). `adapters/` and
    `serialization/` remain empty placeholders for Phases 21 and 22.
- `README.md` gained a *What is deliberately not built* summary, and its
  Configuration section now warns that not every key is wired yet. Both link to
  the ROADMAP section.

### Known limitations
- `INVALIDATED` pullbacks and `FAILED` breakouts are **excluded** by their
  adapters rather than scored low. "Scored badly" and "not a candidate" are
  different statements, and folding a terminal negative in as a small weight
  would collapse them.
- The pullback adapter's lifecycle values (`CANDIDATE` 1/3, `PROVISIONAL` 2/3,
  `CONFIRMED` 1.0) are evenly spaced for stability only. The gaps are **not**
  meaningful: a `PROVISIONAL` pullback is not "twice as provisional" as a
  `CANDIDATE` one.
- The market-state adapter decides whether a factor is measured by looking for a
  trailing number in its detail string. That works for the current three codes
  and would need revisiting if the engine began emitting mid-sentence numbers,
  which is why the parser reads only the last token.
- The evidence model **is** consumed by `Analyzer.analyze()`. *Closed (Phase 16).*
  The limitation recorded here was that rewiring it would have altered output that
  `tests/unit/test_engine_pipeline.py` pinned; it is wired, and the pipeline's
  `evidence` list is now the evidence model's own.
- `AnalyzerConfig.min_score` gates the `EVIDENCE_TOO_WEAK` veto. *Closed
  (Phase 15).* It is no longer decorative, and a test asserts that moving it
  changes which candidates survive.
- The FM exhaustion gate binds more loosely than the specification's wording
  suggests. A bar touching a measured-move target is by construction the extreme
  of the recent range, so the `overshoot` exhaustion condition is almost always
  satisfied on the touching bar, and `POTENTIAL -> DEVELOPING` nearly always
  happens there. The gate is kept as specified; the interaction is documented in
  `docs/algorithms/FADING_MEASURED_MOVE.md` §5.2 and pinned by a test, because
  removing the gate would otherwise not fail any test.
- `Analyzer.analyze()` reads the setup registry. *Closed (Phase 16).* Recorded
  here previously as outstanding work; it is done, and a detector can now be added
  without editing the analyzer.
- `DEFAULT_REGISTRY` is a process-wide mutable global. `build_default_registry()`
  is preferred in library code and tests, because a shared mutable global makes
  test order matter. A test pins that the two are independent.

### Added
- **Phase 14** — `src/albrooks/trade/plan.py`: a platform-independent
  `TradePlan` — entry, stop, target, reward:risk, an invalidation sentence and
  management notes — and one builder that derives them from a setup payload.
- **Every level carries a basis.** This is the phase's load-bearing idea, and it
  is Phase 13's `EvidenceFactor.basis` applied to prices. A stop at `101.20` means
  something different depending on whether it came from a pullback's low, a
  broken reference, a pattern's extreme, a confirmed swing, or an ATR multiple,
  so `entry_basis` / `stop_basis` / `target_basis` say which. A level invented
  from volatility is recorded as `ATR_FALLBACK`, raises
  `VOLATILITY_FALLBACK_STOP` / `VOLATILITY_FALLBACK_TARGET`, and leaves
  `has_structural_stop` False — a reader can never mistake a 1-ATR default for a
  swing low the market made.
- `issues` holds only statements that are false about the arithmetic
  (`STOP_NOT_PROTECTIVE`, `TARGET_NOT_AHEAD`, `RISK_NOT_POSITIVE`, `NO_ATR`,
  `NO_DIRECTION`, `*_UNDEFINED`). `warnings` holds everything noticed and
  deliberately not acted on, because **gating on merit is the decision engine's
  job**: `plan_max_stop_atr` produces a `STOP_WIDE` warning on a plan that is
  still returned and still `is_valid`.
- A setup in a terminal negative state (a `FAILED` breakout, an `INVALIDATED`
  lifecycle) raises `TERMINAL_SETUP_STATE` and is still planned. Its geometry is
  coherent arithmetic, and hiding it would remove the reader's chance to ask
  whether it deserves a plan.
- `SetupAnatomy` is a row of **data** saying where a family's geometry lives in
  its payload, and `build_trade_plan()` is the single algorithm that reads it.
  The five families record prices in incompatible places — a pullback carries
  `stop_price`, a measured move nests its origin under `origin.price`, a fading
  setup's trade direction is `fade_direction` rather than `direction`, and a
  reversal carries no prices at all — so five builders would have duplicated the
  derivation five times, against `CONTRIBUTING.md` rule 5. Adding a family is a
  table row, holding `ARCHITECTURE.md` §9's one-change rule at this layer too.
- A fade reads `fade_direction` **before** `direction`, because
  `FadingSetup.direction` is the *projection's*. Reading it as the trade
  direction produces a plan in the direction of the move being faded, which is
  the easiest way to be wrong in this engine.
- A double top/bottom's stop is the **adverse extreme** of `price1` and `price2`
  (the minimum for a long, the maximum for a short) rather than the first of
  them, which on a bar-order change would put the stop inside the pattern.
- `AnalyzerConfig` gained the `plan_*` block: `plan_stop_buffer_atr`,
  `plan_fallback_stop_atr`, `plan_fallback_target_atr` and `plan_max_stop_atr`.
  ARCHITECTURE.md §11 requires every threshold to be configurable rather than a
  literal inside a detector, and these had nowhere else to live.
- `docs/algorithms/TRADE_PLAN.md` — the trade-plan specification, including what
  a plan is **not** and the exact boundary values of every gate.
- `tests/unit/test_phase14_trade_plan.py` — 56 tests. Every threshold is pinned
  at its **exact** value and on both sides of it, the no-lookahead invariant is
  re-asserted through the swing path (a swing confirmed *after* the plan's bar
  must not set its stop), and `test_the_no_lookahead_fixture_is_not_vacuous`
  guards the comparison from becoming empty.

### Fixed
- A setup payload with **no `direction` field at all** produced a *short* plan.
  The direction reader went through a helper whose "missing" sentinel is `-1`,
  and `-1` is a direction. A missing or non-numeric direction is now `0`, which
  reports `NO_DIRECTION` and derives no levels at all. Found by the Phase 14
  test suite; it would have shipped a plausible-looking number for every setup
  that does not record a direction.
- The volatility **fallback stop** was computed as `entry - stop_buffer`, making
  it `plan_stop_buffer_atr` (0.25 ATR) wide instead of
  `plan_fallback_stop_atr` (1.0 ATR) wide. The fallback is a distance, not a
  buffer, and the two were being conflated.

### Added
- **Phase 15** — `src/albrooks/decision/engine.py` and `veto.py`: a transparent
  decision pipeline returning `BUY` / `SELL` / `WAIT` / `NO_TRADE` with a stable
  reason code, the full explanation, every gate that fired, and the criteria that
  chose the candidate.
- This is the one layer allowed to compare competing setups, which
  `ROADMAP.md` has said all along is where the comparison belongs. It sorts
  eligible candidates by `(-evidence_value, -reward_to_risk, candidate_id)` and
  **echoes that list in `ranking_basis` on every decision**, so a run over the same
  findings always agrees with itself and a reader never has to open a file to know
  why one plan won. `BUY` means "of the plans that passed every gate, this one had
  the most evidence by those criteria" — there is no `confidence` field anywhere
  in this project and `Decision.to_dict()` carries `is_probability: false`.
- `NO_TRADE` and `WAIT` are kept distinct. `NO_TRADE` means the engine declines to
  answer (disabled, no volatility reference, or nothing found) and each has its own
  reason code; `WAIT` means a candidate existed and a stated condition was not met.
  Collapsing them would make an empty result read as a judgement.
- **Nine gates, eight blocking and one advisory.** `NO_DIRECTION`,
  `INVALID_GEOMETRY`, `TERMINAL_SETUP`, `NO_ATR`, `EVIDENCE_TOO_WEAK` (`min_score`),
  `RISK_REWARD_TOO_LOW` (`min_rr`), `TRADE_IS_LATE` (`max_late_atr`),
  `TOO_MANY_FAILED_ATTEMPTS` (`max_failed_attempts`), and the non-blocking
  `VOLATILITY_STOP_ONLY`.
- **No gate short-circuits.** A candidate failing four reports four, because a
  reader fixing one condition should not have to re-run to discover the next. And
  every `Veto.detail` names both numbers it compared — a veto that only said
  `EVIDENCE_TOO_WEAK` would be unfalsifiable. An `ALL_CANDIDATES_VETOED` decision
  keeps the per-candidate veto list, not just a count, and its explanation names the
  four config keys to turn.
- `veto.py` exists as a separate module so that a veto — a statement about a
  *single* candidate — cannot mention another candidate, and a veto list can never
  become a hidden ranking.
- `TradeCandidate` carries a plan, the bundle of evidence behind it, and the score
  derived from that bundle **together**, with the score computed once at
  construction so the number a gate reads and the number the decision reports
  cannot be two different calculations of the same bundle.
- `bundle_for()` maps a family to its Phase 13 adapter and adds market-state
  evidence to **every** bundle: context is part of what backs a candidate, and a
  bundle that omitted it would score a pullback in a strong trend identically to
  one in a tight range.
- `docs/algorithms/DECISION_ENGINE.md` — the specification, including the gates,
  the ranking criteria, and §5's account of what `max_failed_attempts` actually
  counts.
- `tests/unit/test_phase15_decision.py`, plus tests added to
  `test_phase13_evidence.py`. Every threshold is pinned at its **exact** value and
  on both sides of it, the reward:risk tie-break is isolated from the name
  tie-break by giving the better candidate the later id, and the closed-bar
  invariant is re-asserted through the lateness gate — the gate most likely to
  break it.

### Changed
- **`Analyzer.analyze()` now reports a decision and the plans behind it.** The
  setups a run found are planned by `albrooks.trade.plan`, and gated and ranked by
  `albrooks.decision.decide()`. `layers["trade_plans"]` and `layers["decision"]`
  are `True`, so `unimplemented_layers` is **empty** for a normal analysis — which
  is what that field has always existed to say. On degenerate input it is still
  every layer.
- `tests/unit/test_engine_pipeline.py` updated to the new truth. The assertions that
  pinned `layers["trade_plans"] is False` and
  `unimplemented_layers == {"trade_plans", "decision"}` were correct when written
  and are wrong now; leaving them would have made the field lie. Two new tests
  cover the trade-plan and decision output, and one covers
  `enable_decision=False` withholding the decision while leaving the plans alone.
- The six `AnalyzerConfig` keys declared in Phase 1 are finally read, and each one
  is now asserted by a test to change an outcome — which is the only way they
  cannot silently become decorative again. The README and `ROADMAP.md` sections
  that warned they had no effect have been replaced with what they now do.
- The plan layer plans only the setups the pipeline already found, so wiring it in
  cannot introduce a new lookahead surface.
- `NOTE_PLAN_IS_NOT_A_RECOMMENDATION` in `trade/plan.py` no longer says the
  question belongs to "Phase 15" — it belongs to the decision layer, which now
  exists.

### Fixed
- **`AnalyzerConfig.min_score` was declared as `40.0` on a scale that does not
  exist.** The Phase 13 evidence score is 0..1, so the moment the key was read it
  rejected **every** candidate, including a perfect one, and the decision layer
  would have answered `WAIT` / `ALL_CANDIDATES_VETOED` on every input forever. The
  default is now `0.40`, aligned with `evidence_moderate_band`. The key was
  documented as unwired for three phases precisely so nobody was misled by it
  meanwhile, but the ROADMAP's table carried the wrong number until this phase.
- `from_measured_move()` and `from_reversal()` could only read domain models, not
  their `to_dict()` payloads. Every detector's public path is `to_dict()`: the
  registry passes findings around as plain dicts and `analyze()` reports them as
  dicts, so the decision layer could not reach the measured-move and reversal
  evidence at all. Both now read either, preferring the object, and a test asserts
  a payload and its model normalise identically.

### Added
- **Phase 16** — `src/albrooks/engine/pipeline.py`: `analyze_multi_timeframe()`
  aligns two series in time, derives a higher-timeframe bias, and withholds a
  lower-timeframe decision that runs against it. `docs/algorithms/MULTI_TIMEFRAME.md`.
- **Alignment works in close times.** `Bar.time` is the bar's *open* time, so a
  high bar is usable at low bar `i` only once it has closed:
  `htf.time + htf_step <= ltf.time[i] + ltf_step`, i.e.
  `k = floor((i + 1) / ratio) - 1`. That is deliberately **not** `i // ratio` — a
  low bar closing at the same instant as a high bar's close is *inside* that high
  bar. A test makes the forming high bar extreme and asserts the bias does not
  move, which is the specific mistake a naive `htf.time < ltf.time` would make.
- The bar step is the **mode** of the timestamp gaps, not the mean, so a single
  session break cannot become the bar period. Nothing parses a timeframe string:
  `ratio` is the caller's, cross-checked against the timestamps and reported as
  `TIMEFRAME_RATIO_MISMATCH` if it disagrees — a mis-parsed timeframe is a silent
  misalignment, which is the worst kind.
- Five alignment diagnostics, and the two that stop the alignment
  (`MISSING_TIMESTAMPS`, `NON_MONOTONIC_TIME`) are reported rather than papered
  over. A series of bars carrying no `time` is all `0.0` defaults, and guessing a
  step for it would produce a bias that reads as a neutral market.
- The bias is a **veto input, not a signal**. `AGAINST_HIGHER_TIMEFRAME`
  *withholds* a decision and never inverts one: knowing an M15 long disagrees with
  an H1 bear is not knowing the long is a short. A directional read needs the
  higher proxy share to reach `htf_min_strength` (default `0.60`, against a clean
  trend's `0.67`), so a range or a chop cannot manufacture a conflict —
  `htf_opposition_veto=False` reports the bias without gating on it.
- `HTFBias.reason` keeps four "no bias" cases apart — `HTF_ALIGNED`,
  `HTF_NOT_CLASSIFIED`, `HTF_NOT_ALIGNED`, `HTF_NOT_ALIGNED_IN_TIME` — so a
  timestamps problem can never read as a neutral market.
- `AnalysisResult` gained `findings` (every setup detector finding, in
  registration order) and `detectors` (`executed` / `skipped` / `failed`).
- `AnalyzerConfig` gained `htf_min_strength`, `htf_opposition_veto` and
  `htf_report_unclassified`.
- `docs/algorithms/MULTI_TIMEFRAME.md`, promoted to a required document in CI, and
  `tests/unit/test_phase16_multi_timeframe.py` — 38 tests including the closed-bar
  alignment, both sides of   `htf_min_strength`, and the invariant re-asserted
  across **two** series.
- **Phase 18** — `src/albrooks/backtest/events.py`: `replay()` walks a series one
  closed bar at a time and records what the path after each decision did — which
  level came first, how many bars it took, and the maximum favourable and adverse
  excursion in price units and in ATR multiples. `docs/algorithms/BACKTESTING.md`.
- **Two outcomes are things that happened, so they are not tidied away.**
  `AMBIGUOUS` is a bar whose high passed the target while its low passed the stop,
  which OHLC cannot order; `INVALID_ENTRY` is a fill that arrived already through
  the stop, so the trade never existed. Both are recorded on the event, both are
  counted, and neither is dropped from the sample.
- **Ambiguity is resolved at reporting time, never on the event.** The event keeps
  `AMBIGUOUS`; `AmbiguityPolicy` maps it to `STOP_FIRST` (the pessimistic default),
  `TARGET_FIRST` or `EXCLUDE` when the counts are taken. The raw fact therefore
  survives whatever policy reads it, and a test asserts the policy does not
  quietly reclassify the rest of the sample.
- **The fill is a named assumption.** `FillPolicy.NEXT_OPEN` is the default — the
  first price that existed once a closed-bar decision could be acted on.
  `SIGNAL_CLOSE` fills at a price the engine held when it could not yet act, and is
  available for comparison. Events carry both `plan_entry` and `entry` so the two
  stay distinguishable.
- **`ConflictPolicy` has three genuinely different behaviours.** `SKIP` is the
  default and takes at most one position at a time; `CLOSE_AND_REVERSE` cuts the
  replaced position's path at the new fill and records
  `closed by an opposite signal`; `PARALLEL` allows overlap and names itself in the
  caveats. Whether a signal conflicts is answered by the open position's own
  outcome, so a position that exited three bars ago does not keep blocking signals
  for the rest of its horizon.
- **`caveats` is returned inside the result**, so a report cannot travel without
  them, and two entries are generated from the run's own settings: with no horizon
  the excursions cover the rest of the data rather than a holding period, and
  `SKIP` with no horizon holds a position open until a level is actually reached.
- **Two defects were found by the tests and fixed**, both recorded in
  `docs/algorithms/BACKTESTING.md` §6. Excursions were measured to the end of the
  horizon, which credited a stopped-out trade with everything the market did after
  it was no longer in the trade. And level-touching used one helper for both the
  target and the stop while reading the *favourable* extreme in both cases, so a
  long's stop was never actually tested and every reported "stop hit" was
  fabricated.
- `tests/unit/test_phase18_backtesting.py` — 38 tests. The level-touching tests
  build forward windows by hand and state the expected answer rather than running
  through a fixture, because the fabricated readings were plausible enough to pass
  a fixture-level test. One of them also asserts the module produces no `pnl`,
  `equity`, `expectancy`, `profit_factor`, `win_rate`, `sharpe` or `balance` key,
  which is the phase's central refusal.

### Changed
- **`Analyzer.analyze()` now reads the setup registry** instead of calling
  `analyze_breakout`, `detect_h1_h2`, `detect_l1_l2` and `analyze_reversal`
  directly. This is the `ARCHITECTURE.md` §9 work that Phases 12 to 15 each
  deferred to "Phase 16's pipeline work", and it is now done: the pipeline holds
  one detection path rather than two, which `CONTRIBUTING.md` rule 5 forbids.
- `setups` is now complete. It covers the four double detectors and the fading
  measured move, which the pipeline never ran, and each entry carries `detector`,
  `kind` and `setup_family` alongside the detector's own payload.
- `Analyzer.__init__` takes an optional `registry`, defaulting to
  `build_default_registry()`. A caller who wants extra detectors passes its own
  rather than mutating a global: `DEFAULT_REGISTRY` still exists for the
  mutate-on-import pattern, but the analyzer does not read it by default, because
  a process-wide mutable global makes behaviour depend on import order.
- The per-family layers are grouped by **family**, not by the registry's `kind`.
  Two of the eleven shipped detectors are registered with the default `kind`, so
  grouping by it silently lost them, and `pullbacks` / `breakouts` / `reversals`
  were coming back empty.
- The pipeline's family key is `setup_family`, not `family`, because a payload may
  already use that name for a narrower classification — a `MEASURED_MOVE`
  finding's `family` is `RANGE`, `CHANNEL`, `GAP` or `INVERSE`, and overwriting it
  would throw the projection family away.
- `setups/base.py` gained `FAMILY_BY_DETECTOR` and `family_for()`, and
  `trade/plan.py`'s duplicate copy now points at it. One mapping for the trade
  layer's anatomy lookup, the pipeline's grouping and the decision layer's
  evidence adapters, because a second copy is a second thing to keep in step.
- `from_fading_measured_move()` added to the evidence model as its sixth
  vocabulary: a fade's projection evidence plus its own lifecycle position
  (`PROJECTED` 0.2, `POTENTIAL` 0.4, `DEVELOPING` 0.7, `CONFIRMED` 1.0), with
  `COMPLETED` and `INVALIDATED` excluded for the same reason `FAILED` breakouts
  are.
- A detector that raises is now promoted to a result warning
  (`DETECTOR_FAILED:<name>`, `DETECTOR_SKIPPED:<name>`). The registry contains the
  failure rather than propagating it, so a run can come back with fewer setups
  than it should, and "nothing found" and "something broke" must not look alike.
- **Phase 19** — `tests/fixtures/golden/`: the five named fixtures
  (`golden_h2_001`, `golden_breakout_001`, `golden_mtr_001`, `golden_double_001`,
  `golden_fm_001`), and `docs/algorithms/VALIDATION.md`.
- **The golden suite is deliberately not a snapshot of the engine's output.** A
  golden file that stores what the code printed cannot tell a fix from a
  regression — it fails on both and passes on neither, and the way it gets updated
  is by pasting the new answer, which makes the human check optional. Each fixture
  instead pins specific values, states a `basis` for every one of them, and carries
  a list of **falsifiers**: bar edits whose effect the derivation predicts. Twelve
  of them, and they are assertions about causality, which a snapshot structurally
  cannot have.
- **Provenance is enforced rather than trusted.** Every pinned value needs a stated
  reason, every block of expectations must contain at least one piece of arithmetic,
  and each block is checked against an allow-list of behavioural fields so
  over-specification cannot creep in one field at a time. An unrecognised
  `must_not` claim is a **failure**, not a skip, so a fixture cannot introduce a
  claim nobody checks.
- **ATR is the one value that is pinned rather than derived**, since Wilder
  smoothing over 14 bars is checkable by hand and tedious fifty times over. The
  suite re-derives it with an independent implementation and asserts agreement, so
  it is two readings of the same definition rather than one agreeing with itself.
  Everything downstream is expressed as a formula (`stop = extreme_price -
  0.25 * atr`), so those claims hold for any ATR.
- **Three findings, recorded rather than fixed** (`VALIDATION.md` §5):
  - **The fade lifecycle is unreachable through the pipeline.** The registry calls
    `create_setups`, which only seeds, and never calls
    `track_fading_measured_moves`. A live consumer therefore sees `PROJECTED` with
    `age 0` for a projection the market has already reached, and the five-state
    lifecycle is reachable only by calling the module directly. Fixing it means
    giving a stateless detector a stateful responsibility, which belongs with the
    MT5 adapter in Phase 21 rather than with a test fixture. **Closed for a live
    consumer (Phase 21)** — `AnalysisSession` is that stateful caller, and it
    **re-derives** the lifecycle on every call rather than accumulating it, because
    an incremental state machine would break `RPC-1`. The *pipeline* still reports
    `PROJECTED`, which is correct: the registry is stateless and that is its
    contract, so the session adds a caller rather than editing it.
  - **The pullback window is a configuration choice, not a reading of price.** The
    detector calls the first bar with a higher high the first leg, so in a clean
    uptrend the "pullback" is just the last `max_pb_bars` bars. `golden_h2_001`
    pins the config and supplies a flat top, which is what makes a higher high
    meaningful.
  - **Two of the three disagreements were derivations being wrong**, not engine
    defects: a retest named at bar 20 where the forward scan stops at bar 18, and a
    falsifier that expected to delete a double top where it actually relocates to
    an earlier pair. Both are recorded in the fixtures and were fixed by
    correcting the derivation.
- `tests/unit/test_phase19_golden.py` — 47 tests, including the closed-bar contract
  applied to the fixtures themselves and a guard that the newest bar *does* change
  the output, so the first is not vacuous.
- **What this phase is not**, stated in `VALIDATION.md` §1 and enforced by
  `test_the_dataset_claims_no_edge_and_no_forecast`: it is a semantic regression
  suite over five hand-drawn charts. It says what the engine names. It does not say
  any setup works, and §9 lists what would be needed to change that — the largest
  missing piece being a stated null.

### Fixed
- **A fading measured move outranked the measured move it was fading.** The
  decision layer had no FM evidence adapter, so a fade's bundle held only the
  shared market-state factors. Because `score()` averages *within* each source and
  then across sources, a bundle with a single source scores that source's value
  outright — the fade scored 100 ppts on market context alone, above a measured
  move with real measured factors behind it, and then manufactured an
  `EVIDENCE_CONFLICT` against the real read. Two fixes, both in place: the FM
  adapter, and a new blocking `NO_OWN_EVIDENCE` gate that refuses to rank any
  candidate whose bundle says nothing about its own setup. The same inversion
  cannot come back through a family nobody wrote an adapter for.
- **A trend trade and a fade of the same projection scored identically**, so the
  conflict gate reported a zero-width `EVIDENCE_CONFLICT` on every strong measured
  move. The fade's lifecycle factor is what makes the two distinguishable:
  `POTENTIAL` means price has only *approached* the target, which is a weaker
  claim than a confirmed projection, and the weaker claim now scores lower. The
  gap is what the ranking sees, and it is a difference in evidence rather than a
  tuned constant.
- `pullbacks`, `breakouts` and `reversals` were coming back empty once detection
  moved to the registry, because they were grouped by the registry's `kind` and
  two shipped detectors are registered with the default one.

### Added
- **Phase 17** — `docs/algorithms/NON_REPAINT_CONTRACT.md`: the closed-bar
  promise, finally a **numbered contract** rather than a claim scattered across
  `ARCHITECTURE.md` §6, four algorithm specifications and a dozen tests.
  Eighteen guarantees, `RPC-1` to `RPC-18`, each with the reason it exists, how
  it is enforced, and the name of the test that enforces it.
- **`RPC-7`, per-detector closure.** Every one of the eleven registered detectors
  is checked individually, driven off `build_default_registry()`, so a detector
  added later is covered by construction rather than by remembering. `RPC-1` is
  asserted at the *pipeline* level, which catches a mis-wired stage but says
  nothing about a detector that is individually wrong.
- **`RPC-15`, the historical freeze.** A live series whose newest bar is still
  forming is truncated, and the frozen result is compared with the historical one
  — including while the forming bar *mutates*, which is the property a consumer
  recomputing on every tick actually depends on.
- **`RPC-16`, the truncation is load-bearing.** Analysing the forming bar as if it
  were closed must produce a *different* answer, or `BarSeries` might simply be
  ignoring its last bar and "freeze your series" would be advice with no cost.
- **`RPC-18`, the contract is checked against the suite.** The document is parsed,
  its `RPC-n` identifiers are collected, and every test it names is resolved
  against the suite's own source. A renamed or deleted test fails there rather
  than leaving the document quietly claiming something false.
- The contract states its own vocabulary (closed bar, forming bar, `last_closed`,
  confirmation, freeze) and a §6 on **what it does not promise**: not that the
  analysis is good, not the same answer across brokers, not that a signal was
  stable in hindsight, and nothing at all about gaps.
- `docs/algorithms/NON_REPAINT_CONTRACT.md` is promoted to a required CI document,
  and a test asserts the promotion, because a contract that can go missing is not
  a contract.
- `tests/unit/test_phase17_non_repaint.py`, and a test that proves the
  reference-checker can actually fail on a deliberately bogus reference.

### Documented
- **There is no forming-bar flag, and that is the design.** `Bar` has no
  `is_forming` field and `BarSeries` is a sequence of *closed* bars. A flag would
  have to be threaded through every detector, and a detector that forgot to honour
  it would be a look-ahead bug no test could see. Freezing the series is therefore
  the **adapter's** obligation, and Phase 21 owns it. `RPC-14` and `RPC-15` say
  what happens when it does its job and `RPC-16` what happens when it does not.
- `ARCHITECTURE.md` §6 now points at the contract rather than describing the
  invariant a second time, and `CONCEPT_TAXONOMY.md` §4 classifies the guarantees
  themselves as `OBJECTIVE` — a property of arithmetic and index threading is
  either true or it is not, which is why they are testable at all.

### Known limitations
- **The higher-timeframe veto is one blunt rule.** It knows only that the higher
  proxy reads the other way, which is enough to withhold a signal and not enough
  to reverse one. A genuine counter-trend trade is indistinguishable from a
  mistake at this resolution, and `htf_opposition_veto=False` exists because the
  default is a choice rather than a finding.
- **The bias is a read, not a higher-timeframe strategy.** It comes from one
  higher bar's market-state classification. There are no higher-timeframe swings,
  legs or setups, so the higher timeframe contributes context and nothing else.
- **A new *layer* is not covered by the contract by construction.** A detector
  registered in the registry is, via `RPC-7`; a layer has to assert `RPC-1` for
  itself. The contract says so rather than implying coverage it cannot provide.
- `htf_min_strength` and `htf_opposition_veto` are chosen values on a proxy. A
  veto that fired on every directional higher-timeframe read would be a veto on a
  mood; a test pins the same fixture vetoing at `0.30` and not vetoing at the
  default, so the threshold is provably doing work.
- **No higher-timeframe claim here has been validated.** A higher-timeframe veto
  sounds like a well-known improvement and may be one, but nothing in this project
  has been checked against outcomes, so the claim here is only that the two
  readings can be compared and the comparison reported.
- `max_failed_attempts` counts two evidence codes, not failures in general, and
  the fading-measured-move lifecycle arrived in Phase 16 while a count of *failed*
  fades still needs the terminal states to be recordable.
- Every gate threshold in the decision layer is a chosen value. `min_rr = 1.0` is
  a convention. Setting `min_rr` to 3.0 does not improve a 3.1 plan; it makes
  fewer plans eligible, which is a different thing.
- **Adding market-state evidence to every bundle can lower a score**, because
  `score()` balances sources and a context made of bare assertions is a weak
  source. That is the Phase 13 per-source rule working, and a test asserts the
  contribution rather than a rise.
- `evaluation.compare()` is still for display only. The decision engine is the one
  sanctioned ranking, and nothing downstream may treat the two as the same thing.

## [0.1.0] — 2026-09-27

Initial development series, Phases 0-10. Every phase below is a **partial**
implementation being brought into line with the master specification; the
`Analyzer.analyze()` pipeline is not yet wired.

### Added
- **Phase 0** — `docs/FM_INDICATOR_AUDIT.md`: audit of the reference
  implementation, with migration strategy.
- **Phase 1** — package foundation: `Bar`, `BarSeries`, `AnalyzerConfig`,
  `AnalysisResult`, public API, CI.
- **Phase 2** — bar-by-bar engine: bodies, wicks, close location, doji,
  inside/outside, barbwire, overlap, pressure, ATR.
- **Phase 3** — swing, leg and two-legged-structure detection with delayed
  confirmation and no lookahead.
- **Phase 4** — market-context engine: trend, channel, trading-range and
  breakout-mode proxies.
- **Phase 5** — structures: climax, stall, pushes, wedge, overshoot, exhaustion.
- **Phase 6** — H1/H2 and L1/L2 pullback detection.
- **Phase 7** — major/micro double tops and bottoms.
- **Phase 8** — breakout state machine with follow-through and failure
  precedence.
- **Phase 9** — Major/Minor Trend Reversal engine.
- **Phase 10** — measured-move engine with five families: `REGULAR`
  (Leg 1 = Leg 2), `CHANNEL` (shallow pullback), `RANGE` (range-height breakout),
  `GAP` (measuring gap) and `INVERSE` (failed breakout of the leg extreme).

### Known gaps
*(as of 0.1.0; see the Unreleased section above for which of these are now closed)*

- `Analyzer.analyze()` still returns a Phase 1 placeholder; the pipeline is not
  wired, so the documented public API does not yet produce analysis output.
  **Closed** — the pipeline is wired (B9).
- `AnalysisResult` is missing the `trends`, `channels`, `pullbacks`, `breakouts`,
  `reversals` and `evidence` fields named in the specification.
  **Closed** (B9).
- Pivots (Phase 3) and several structures (Phase 5) are not implemented.
  **Closed** (B1, B3).
- Pullback lifecycle states (Phase 6) are not distinguished.
  **Closed** (B4).
- `MeasuredMove` does not yet expose the `reference_leg`, `confidence` or
  `evidence` fields required by the specification. **Closed** (B8).
- Reversal detection, quality and decision are not yet separated.
  **Closed** (B7).
- No `examples/`, integration, regression, parity or golden test suites yet.
  **Largely closed.** `tests/unit/test_engine_pipeline.py` is an
  integration/regression suite, and Phase 19 added the golden fixtures at
  `tests/fixtures/golden/` with `tests/unit/test_phase19_golden.py`. Still open:
  `examples/` (Phase 22) and the MQL5 parity harness (Phase 20).
