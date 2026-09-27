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
| Evaluation | `albrooks.evaluation` | Evidence and quality scoring. *(planned)* |
| Decision | `albrooks.decision` | Transparent BUY/SELL/WAIT/NO_TRADE with reasons. *(planned)* |
| Trade plan | `albrooks.trade` | Platform-independent plan objects. *(planned)* |
| Adapters | `albrooks.adapters` | Data-frame, CSV, and MT5 translation. *(planned)* |
| Orchestration | `albrooks.engine` | Config, pipeline, result container. |

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

See `docs/algorithms/MEASURED_MOVES.md` §4 and
`docs/algorithms/NON_REPAINT_CONTRACT.md` *(planned)*.

## 7. Facts vs interpretation

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

## 8. Extensibility

New setups must be addable **without modifying the central analyzer.** The
registry pattern (`albrooks.setups.registry`) is designed so that registering a
detector is a one-line change and the analyzer is untouched. If adding a
detector requires editing `engine/analyzer.py`, the architecture has been
violated and that should be raised rather than worked around.

## 9. Serialization

Every domain model is an immutable, slotted dataclass with a `to_dict()`, so
the whole analysis is JSON-serializable without reaching into internals. This is
what makes the library usable from an AI agent, a dashboard, or a REST API
without exposing Python object graphs.

## 10. Configuration

Every heuristic threshold lives on `AnalyzerConfig` — never as a literal buried
in a detector. Configuration round-trips through `to_dict()` / `from_dict()`.

The reason: when a threshold is wrong, the fix should be a config change, not a
code change. And when a result is surprising, the user needs to be able to see
and change every value that produced it.

## 11. Testing strategy

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

## 12. Anti-goals

Stated explicitly, because they are the most reliable way to keep this project
honest:

- **No profitability claims.** Ever, without documented statistical validation.
- **No MT5 in the core.** Ever.
- **No hidden thresholds.** If a number affects output, it is configurable and
  documented.
- **No duplicated algorithms.** One authoritative implementation per concept.
- **No circular dependencies**, even convenient ones.
- **No "this is exactly what Al Brooks means."** See [SOURCES.md](../../SOURCES.md).
