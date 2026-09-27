# Al Brooks Price Action Engine — Living Roadmap

This roadmap documents the implementation progress across all 23 development phases.

It answers three separate questions, and each is kept distinct because they are
different claims:

| Section | Question |
|---|---|
| [Phase Checklist](#phase-checklist) | What is built and verified? |
| [Deliberately Not Built](#deliberately-not-built) | What will not be built, and why? |
| `CHANGELOG.md` → *Known limitations* | What is built but imperfect? |

## Status Legend
- `[x]` Completed & Verified
- `[ ]` In Progress / Pending

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
  - **Deliverable**: `src/albrooks/setups/measured_move.py`, `docs/algorithms/MEASURED_MOVE.md`, tests.
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
    analyzer's direct detector calls; that is Phase 16's pipeline work.

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
    and the payload carries `is_probability: false`. Not yet consumed by the
    pipeline; that is Phase 16.

- [ ] **Phase 14 — Trade Plan Engine**
  - **Objective**: Platform-independent trade plan (entry, stop, target, R:R, invalidation, management notes).
  - **Deliverable**: `src/albrooks/trade/plan.py`, tests.

- [ ] **Phase 15 — Decision Engine**
  - **Objective**: Transparent decision pipeline (BUY, SELL, WAIT, NO_TRADE) with structural vetoes and explainability.
  - **Deliverable**: `src/albrooks/decision/engine.py`, `src/albrooks/decision/veto.py`, tests.

- [ ] **Phase 16 — Multi-Timeframe Architecture**
  - **Objective**: Synchronized HTF bias, timestamp alignment, strict no-lookahead contracts.
  - **Deliverable**: `src/albrooks/engine/pipeline.py`, tests.

- [ ] **Phase 17 — Real-Time / Non-Repaint Contract**
  - **Objective**: Formal closed-bar guarantees, historical freeze, delayed confirmation validation.
  - **Deliverable**: `docs/NON_REPAINT_CONTRACT.md`, tests.

- [ ] **Phase 18 — Backtesting Interface**
  - **Objective**: Lightweight event-driven validation (MFE, MAE, time to target/stop, outcome metrics).
  - **Deliverable**: `src/albrooks/backtest/events.py`, tests.

- [ ] **Phase 19 — Validation Dataset**
  - **Objective**: Golden fixtures (`golden_fm_001`, `golden_h2_001`, `golden_breakout_001`, `golden_mtr_001`, `golden_double_001`).
  - **Deliverable**: `tests/fixtures/golden/`, tests.

- [ ] **Phase 20 — Python / MQL5 Parity**
  - **Objective**: Closed-bar parity validation harness between Python and MQL5 components.
  - **Deliverable**: `tests/parity/`, `docs/PYTHON_MQL5_PARITY.md`.

- [ ] **Phase 21 — MT5 Adapter & MQL5 Layer**
  - **Objective**: MQL5 include headers, MT5 python connector, indicator & EA templates.
  - **Deliverable**: `src/albrooks/adapters/mt5/`, `mql5/Include/AlBrooks/`.

- [ ] **Phase 22 — AI / LLM Interface**
  - **Objective**: Stable JSON serialization for LLM agents, diagnostic output, example script.
  - **Deliverable**: `src/albrooks/serialization/json.py`, `examples/llm_analysis.py`.

- [ ] **Phase 23 — Comprehensive Bilingual Documentation**
  - **Objective**: Complete English and Persian documentation suite (`README.md`, `README_FA.md`, algorithm specs).
  - **Deliverable**: `docs/`, `README.md`, `README_FA.md`.

---

## Deliberately Not Built

The other two lists above say what *is* done and what *remains*. This one records
what is **not going to be built**, and why — because a project whose premise is
honest self-reporting should not leave its exclusions implicit either.

Each entry states the thing, the reason, and what would have to change.

### The engine will not rank competing setups

A measured-move target and a reversal leg count are different kinds of claim.
Picking between them is a *trade decision*, and this project has not earned it:
nothing here has been validated against outcomes, so any ordering would be a
preference dressed as an analysis.

- The registry returns findings in **registration order**, which is deterministic
  and is not a ranking (`docs/algorithms/SETUP_ENGINE.md` §5).
- `evaluation.compare()` orders bundles **for display only**; nothing downstream
  may treat its order as a recommendation
  (`docs/algorithms/EVIDENCE_MODEL.md` §6).

*Changes when:* the decision engine (Phase 15) exists, and is where the comparison
belongs.

### No score in this project is a probability

`CONCEPT_TAXONOMY.md` §5 classifies no value here as `STATISTICAL`, because
nothing has been statistically validated. The evidence score is a mean of
observed factor weights; `0.8` does not mean "right 80% of the time".
`EvidenceScore.to_dict()` carries `is_probability: false` so downstream consumers
are told rather than left to know.

*Changes when:* a validation phase (19/20) calibrates against historical data.
Per the taxonomy, the method, sample and confidence intervals must be documented
there **before** any of these labels may change.

### The pipeline will not infer a trade

`decision` is always `NO_TRADE` with the reason `DECISION_ENGINE_NOT_IMPLEMENTED`,
and `AnalysisResult.layers` marks `trade_plans` and `decision` as not run, so
`unimplemented_layers` is a fact rather than an inference from an empty list.

*Changes when:* Phases 14 and 15 land.

### Declared but deliberately unwired configuration

Six `AnalyzerConfig` keys are consumed by **nothing** today. They are Phase 15's
`Decision Engine & Gating` block, declared ahead of the engine that owns them:

| Key | Default | Owner |
|---|---|---|
| `enable_decision` | `True` | Phase 15 |
| `min_score` | `40.0` | Phase 15 (Phase 13 supplies the evidence score) |
| `min_rr` | `1.0` | Phase 15 |
| `max_late_atr` | `0.50` | Phase 15 |
| `conflict_ppts` | `10` | Phase 15 |
| `max_failed_attempts` | `2` | Phase 15 |

> **Setting any of these has no effect today.** They are listed here so that a
> user tuning `min_rr` is not left to wonder why nothing changed. They were kept
> rather than deleted because the values are documented defaults for a specified
> layer, not invented as they went.

*Changes when:* Phase 15 reads them.

### `engine.state.NOT_IMPLEMENTED` is unused

The constant `NOT_IMPLEMENTED = "NOT_IMPLEMENTED_YET"` is defined and referenced
nowhere. Its stated purpose — distinguishing "not detected" from "never looked
for" — is actually served by the `layers` map, and `unimplemented_layers` reads
that. The constant is retained as a reserved marker, not because it is live.

*Changes when:* something needs a per-*value* not-implemented marker, as opposed
to the per-*layer* one already implemented.

### `examples/` is empty and untracked

The directory exists on the working machine but **contains no files**, so it does
not survive a fresh clone. Phase 22 owns `examples/llm_analysis.py`. The 0.1.0
changelog listed missing examples as a known gap, and that gap is still open.

### Not started at all

`src/albrooks/decision/`, `src/albrooks/trade/`, `src/albrooks/adapters/` and
`src/albrooks/serialization/` each contain only an empty `__init__.py`. They are
placeholders for Phases 14, 15, 21 and 22, not partial implementations.

