# Al Brooks Price Action Engine

A production-grade, extensible, **platform-independent** Al Brooks price-action
analysis engine written in Python.

> **Persian / فارسی: [README_FA.md](README_FA.md)**

## Purpose

This library turns closed OHLCV bars into structured, explainable price-action
analysis: market context, structural swings and legs, measured-move projections,
setup detection, trade-plan geometry, a decision, and a higher-timeframe read the
decision is held to.

It is an **analytical engine, not a trading system**. It never places orders and
never depends on MetaTrader 5. Platform integration lives strictly in adapters.

## Status

**23 of 24 phases are complete** (all but 21). One remains, and it is blocked on
hardware rather than on effort.

Phase 21 is **partially** delivered: the adapter, the freeze and the stateful
session are built, tested **and run against a live MetaTrader terminal** (which
found three defects the fake-driven tests had passed — see
[MT5_ADAPTER.md §10](docs/algorithms/MT5_ADAPTER.md)), while the MQL5 port is
blocked on MetaEditor and parity therefore still reports `UNVERIFIED`.

Phase 22 needed no external tooling and is complete: a stable, self-reporting
serialization for a language model that makes the payload 91% smaller and refuses
to emit a bare score. Phase 23 added `docs/fa/`, an index that records the
Persian status of all 24 English documents plus the three whose claims a reader
could act on.

See [ROADMAP.md](ROADMAP.md) → *Where the project stands* for the full picture
and [CHANGELOG.md](CHANGELOG.md) for history.

| Area | State |
|---|---|
| Bar-by-bar features | Implemented, unit tested |
| Swings, legs, pivots | Implemented |
| Market context | Implemented |
| Structures | Implemented |
| H1/H2, L1/L2 | Implemented, with lifecycle states |
| Doubles, breakouts, reversals | Implemented |
| Measured moves | Implemented, with evidence and confidence |
| Fading measured moves | Implemented — full lifecycle |
| `Analyzer.analyze()` pipeline | Wired — all layers above, closed-bar only |
| Evidence model | Implemented — one factor shape, source-balanced score |
| Trade plans | Implemented — entry / stop / target, every level with a stated basis |
| Decisions | Implemented — ranked, gated, and explainable |
| Multi-timeframe | Implemented — closed-bar alignment, HTF bias as a veto |
| Non-repaint contract | Formalised — 18 numbered guarantees, each naming its test |
| Backtesting | Implemented — MFE/MAE, time to level, outcome class. **No P&L, by design** |
| Golden fixtures | Implemented — 5 hand-authored charts, hand-derived expectations, falsifiers |
| MQL5 parity | **Harness built, nothing compared** — Phase 20. No MQL5 build exists yet |
| MT5 adapter | **Implemented and run against a live terminal** — Phase 21. Feed, series direction, forming-bar freeze, stateful session |
| MQL5 layer | **Not started** — Phase 21, blocked on MetaEditor. Nothing has been compared |
| AI / LLM interface | **Implemented** — Phase 22. 91% smaller payload, no score leaves as a bare number |
| Bilingual documentation | **Partial by choice** — Phase 23. `docs/fa/` indexes all 24 English docs and translates the three whose claims a reader could act on |

**Implementation status is not trading validation.** See
[Limitations](#limitations) — no performance claim is made anywhere in this
project, and the two rows above (`Backtesting`, `Golden fixtures`) are the ones
most likely to be misread as evidence. They are not.

### What is deliberately not built

Some things in this project are **absent on purpose**, not merely unfinished.
Those are recorded in
[ROADMAP.md → Deliberately Not Built](ROADMAP.md#deliberately-not-built) rather
than left implicit. The short version:

- **Competing setups are ranked in exactly one place, and the ranking is not an
  edge.** `decision.decide()` is the one layer allowed to compare them, and it
  sorts by declared criteria which it echoes in its own output. Every layer below
  refuses: the registry returns registration order, `evaluation.compare()` is for
  display only, and a `TradePlan` is never sorted by reward:risk. Nothing has been
  validated against outcomes, so that ordering is a comparison, not a
  recommendation.
- **The decision layer abstains rather than guessing.** `NO_TRADE` for disabled,
  un-analysable or nothing-found; `WAIT` for everything gated or contested. The
  least bad candidate is never promoted, and a near-tie between the two directions
  is never resolved by arithmetic. `enable_decision=False` answers `NO_TRADE`.
- **No score here is a probability.** The evidence score is a mean of observed
  factor weights. `0.8` does not mean "right 80% of the time", and
  `Decision.to_dict()` carries `"is_probability": false`. There is deliberately no
  `confidence` field anywhere in this project.
- **A trade plan is not an order.** `albrooks.trade.plan` reports geometry, with
  `to_dict()` carrying `"is_recommendation": false`. There is no sizing, no order
  type, and no expectation: sizing needs an account risk policy, and this project
  has no validated edge to size against.

## Architecture

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

The dependency direction is strictly downward. Measured moves never depend on
fading; fading consumes measured moves. The core never imports MT5.

## Installation

```bash
pip install albrooks
```

From source, for development:

```bash
pip install -e ".[dev]"
```

Requires Python 3.10+. The core has **no runtime dependencies**.

## Quick start

```python
from albrooks import Analyzer, AnalyzerConfig

config = AnalyzerConfig(atr_period=14, swing_k=3)
analyzer = Analyzer(config)

bars = [
    {"o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5},
    # ... oldest first ...
]

result = analyzer.analyze(bars, symbol="EURUSD", timeframe="H1")

print(result.market_state["mode"], result.market_state["direction"])
for setup in result.setups:
    print(setup["detector"], setup["setup_family"], setup.get("setup_type"))

# a decision, with the reasoning attached
print(result.decision["action"], result.decision["reason"])
for line in result.decision["explanation"]:
    print(" -", line)

# analyse as of an earlier bar; later bars cannot change the result
snapshot = analyzer.analyze(bars, last_closed=99)
```

Pass `last_closed` to analyse **as of** a bar index. Everything derived is read from
bars `0..last_closed` only, so the output for a given index is identical whether or
not later bars exist. A value past the end of the data is clamped, not rejected.

Degenerate input is reported rather than hidden. A series with no bars, or one with
no volatility at all, returns a result whose `market_state.reason` and
`decision.reason` say so, with every layer marked as not run — an empty layer would
otherwise read as a claim about the market that was never actually examined.

`result.layers` records which layers ran, and `result.unimplemented_layers` lists
the ones this build makes no claim about. For a normal analysis it is currently
**empty**; on a degenerate input it is every layer, which is the point of recording
it. `result.detectors` reports which setup detectors ran, were skipped, or failed.

`result.decision` is one of `BUY`, `SELL`, `WAIT` or `NO_TRADE`, with a stable
`reason` code, the full `explanation`, every gate that fired in `vetoes`, and the
`ranking_basis` that chose the candidate. `BUY` means "of the plans that passed
every gate, this one had the most evidence by those criteria" — **not** "this is
more likely to work". Nothing in this project has been validated against outcomes.
Set `AnalyzerConfig(enable_decision=False)` to get `NO_TRADE` /
`DECISION_DISABLED` instead, with the structure and the plans still reported.

Bar indexing is **oldest-first** throughout: index `0` is the oldest bar,
`len(bars) - 1` the newest. This is deliberately the opposite of MetaTrader 5
series indexing, and the conversion is handled only inside the MT5 adapter.

Accepted bar forms are `Bar` objects or plain dicts with `o/h/l/c`
(or `open/high/low/close`) keys.

## Configuration

Every heuristic parameter is configurable via `AnalyzerConfig` and is
serializable:

```python
from albrooks import AnalyzerConfig

config = AnalyzerConfig(
    swing_k=3,
    atr_period=14,
    min_leg_bars=3,
    max_leg_bars=100,
    min_pb_ratio=0.15,
    max_pb_ratio=0.90,
)
payload = config.to_dict()          # JSON-safe
restored = AnalyzerConfig.from_dict(payload)
```

Defaults are documented per section in `docs/algorithms/`.

The `Decision Engine & Gating` block (`enable_decision`, `min_score`, `min_rr`,
`max_late_atr`, `conflict_ppts`, `max_failed_attempts`) was declared in Phase 1 and
consumed by nothing until Phase 15. **All six are live now**, and each one is
asserted by a test to change an outcome — see
[docs/algorithms/DECISION_ENGINE.md](docs/algorithms/DECISION_ENGINE.md) §10.

> `min_score` is on the **0..1** evidence scale, the same scale
> `EvidenceScore.value` uses. It was declared as `40.0`, on a 0-100 scale the
> evidence model never had, which would have rejected every candidate including a
> perfect one. The default is now `0.40`, aligned with `evidence_moderate_band`.

The `plan_*` block moves a trade plan's levels; the `htf_*` block decides how
strictly a higher-timeframe read is held against a decision.

## Trade plans

`albrooks.trade.plan` turns a setup payload into the geometry of a hypothetical
trade — entry, stop, target, reward:risk, what would void the reading behind it —
and reports **where every level came from**:

```python
from albrooks.trade.plan import anatomy_for, build_trade_plan

plan = build_trade_plan(
    "PULLBACK_H",
    {"direction": 1, "reference_price": 104.0, "stop_price": 100.0, "signal_bar": 9},
    bars=bars,
    bar_index=9,
    atr=2.0,
    anatomy=anatomy_for("PULLBACK"),
)
plan.stop, plan.stop_basis      # 99.5, 'PULLBACK_EXTREME'
plan.reward_to_risk             # 0.888...
```

A stop at `99.5` means something different when it came from a pullback's low than
when it came from an ATR multiple, so the basis travels with the price. A level
that had to be invented from volatility is recorded as `ATR_FALLBACK`, raises a
warning, and leaves `has_structural_stop` False.

`is_valid` means the three prices are on the correct sides of each other and
nothing more. A plan is not an order: there is no sizing, no order type, and no
expectation, and `to_dict()` says `"is_recommendation": false`.
See [docs/algorithms/TRADE_PLAN.md](docs/algorithms/TRADE_PLAN.md).

## Decisions

`albrooks.decision` is the one layer that compares setups, and its whole design is
about making the comparison arguable rather than authoritative.

```python
d = result.decision

d["action"]            # "BUY" | "SELL" | "WAIT" | "NO_TRADE"
d["reason"]            # a stable code, not a sentence
d["ranking_basis"]     # the criteria, echoed
d["sides"]             # strongest bull and bear evidence, in points
d["vetoes"]            # every gate that fired, with both numbers compared
d["explanation"]       # ordered prose, the same steps in words
```

`BUY` means *of the plans that passed every gate, this one had the most evidence by
the criteria in `ranking_basis`*. It does **not** mean the trade is more likely to
work: there is no `confidence` field, `is_probability` is `false`, and nothing in
this project has been checked against outcomes.

Two things it refuses to do:

- **It will not promote the least bad candidate.** With every candidate gated out
  the answer is `WAIT` / `ALL_CANDIDATES_VETOED`, with the failing gates named.
- **It will not resolve a contested reading by arithmetic.** Two directions within
  `conflict_ppts` of each other is `WAIT` / `EVIDENCE_CONFLICT`.

Nine gates, eight blocking and one advisory, each in
[docs/algorithms/DECISION_ENGINE.md](docs/algorithms/DECISION_ENGINE.md) §5. No gate
short-circuits, so a candidate that fails four reports four, and every detail names
both numbers it compared.

## Multi-timeframe

`albrooks.engine.pipeline` analyses one timeframe and holds its decision to the
next one up:

```python
from albrooks.engine.pipeline import analyze_multi_timeframe

result = analyze_multi_timeframe(
    m15_bars, h1_bars,       # Bar.time is the bar's OPEN time
    ratio=4,                 # lower bars per higher bar
    symbol="EURUSD", lower_timeframe="M15", higher_timeframe="H1",
)

result.bias.direction        # +1, -1 or 0
result.bias.reason           # HTF_ALIGNED | HTF_NOT_CLASSIFIED | HTF_NOT_ALIGNED | ...
result.alignment.warnings    # MISSING_TIMESTAMPS, TIMEFRAME_RATIO_MISMATCH, ...
result.decision["reason"]    # or AGAINST_HIGHER_TIMEFRAME
```

Alignment works in **close** times, because an H1 bar is not knowable until its
last M15 bar has closed. The newest usable H1 bar at low bar `i` is
`floor((i + 1) / ratio) - 1` — deliberately not `i // ratio`, because a low bar
closing at the same instant as a high bar's close is *inside* that high bar.

The bias **withholds** a decision that runs against it; it never inverts one, since
knowing an M15 long disagrees with an H1 bear is not knowing the long is a short.
Set `htf_opposition_veto=False` to keep the bias as context without gating on it.
See [docs/algorithms/MULTI_TIMEFRAME.md](docs/algorithms/MULTI_TIMEFRAME.md).

## Non-repaint policy

The engine is **closed-bars only** by default. A bar is only used after it has
closed. Structural detections that inherently require right-side confirmation
(such as a fractal swing) are emitted only from the bar that *confirms* them, and
every such detection records its confirmation index.

The invariant enforced by the test suite:

> The analysis for a given bar index is **identical** whether or not later bars
> exist.

That promise is written out as **eighteen numbered guarantees**, each naming the
test that enforces it, in
[docs/algorithms/NON_REPAINT_CONTRACT.md](docs/algorithms/NON_REPAINT_CONTRACT.md).
A test parses that document and fails if a guarantee names a test that does not
exist, so the contract cannot quietly drift from the code.

There is no forming-bar flag, and that is deliberate: freezing a live series is the
**adapter's** obligation, not something the engine can be reminded of. See the
contract's §4.

## Backtesting

`albrooks.backtest.events` walks a series one closed bar at a time, calls
`analyze(bars, last_closed=k)`, and records what the path afterwards did:

```python
from albrooks.backtest.events import Outcome, replay

result = replay(bars, horizon=10)

result.counts()                        # outcome -> count, zeros included
result.sample_share(Outcome.TARGET_FIRST)
result.mean_mfe_atr()
result.skipped                         # why no event was made, per reason code
result.caveats                         # read before the numbers
```

Five outcomes: `TARGET_FIRST`, `STOP_FIRST`, `NEITHER`, `AMBIGUOUS` and
`INVALID_ENTRY`. The last two are things that happened, so they are recorded
rather than tidied away — a bar whose high passed the target while its low passed
the stop is not resolvable from OHLC, and a fill that arrived already through the
stop never existed as a trade. `AMBIGUOUS` is never overwritten on the event; the
resolution is a reporting step whose default is the pessimistic reading.

**It produces no P&L.** No equity curve, no expectancy, no profit factor, no win
rate. Those are the numbers a backtest exists to offer, and each is a claim about
the future that this project cannot support: Phase 19 built a golden fixture
dataset and pointedly did *not* validate against outcomes, because validating
against outcomes needs real labelled data this repository does not have.
`sample_share()` is a proportion of the sample you supplied and is deliberately
not called a win rate.

Three settings worth knowing, because the defaults are the defensible ones rather
than the convenient ones: the fill is the **next bar's open** (the first price
that existed after the decision), overlapping signals are **skipped** (three
decisions in twelve bars are usually one trend counted three times), and ambiguity
resolves to **stop first**. See
[docs/algorithms/BACKTESTING.md](docs/algorithms/BACKTESTING.md).

## Golden fixtures

`tests/fixtures/golden/` holds five hand-authored charts, one per named concept:
an H2 entry, a range breakout, a trend reversal, a micro double top, and a fade of
a measured move.

They are **not** snapshots of the engine's output. A golden file that stores what
the code printed cannot tell a fix from a regression — it fails on both, passes on
neither, and gets updated by pasting the new answer. Each fixture instead pins
specific values, states a reason for every one of them, and carries a list of
**falsifiers**: edits to the bars whose effect the derivation predicts. Those are
assertions about causality, and a snapshot structurally cannot have them.

```python
golden_h2_001    # H2 CONFIRMED, plan clears its own gates
golden_mtr_001   # three of four reversal legs, the missing one named
golden_double_001 # a double is found, and is never actionable
```

Three things this dataset found, recorded rather than quietly fixed:

- **The fade lifecycle is unreachable through the pipeline.** The registry only
  seeds a fade, so a live consumer sees `PROJECTED` with `age 0` for a projection
  the market has already reached. Fixing it means giving a stateless detector a
  stateful responsibility, which belongs with the adapter, not with a test.
- **The pullback window is a configuration choice**, not a reading of price: the
  detector calls the first bar with a higher high the first leg, so in a clean
  uptrend the "pullback" is just the last `max_pb_bars` bars.
- **Two of the three disagreements were our own derivations being wrong**, not
  engine defects. Both are recorded in the fixtures.

**This is a semantic regression suite, not a validation study.** It establishes
what the engine *names* over five hand-drawn charts. It says nothing about whether
any setup works, and
[docs/algorithms/VALIDATION.md](docs/algorithms/VALIDATION.md) §9 lists what would
be needed to change that. What is not built: the MT5 adapter and MQL5 layer
(Phase 21) and the AI/LLM interface (Phase 22).

## Python / MQL5 parity

`tests/parity/` holds the contract an MQL5 port would be compared against: a
**canonical vector** of 33 declared fields — the analysed bar, ATR, the market
state, the swings with both their bar index and their confirmation index, the
detected setups, the plan geometry with the basis of every level, and the
decision with its reason code.

**Nothing has been compared.** No MQL5 build of this engine exists;
`tests/parity/mql5/` is empty and a run reports `UNVERIFIED` — neither a pass nor
a failure, because no comparison happened. The harness is built so that state
cannot be mistaken for a result: a sidecar that did not come from an MQL5 build is
not counted, a sidecar covering less than the full scope is refused, and
`AGREED` requires *every* case to have been compared.

```bash
python -m tests.parity.runner   # exit 2 while nothing is comparable
```

Phase 20 shipped the contract and Phase 21 ships the port, because a
specification written after the port exists is a specification shaped around
whatever the port happened to do. See [docs/PYTHON_MQL5_PARITY.md](docs/PYTHON_MQL5_PARITY.md).

## Testing

```bash
pytest              # full suite
pytest tests/unit   # unit only
ruff check .        # lint
mypy src            # static types
```

## Limitations

- **Al Brooks price action mixes objective geometry with discretionary judgement.**
  Everything here is a *systematic proxy*, labelled as such. Nothing in this
  repository claims to be "exactly what Al Brooks means".
- No profitability, accuracy, or win-rate claim is made. None has been
  statistically validated yet. See `docs/` and [SOURCES.md](SOURCES.md).
- Market context, trend classification, and H2 "quality" are heuristics.
- The engine is not yet statistically calibrated; scores are evidence-weight
  heuristics, not probabilities. **This includes the decision layer**: its ranking
  criteria are the most subjective thing in the project, are declared in
  `RANKING_BASIS`, and are labelled `INTERPRETATION` in
  [CONCEPT_TAXONOMY.md](docs/architecture/CONCEPT_TAXONOMY.md) §4.
- The decision layer's six thresholds are chosen values. `min_rr = 1.0` is a
  convention, not a finding, and changing it changes how many plans are eligible
  rather than how good they are.
- `max_failed_attempts` counts two evidence codes, not failures in general. See
  [DECISION_ENGINE.md](docs/algorithms/DECISION_ENGINE.md) §5.
- The higher-timeframe veto is **one blunt rule**: it knows only that the higher
  proxy reads the other way. That is enough to withhold a signal, not enough to
  reverse one, and a genuine counter-trend trade is indistinguishable from a
  mistake at this resolution.
- The higher-timeframe contribution is a **read, not a strategy**: one higher bar's
  market-state classification, with no higher-timeframe swings, legs or setups of
  its own.
- A single-timeframe `analyze()` has no higher-timeframe context, and its
  explanation says so in the output rather than implying otherwise.
- No backtested performance data ships with this project.
- **No MQL5 parity has been established.** The harness exists and is unfilled:
  there is no MQL5 build, so nothing has been compared, and the runner's verdict is
  `UNVERIFIED` rather than a pass. See
  [PYTHON_MQL5_PARITY.md](docs/PYTHON_MQL5_PARITY.md) §7.

## Documentation

- [ROADMAP.md](ROADMAP.md) — living phase checklist
- [CHANGELOG.md](CHANGELOG.md) — release history
- [SOURCES.md](SOURCES.md) — attribution and provenance
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to help
- [SECURITY.md](SECURITY.md) — reporting vulnerabilities
- [docs/algorithms/](docs/algorithms/) — per-algorithm specifications
- [docs/FM_INDICATOR_AUDIT.md](docs/FM_INDICATOR_AUDIT.md) — reference-project audit

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports, new setup detectors, and
documentation improvements are all welcome.

## Source attribution

This is an independent software implementation of widely known price-action
concepts. See [SOURCES.md](SOURCES.md) for the full account of what was
referenced, what was designed here, and the line between the two.

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

This software is provided for **research and educational purposes only**. It is
not financial, investment, or trading advice. Trading carries substantial risk of
loss. The authors accept no liability for any trading or other loss arising from
use of this software. You are solely responsible for any decision you make.
