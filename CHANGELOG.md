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

### Changed
- `docs/algorithms/MEASURED_MOVE.md` renamed to `MEASURED_MOVES.md` to match the
  documented spec filename.
- `AnalyzerConfig` gained the measured-move family flags
  (`enable_range_mm`, `enable_channel_mm`, `enable_gap_mm`,
  `enable_inverse_mm`, `range_lookback`, `min_gap_atr`).

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
- `Analyzer.analyze()` still returns a Phase 1 placeholder; the pipeline is not
  wired, so the documented public API does not yet produce analysis output.
- `AnalysisResult` is missing the `trends`, `channels`, `pullbacks`, `breakouts`,
  `reversals` and `evidence` fields named in the specification.
- Pivots (Phase 3) and several structures (Phase 5) are not implemented.
- Pullback lifecycle states (Phase 6) are not distinguished.
- `MeasuredMove` does not yet expose the `reference_leg`, `confidence` or
  `evidence` fields required by the specification.
- Reversal detection, quality and decision are not yet separated.
- No `examples/`, integration, regression, parity or golden test suites yet.
