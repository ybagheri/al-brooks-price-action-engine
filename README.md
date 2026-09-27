# Al Brooks Price Action Engine

A production-grade, extensible, **platform-independent** Al Brooks price-action
analysis engine written in Python.

> **Persian / فارسی: [README_FA.md](README_FA.md)**

## Purpose

This library turns closed OHLCV bars into structured, explainable price-action
analysis: market context, structural swings and legs, measured-move projections,
setup detection, and — later — trade plans and decisions.

It is an **analytical engine, not a trading system**. It never places orders and
never depends on MetaTrader 5. Platform integration lives strictly in adapters.

## Status

Work is in progress. See [ROADMAP.md](ROADMAP.md) for per-phase status and
[CHANGELOG.md](CHANGELOG.md) for history.

| Area | State |
|---|---|
| Bar-by-bar features | Implemented, unit tested |
| Swings, legs | Partial — pivots pending |
| Market context | Partial — being brought to spec |
| Structures | Partial — being brought to spec |
| H1/H2, L1/L2 | Partial — lifecycle states pending |
| Doubles, breakouts, reversals | Partial |
| Measured moves | Implemented, being aligned to spec model |
| `Analyzer.analyze()` pipeline | Not yet wired |
| Evidence, trade plans, decisions | Not started |
| MQL5 parity, MT5 adapter | Not started |

**Implementation status is not trading validation.** See
[Limitations](#limitations) — no performance claim is made anywhere in this project.

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

print(result.market_state)
for setup in result.setups:
    print(setup)
```

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

## Non-repaint policy

The engine is **closed-bars only** by default. A bar is only used after it has
closed. Structural detections that inherently require right-side confirmation
(such as a fractal swing) are emitted only from the bar that *confirms* them, and
every such detection records its confirmation index.

The invariant enforced by the test suite:

> The analysis for a given bar index is **identical** whether or not later bars
> exist.

See `docs/algorithms/MEASURED_MOVES.md` §4 for a worked example.

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
  heuristics, not probabilities.
- No backtested performance data ships with this project.

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
