# FM-Indicator Repository Audit (Phase 0)

## Executive Summary

This document presents a comprehensive technical audit of [`FM-Indicator`](https://github.com/ybagheri/FM-indicator), conducted to inform the architecture, extraction, and clean redesign of the **Al Brooks Price Action Engine** (`al-brooks-price-action-engine`).

The `FM-Indicator` repository represents an advanced, battle-tested MQL5 and Python mirror implementation focusing on Fading Measured Moves (FM), bar-by-bar price action classification, multi-pattern detection (H1/H2, L1/L2, Major Trend Reversals, Double Tops/Bottoms, Breakouts), a multi-tiered Decision Engine with structural vetoes, and trade lifecycle execution. It achieved full closed-bar non-repainting semantics and 100% parity across 140 automated Python tests.

However, `FM-Indicator` was designed with an MQL5 indicator/EA application mindset. The new project, `al-brooks-price-action-engine`, extracts the foundational price-action algorithms, unifies their domain abstractions, decouples them entirely from MetaTrader 5 execution specifics, and establishes a modular, extensible, platform-independent Python library with type-safe interfaces, rich diagnostic evidence, and clean MQL5 parity adapters.

---

## 1. Reusable Components & Algorithms

The following components from `FM-Indicator` possess sound mathematical/algorithmic definitions that will be adapted into the core library:

1. **Bar-by-Bar Primitive Engine (`BarAnalyzer.mqh`, `tests/bar_analyzer.py`)**:
   - Closed-bar feature extraction: body size, range, upper/lower wicks, close/open location fractions.
   - Classification predicates: bull/bear bar, doji (`body <= 0.15 * range`), big bar (`range >= 2.0 * ATR`), small bar (`range <= 0.5 * ATR`), strong close (`close_pct >= 0.70`), inside bar, outside bar, `ii` pattern counts.
   - Barbwire & overlap detection: running body overlap metric, barbwire condition (>= 3 overlapping bars with alternating polarity and flat EMA within window).
   - Pressure metrics: rolling buy/sell volume proxy, close location averages over lookback.

2. **Swing Detection & Non-Repaint Confirmation (`Swings.mqh`, `tests/fm_engine.py`)**:
   - $k$-bar fractal swing detection ($k$ bars left and right).
   - Strict delayed confirmation at index $i + k$, eliminating lookahead bias while maintaining exact historical reproduction.

3. **Measured Move Families (`MeasuredMove.mqh`, `SessionMeasuredMove.mqh`)**:
   - Four distinct projection families:
     * Leg 1 = Leg 2 ($AB = CD$).
     * Range height projection (breakout of trading range).
     * Channel projection (parallel channel depth).
     * Gap projection (measuring gap as midpoint of trend).
   - Touch vs. confirmation distinction: touch is an objective geometrical event; confirmation requires exhaustion/reversal bar confirmation.

4. **Market Context & State Machine (`MarketState.mqh`, `tests/market_state.py`)**:
   - 6-state probabilistic or score-based classification: `BULL_TREND`, `BEAR_TREND`, `BULL_CHANNEL`, `BEAR_CHANNEL`, `TRADING_RANGE`, `BREAKOUT_MODE`.
   - Feature weights: EMA trend slope, EMA gap, higher-high/higher-low counts, bar overlap ratio, consecutive bull/bear bars.

5. **Pullback Patterns: H1/H2 and L1/L2 Counting (`PullbackPatterns.mqh`, `tests/pullback_patterns.py`)**:
   - Systematic counting rules for legs within pullbacks against an established trend.
   - Candidate $\rightarrow$ Provisional $\rightarrow$ Confirmed $\rightarrow$ Invalidated lifecycle.

6. **Reversal & MTR Detection (`ReversalEngine.mqh`, `tests/reversal.py`)**:
   - Major Trend Reversal (MTR) 4-phase sequence: Trend $\rightarrow$ Breakout of trendline $\rightarrow$ Test of extreme (higher high / lower low or double top/bottom) $\rightarrow$ Strong reversal signal bar.
   - Minor Trend Reversal (climax exhaustion, wedge overshoot).

7. **Breakout Engine & Second-Leg Traps (`BreakoutEngine.mqh`, `tests/breakout.py`)**:
   - Breakout state lifecycle: `NONE` $\rightarrow$ `PENDING` $\rightarrow$ `BREAKOUT` $\rightarrow$ `FOLLOW_THROUGH` or `FAILED`.
   - Trapped trader identification (second-leg trap at key boundaries).

8. **Decision Engine & Structural Vetoes (`DecisionEngine.mqh`, `tests/decision.py`)**:
   - Hierarchical gating: Disabled $\rightarrow$ No Setup $\rightarrow$ Barbwire Veto $\rightarrow$ Mid-Range Veto $\rightarrow$ Conflict Veto $\rightarrow$ No Edge Veto $\rightarrow$ Score Threshold $\rightarrow$ Minimum Reward-to-Risk $\rightarrow$ Late Entry Veto $\rightarrow$ Trap Repeat Veto $\rightarrow$ Buy/Sell Action.

---

## 2. Components Requiring Redesign

1. **Tight Coupling between Setup Types and FMEngine**:
   - In `FM-Indicator`, `FMEngine` served as the primary monolith, while other setups (`GeneralSetups.mqh`) were retrofitted around it.
   - *Redesign*: In `al-brooks-price-action-engine`, a plugin-style `SetupDetector` protocol (`albrooks.setups.base`) treats `FadingMeasuredMove` as one of many first-class setups alongside `H1H2`, `Breakout`, `Reversal`, and `DoublePatterns`.

2. **Primitive Dictionary Data Structures in Python Mirror**:
   - The Python mirror in `FM-Indicator` used generic `dict` and loose tuple formats for speed in parity checking.
   - *Redesign*: Clean, immutable, strongly-typed Python dataclasses (`Bar`, `BarSeries`, `Swing`, `Leg`, `MarketState`, `Setup`, `TradePlan`, `Decision`, `AnalysisResult`) with Pydantic/dataclass serialization and clear schemas.

3. **Duplication of Swing and Leg Calculations**:
   - Low-level swing logic was implemented in `Swings.mqh` and partially recomputed inside `MeasuredMove.mqh` and `PullbackPatterns.mqh`.
   - *Redesign*: A single, authoritative `SwingsEngine` and `LegsEngine` in `albrooks.core` producing immutable structural representations that all downstream modules consume.

4. **Trade Execution & Order Management Concerns**:
   - `PositionManager.mqh`, `SafetyManager.mqh`, and `PaperTrader.mqh` handled MT5 broker orders, lot sizing, and live trade tracking.
   - *Redesign*: Strict separation of analysis from execution. The core engine outputs analytical `TradePlan` and `Decision` objects. Platform-specific execution is relegated strictly to adapter layers.

---

## 3. Existing Tests vs. Missing Tests

### Existing Tests in `FM-Indicator` (140 passed)
- Comprehensive unit tests for bar metrics (`test_bar.py`).
- Breakout state machine verification (`test_breakout.py`).
- Decision veto pipeline verification (`test_decision.py`).
- Setup geometry and RR gates (`test_setup.py`).
- Market state classification (`test_state.py`).
- Strategy registry and tiebreaking (`test_registry.py`).
- Parity compare between MQL5 outputs and Python models (`parity_compare.py`).

### Missing Tests Addressed in the New Engine
- **Multi-Timeframe Lookahead Rigor**: Specific tests verifying that higher-timeframe bar ingestion does not expose unclosed HTF bar data to lower-timeframe timestamps.
- **Incremental Streaming Equivalence**: Validating that streaming bars one by one via `engine.update(bar)` produces identical results to batch `engine.analyze(bars)`.
- **JSON Schema Validation**: Automated schema validation of `result.to_json()` ensuring AI agents and web dashboards receive compliant structured payloads.
- **Golden Regression Suite**: Dedicated test fixtures for each Al Brooks concept (`golden_fm_001`, `golden_h2_001`, `golden_breakout_001`, `golden_mtr_001`, `golden_double_001`).

---

## 4. Technical Debt & Architecture Weaknesses in Source

1. **Monolithic Include Chains in MQL5**: Circular header dependencies resolved by custom forward declarations.
2. **Hard-coded Magic Numbers**: Some heuristics (e.g. 10-bar lookback for pressure, 0.70 strong close ratio) were sprinkled across multiple mqh files without centralized configuration injection.
3. **Implicit Array Indexing Confusion**: MT5 uses reverse indexing (`0` is newest active bar, `N-1` is oldest), while Python uses forward indexing (`0` is oldest, `N-1` is newest). In `FM-Indicator`, mapping back and forth required repetitive mental arithmetic and conversion functions.
4. **Lack of Explainability Metadata**: Setups recorded scores, but did not consistently serialize machine-readable multi-factor evidence trees and warnings for consumption by LLM agents or research tools.

---

## 5. Migration & Redesign Strategy

1. **Step 1**: Establish `albrooks` Python package with pure, zero-dependency core domain models.
2. **Step 2**: Implement core bar-by-bar engine and swing/leg detection with strict non-repaint contracts.
3. **Step 3**: Build Context and Structure engines (Market State, Trends, Channels, Ranges).
4. **Step 4**: Implement specialized pattern engines (H1/H2, Doubles, Breakouts, Reversals, Measured Moves, Fading Measured Moves).
5. **Step 5**: Create unified Setup Registry, Evidence Scoring Model, Trade Plan Generator, and Decision Engine.
6. **Step 6**: Provide MT5 Adapters, Backtesting harness, Golden datasets, MQL5 parity layer, and AI agent interfaces.
7. **Step 7**: Produce complete bilingual documentation (English and Persian).

---
*Audit Completed as part of Phase 0 of the Master Development Plan.*

