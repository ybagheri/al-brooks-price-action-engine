# Contributing

Thanks for your interest. This project is a long-term open-source effort and
contributions are welcome — including bug reports and documentation fixes.

## Before you start

This is a **price-action analysis library**, not a strategy. Please read:

- [SOURCES.md](SOURCES.md) — what may and may not be contributed
- [README.md](README.md) §Limitations — what this project does and does not claim

## Hard rules

1. **No proprietary material.** Do not paste text, charts, or exercises from
   books, courses, webinars, or any paid source. Short terminology and
   original technical prose only. See [SOURCES.md](SOURCES.md).
2. **No profitability claims.** Do not describe a detector as "accurate",
   "profitable", or "high win rate" unless you are supplying rigorous, documented
   statistical validation. This applies to code comments, docstrings, and PR
   descriptions alike.
3. **No lookahead.** Every detector must consume closed bars only. If a
   structural detection needs right-side confirmation, it must be emitted from
   the confirming bar and must record its confirmation index. See
   `docs/algorithms/MEASURED_MOVES.md` §4 for the invariant the suite enforces.
4. **Label heuristics.** Mark each feature as `OBJECTIVE`, `PROXY`, `HEURISTIC`
   or `INTERPRETATION` in its documentation, and state what it does **not** claim.
5. **No duplicated algorithms.** Reuse `core/` primitives. If you find yourself
   recomputing swings or legs inside a new detector, use the existing engine.
6. **Dependency direction is strictly downward:**

   ```text
   Core primitives → Structure → Context → Patterns → Setups
                  → Evaluation → Decision → Adapters
   ```

   Fading may depend on MeasuredMove; MeasuredMove must never depend on Fading.

## Environment

```bash
pip install -e ".[dev]"
```

Requires Python 3.10+. The core must stay dependency-free; if you believe a new
runtime dependency is justified, open an issue and argue the case first.

## Checks

All three must pass before you push:

```bash
ruff check .
mypy src
pytest
```

## Tests

Every new algorithm needs tests. The suite should cover, as applicable:

```text
unit · integration · regression · edge cases
lookahead / repaint · state transitions · serialization
```

Tests must be **deterministic** and must not depend on live market data. Prefer
synthetic bar series built by a helper, and assert exact expected values rather
than "it does not crash". A test that only checks the absence of an exception is
not a real test.

For a new detector, the minimum is:

- one test per happy path,
- one per gate or threshold boundary (including the exact boundary value),
- one proving it rejects invalid input (zero ATR, too-short series, bad ordering),
- one proving **no lookahead**, if it reads bars.

## Adding a setup detector

Setups must be addable **without modifying the central analyzer**. Implement the
`SetupDetector` protocol and register it. If you find yourself editing
`engine/analyzer.py` to add your detector, the architecture is wrong — please
raise it.

## Documentation

Documentation is a first-class deliverable here, not an afterthought.

- Every algorithm gets its own document under `docs/algorithms/`.
- Include exact formulas, thresholds, and their config keys.
- State known limitations and false-positive risks.
- Public API changes need a docstring; behaviour changes need a
  [CHANGELOG.md](CHANGELOG.md) entry.

## Commit messages

Conventional commits, scoped by layer:

```text
feat(core): add pivot detection
feat(price-action): split pressure into its own module
feat(setups): add fading measured move
test(parity): add Python/MQL5 parity fixtures
docs: add bilingual architecture documentation
fix(context): exclude unconfirmed swings from state scoring
```

One meaningful change per commit. Please do not mix unrelated phases.

## Pull requests

1. Branch from `main`.
2. Make the change, with tests and docs.
3. Ensure `ruff`, `mypy` and `pytest` all pass.
4. Update [ROADMAP.md](ROADMAP.md) if you complete a phase.
5. Describe **what** changed and **why**, and be explicit about anything you are
   unsure of. Honest uncertainty is far more useful than a confident guess.

## Reporting bugs

Open an issue with the smallest reproduction you can manage — ideally synthetic
bar data. If the bug involves lookahead or repainting, say so explicitly; those
are treated as high severity.

## Code of conduct

Be respectful and constructive. Assume good faith. Technical disagreement is
expected and healthy; personal attacks are not.

## Licence

Contributions are accepted under the [MIT Licence](LICENSE).
