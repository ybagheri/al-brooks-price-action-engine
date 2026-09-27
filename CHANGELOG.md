# Changelog

All notable changes to this project are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Status: pre-1.0.** The public API may still change. Nothing in this project has
been statistically validated, and no performance claim is made.

## [Unreleased]

### Added
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
