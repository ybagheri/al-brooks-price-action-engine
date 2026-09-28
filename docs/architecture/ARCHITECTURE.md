# Architecture

## 1. The one rule

> Separate **price-action facts** from **interpretation** from **platform execution**.

Everything else in this document follows from that. The failure mode this
project exists to avoid is a library where a broker order and a swing-detection
threshold are tangled together, so that nothing about the analysis can be
trusted, tested, or reused without dragging execution along with it.

## 2. Layers

```text
Raw Market Data
       ↓
Bar Normalization
       ↓
Primitive Price-Action Features
       ↓
Swings / Legs / Structure
       ↓
Context / Market State
       ↓
Pattern Detection
       ↓
Setup Detection
       ↓
Setup Evaluation
       ↓
Trade Plan
       ↓
Decision / Interpretation
       ↓
Platform Adapter
```

| Layer | Package | Responsibility |
|---|---|---|
| Normalization | `albrooks.core.bars` | Immutable `Bar`, `BarSeries`, oldest-first indexing, validation. |
| Features | `albrooks.price_action` | Per-bar and cross-bar geometry. Facts, no judgement. |
| Structure | `albrooks.core.{swings,legs,structures}` | Swings, legs, and structural observations. |
| Context | `albrooks.context` | Systematic proxies for market mode. |
| Patterns | `albrooks.setups` | Named price-action patterns and setups. |
| Evaluation | `albrooks.evaluation` | Evidence and quality scoring. |
| Trade plan | `albrooks.trade` | Platform-independent plan objects. Implemented and in the pipeline. |
| Decision | `albrooks.decision` | Transparent BUY/SELL/WAIT/NO_TRADE with reasons. Implemented and in the pipeline. |
| Adapters | `albrooks.adapters` | Data-frame, CSV, and MT5 translation. *(planned)* |
| Orchestration | `albrooks.engine` | Config, pipeline, result container, multi-timeframe alignment. |
| Backtesting | `albrooks.backtest` | Replays the engine over a series and records path geometry and outcome. Read-only on decisions; produces no P&L. Implemented, and **outside** the live pipeline. |

## 3. Dependency direction

```text
Core primitives → Structure → Context → Patterns → Setups
               → Evaluation → Decision → Adapters
```

Arrows point in the allowed direction only. Concretely:

- Fading may depend on MeasuredMove. **MeasuredMove must never depend on Fading.**
- H2 uses generic pullback and structure components. **The core must never
  depend on H2.**
- Setup detectors consume an analysis context. **The context must never import a
  specific setup detector.**

This is enforced mechanically, not by convention — see
[`scripts/check_no_mt5_dependency.py`](../../scripts/check_no_mt5_dependency.py),
which fails CI if the core reaches for MT5, a heavy runtime dependency, or the
adapters layer.

The reason to enforce it rather than trust it: cycles are *convenient* while
writing a single feature, and only become visible as pain later. A core that
imports a setup is unusable by a project that wants the structure without the
setup, which is most projects.

## 4. Platform independence

The core is **standard library only**. No MT5, no numpy, no pandas.

Where exact MQL5 parity is required, a parallel implementation lives under
`mql5/` and is validated against the Python core by parity tests with documented
tolerances. Python remains the reference implementation; MQL5 is a mirror, not
the source of truth.

## 5. Bar indexing

**Oldest-first, everywhere.** Index `0` is the oldest bar; `len(bars) - 1` is the
newest.

This is the opposite of MetaTrader 5 series indexing, where `0` is the forming
bar and indices count backwards. That inversion is a notorious source of
off-by-one bugs — it has been the cause of lookahead bugs in trading code
generally — so this project removes the ambiguity at the boundary rather than
carrying it inward. The only code that knows about MT5 ordering is the MT5
adapter.

## 6. Closed-bar contract

The engine is **closed-bars only** by default. A bar is used only after it has
closed.

Structural detections that inherently need right-side confirmation — a fractal
swing, for instance — are emitted from the bar that *confirms* them, and record
their `confirmed_bar_index`. This gives one invariant the test suite enforces:

> The analysis for a given bar index is **identical** whether or not later bars
> exist.

See `docs/algorithms/MEASURED_MOVES.md` §5 for the enforced implementation, and
`docs/algorithms/NON_REPAINT_CONTRACT.md` for the full numbered statement — eighteen
guarantees, each naming the test that enforces it.
`tests/unit/test_engine_pipeline.py` asserts the invariant above across every layer
of the pipeline at once, not only per detector.

## 7. The pipeline

`Analyzer.analyze()` is the only orchestrator. It is deliberately thin: each stage
is a pure function that already exists and is tested on its own, and the pipeline
only decides **order** and **which index to pass**.

```text
bars ──► ATR ──► bar features ──► swings ──► legs ──► pivots
                       │                         │
                       └──────────┬──────────────┘
                                  ▼
                            market state, trend metrics, channels
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
  measured moves             setup registry          channels, structures
        │                         │
        └──────────┬──────────────┘
                   ▼
        evidence bundles ──► trade plans ──► decision
                                              ▲
        higher-timeframe bias ─────────────────┘   (engine/pipeline.py)
```

Four decisions are worth stating, because each is a place where a
plausible-looking implementation would be wrong.

**ATR is computed first and gates the whole run.** Almost every threshold is
expressed in ATR multiples, and a detector handed `atr=0` returns "nothing found"
rather than raising. A pipeline that passed zero onward would return a clean, empty,
entirely plausible result describing a market with no structure. So the run is
refused, and the reason is reported.

**`last_closed` is threaded to every stage, and the value used is reported.** The
invariant is that analysis for a given index is identical whether or not later bars
exist. It is asserted at the pipeline level, not only per detector, because a
mis-wired stage — right detector, wrong index, or a series that includes the future
— passes every one of its own unit tests. That is exactly the class of bug this
layer is responsible for catching, and `bar_features` leaking future bars was a
real instance of it. The full numbered statement is
`docs/algorithms/NON_REPAINT_CONTRACT.md`.

**Setup detection goes through the registry, not around it.** `analyze()` runs
`build_default_registry()` over one `SetupContext` rather than calling four
detectors itself, so the pipeline holds one detection path. A caller with its own
detectors passes `Analyzer(config, registry=...)`. The registry returns findings in
registration order, which is deterministic and is not a ranking.

**Multi-timeframe alignment works in close times.** An H1 bar is not knowable until
its last M15 bar has closed, so the pipeline aligns on
`htf.time + htf_step <= ltf.time[i] + ltf_step` and analyses the higher series *as
of* the aligned bar. See `MULTI_TIMEFRAME.md` §2 and §7.

### Degenerate input is reported, not hidden

A series with no bars, or with no volatility, produces a result whose
`market_state.reason` and `decision.reason` say so, with every layer marked as not
run. Returning empty lists would be a claim about a market that was never examined.
`AnalysisResult.layers` records what actually ran, so `unimplemented_layers` is a
fact rather than an inference from an empty list.

### What the pipeline does not do

It reports structure, context, setup candidates, trade-plan geometry, and a
decision. The decision is a **ranking by declared criteria** — see
`docs/algorithms/DECISION_ENGINE.md` §6 — and it is allowed to answer `BUY`,
`SELL`, `WAIT` or `NO_TRADE`. It is not a validated edge, and
`Decision.to_dict()` says so with `is_probability: false`.

Two things it still will not do, both recorded in `ROADMAP.md`:

- **It will not promote the least bad candidate.** With every candidate gated out,
  the answer is `WAIT` with the failing gates named.
- **It will not resolve a contested reading by arithmetic.** Two directions within
  `conflict_ppts` of each other is `WAIT` / `EVIDENCE_CONFLICT`.

`engine/pipeline.py` adds one more veto above all of this: a lower-timeframe
decision that runs against a directional higher-timeframe read is withheld as
`AGAINST_HIGHER_TIMEFRAME`. It withholds rather than reversing, because knowing the
two disagree is not knowing which one to trade.

### Backtesting sits outside the pipeline

`albrooks.backtest` consumes decisions; it does not produce them. `replay()` calls
the ordinary `analyze()` at each bar and reads the bars *after* that one only to
classify the path. It is deliberately not a pipeline stage, and the dependency
arrow runs one way: a backtest can be wrong about the market, and nothing the live
pipeline does may depend on it.

This is where the closed-bar invariant earns its keep. Because the analysis for
bar `k` cannot depend on later bars, appending data cannot change a historical
event's plan, and the only thing a horizon controls is how far the outcome is
read. Where that stops being true — `horizon=None` runs a path to the end of the
series — the module says so in its own `caveats` rather than leaving it to the
reader.

It reports path geometry and outcome classification and produces no P&L, equity
curve or win rate. See `docs/algorithms/BACKTESTING.md`.

## 8. Facts vs interpretation

Not every layer is equally objective. See
[CONCEPT_TAXONOMY.md](CONCEPT_TAXONOMY.md) for the full classification.

The short version:

- **Layers 1-3 are mostly `OBJECTIVE` or `ALGORITHMIC`.** Bar geometry, swing
  detection, leg measurement. These are things you can check by hand.
- **Context and above are `PROXY` and `INTERPRETATION`.** "Trend" is not a
  thing; a market-state score is a documented stand-in for a human judgement.
  It is labelled as such everywhere it appears.
- **Nothing is `STATISTICAL`, because nothing has been validated.** No score in
  this project is a probability.

## 9. Extensibility

New setups must be addable **without modifying the central analyzer.** The
registry pattern (`albrooks.setups.registry`) is designed so that registering a
detector is a one-line change and the analyzer is untouched. If adding a
detector requires editing `engine/analyzer.py`, the architecture has been
violated and that should be raised rather than worked around.

## 10. Serialization

Every domain model is an immutable, slotted dataclass with a `to_dict()`, so
the whole analysis is JSON-serializable without reaching into internals. This is
what makes the library usable from an AI agent, a dashboard, or a REST API
without exposing Python object graphs.

## 11. Configuration

Every heuristic threshold lives on `AnalyzerConfig` — never as a literal buried
in a detector. Configuration round-trips through `to_dict()` / `from_dict()`.

The reason: when a threshold is wrong, the fix should be a config change, not a
code change. And when a result is surprising, the user needs to be able to see
and change every value that produced it.

## 12. Testing strategy

| Category | What it protects |
|---|---|
| unit | Each detector in isolation, with exact expected values. |
| integration | Detectors composed through the real pipeline. |
| regression | Golden fixtures pinning known-good behaviour. |
| lookahead | The no-lookahead invariant, asserted directly. |
| serialization | Output shape stability for downstream consumers. |
| parity | Python vs MQL5 agreement within documented tolerances. |

Tests are deterministic and never depend on live market data. A test that only
asserts "does not raise" is not a test — see [CONTRIBUTING.md](../../CONTRIBUTING.md).

## 13. Anti-goals

Stated explicitly, because they are the most reliable way to keep this project
honest:

- **No profitability claims.** Ever, without documented statistical validation.
- **No MT5 in the core.** Ever.
- **No hidden thresholds.** If a number affects output, it is configurable and
  documented.
- **No duplicated algorithms.** One authoritative implementation per concept.
- **No circular dependencies**, even convenient ones.
- **No "this is exactly what Al Brooks means."** See [SOURCES.md](../../SOURCES.md).
