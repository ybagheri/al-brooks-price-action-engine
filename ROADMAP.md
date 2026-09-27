# Al Brooks Price Action Engine — Living Roadmap

This roadmap documents the implementation progress across all 23 development phases.

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
  - **Status**: Completed.

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

- [ ] **Phase 10 — Measured Move Engine**
  - **Objective**: Generic MM framework (Leg 1 = Leg 2, Range projection, Channel projection, Gap projection).
  - **Deliverable**: `src/albrooks/setups/measured_move.py`, tests.

- [ ] **Phase 11 — Fading Measured Move (FM)**
  - **Objective**: Port and refine FM lifecycle (PROJECTED, POTENTIAL, DEVELOPING, CONFIRMED, COMPLETED, INVALIDATED).
  - **Deliverable**: `src/albrooks/setups/fading_measured_move.py`, tests.

- [ ] **Phase 12 — General Setup Registry**
  - **Objective**: Plugin-style setup detector protocol, setup registry.
  - **Deliverable**: `src/albrooks/setups/registry.py`, `src/albrooks/setups/base.py`, tests.

- [ ] **Phase 13 — Setup Evidence Model**
  - **Objective**: Structured multi-factor evidence, weights, warnings, confidence heuristics.
  - **Deliverable**: `src/albrooks/evaluation/evidence.py`, `src/albrooks/evaluation/scoring.py`, tests.

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
