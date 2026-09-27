# Changelog

All notable changes to this project are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Status: pre-1.0.** The public API may still change. Nothing in this project has
been statistically validated, and no performance claim is made.

## [Unreleased]

### Added
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
  winner. Ranking them is a decision, and the decision layer does not exist yet.

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
- Recorded there, every claim verified against the source rather than assumed:
  - The setup registry and `evaluation.compare()` do not rank competing setups.
  - No score in this project is a probability.
  - The pipeline never infers a trade (`NO_TRADE` /
    `DECISION_ENGINE_NOT_IMPLEMENTED`).
  - The six `AnalyzerConfig` keys consumed by nothing — `enable_decision`,
    `min_score`, `min_rr`, `max_late_atr`, `conflict_ppts`,
    `max_failed_attempts`. Each was confirmed to have zero references outside
    `configuration.py` in both `src/` and `tests/`. A user tuning `min_rr` today
    gets no effect and previously had no way to learn why.
  - `engine.state.NOT_IMPLEMENTED` is defined and never used; the job it
    describes is actually done by the `layers` map and `unimplemented_layers`.
  - `examples/` is empty and untracked, so it does not survive a fresh clone.
    Phase 22 owns `examples/llm_analysis.py`, and the 0.1.0 known-gap entry for
    missing examples is still open.
  - `decision/`, `trade/`, `adapters/` and `serialization/` hold only empty
    `__init__.py` placeholders — not partial implementations.
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
- The evidence model is not yet consumed by `Analyzer.analyze()`; the
  pipeline's existing `evidence` list is unchanged, because rewiring it would
  have altered output that `tests/unit/test_engine_pipeline.py` pins. Wiring the
  two together is Phase 16's pipeline work.
- `AnalyzerConfig.min_score` is still consumed by nothing. Phase 13 supplies the
  evidence score it was evidently waiting for, but gating on it is the decision
  engine's job (Phase 15), so it is deliberately left unwired rather than used
  as a threshold here.
- The FM exhaustion gate binds more loosely than the specification's wording
  suggests. A bar touching a measured-move target is by construction the extreme
  of the recent range, so the `overshoot` exhaustion condition is almost always
  satisfied on the touching bar, and `POTENTIAL -> DEVELOPING` nearly always
  happens there. The gate is kept as specified; the interaction is documented in
  `docs/algorithms/FADING_MEASURED_MOVE.md` §5.2 and pinned by a test, because
  removing the gate would otherwise not fail any test.
- `Analyzer.analyze()` still calls its detectors directly rather than reading the
  registry. Phase 12's claim is that a detector can be *added* without editing
  the analyzer, and `build_default_registry()` satisfies that; making the
  pipeline consume the registry is Phase 16's work.
- `DEFAULT_REGISTRY` is a process-wide mutable global. `build_default_registry()`
  is preferred in library code and tests, because a shared mutable global makes
  test order matter. A test pins that the two are independent.

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
  Partly addressed: the pipeline suite in `tests/unit/test_engine_pipeline.py`
  is an integration/regression suite. `examples/`, parity and golden fixtures
  remain.
