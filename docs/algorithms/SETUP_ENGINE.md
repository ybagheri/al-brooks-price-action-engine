# Setup Engine Specification

## 1. Role

Phases 2-11 produced eleven setup detectors, each written against the shape its
own phase needed. This module gives them one way to be called, so that adding a
twelfth is a registration rather than an edit to the orchestrator.

`ARCHITECTURE.md` §9 states the rule this exists to satisfy:

> New setups must be addable **without modifying the central analyzer.** If adding
> a detector requires editing `engine/analyzer.py`, the architecture has been
> violated and that should be raised rather than worked around.

## 2. The problem

The detectors do not share a signature. They genuinely differ:

| Detector | Signature | Returns |
|---|---|---|
| `detect_h1_h2` | `(bars, idx, last_closed, atr, config)` | one `PullbackSetup` |
| `analyze_breakout` | `(bars, idx, last_closed, atr, swings, config)` | one `BreakoutResult` |
| `find_major_double_top` | `(swings, atr, config)` — **no bars at all** | one `DoublePattern` |
| `detect_measured_moves` | `(bars, swings, atr, last_closed, legs, config)` | a **list** |
| `create_setups` | `(bars, last_closed, atr, swings, legs, config)` | a **list** |

One detector does not read bars. Two return lists while four return a single
object. A registry that has to know all of that is not a protocol, it is a switch
statement — and a switch statement is exactly the thing that has to be edited
when a detector is added.

## 3. The three pieces

### 3.1 `SetupContext` — one input, named

Everything a detector might need, present and named: `bars`, `last_closed`, `atr`,
`config`, `swings`, `legs`, and `idx`.

Passing a single context rather than a long parameter list is what lets a
detector declare only what it uses, and lets an input be added later without
touching any signature. `idx` defaults to `last_closed` because that is the
common case, and is separate from it because some detectors reason about a bar
other than the newest.

`is_usable` is the honesty gate. Every detector here gates on ATR multiples, so a
context with no volatility would produce a confident, entirely plausible "nothing
found" for a market that was never measured.

### 3.2 `SetupFinding` — a thin, uniform wrapper

A name, a `kind`, a direction, and the detector's own payload dict. It is
deliberately thin and it **does not rank anything**. Comparing setups is Phase
15's job, and a ranking produced here would be a claim this engine has not
earned. `SetupFinding` exists so a caller can ask "what fired, in which
direction" without knowing which detector fired it.

### 3.3 `SetupDetector` — one method

```python
def detect(self, context: SetupContext) -> list[SetupFinding]: ...
```

Deliberately one method. Anything a registry needs in order to *decide* —
enablement, ordering, priority — belongs in the registration record, not in extra
protocol methods every implementation would have to supply and most would answer
with a constant.

## 4. `adapt()` — the bridge

`adapt(name, call, ...)` wraps a detector of any existing shape as a
`SetupDetector`, so no detector had to be rewritten to be registered. Three hooks
exist because "is this a finding, and in which direction?" cannot be inferred
uniformly:

| Hook | Default | Needed for |
|---|---|---|
| `expand` | a list return is already the set of findings | nested returns |
| `present` | `payload.get("found", True)` | a model using `found` to mean something narrower |
| `direction` | the shared `direction` field | the fade adapter (see §6) |

Extra `**kwargs` pass through untouched, which is how a detector's own
`reversal_direction` or `level` argument is supplied.

## 5. What the registry deliberately does not do

**It does not rank.** There is no "best setup" and no score. A measured-move
target and a reversal signal are different kinds of claim, and picking between
them is a trade decision — one that belongs to the decision engine (Phase 15), not
to a lookup table. Findings come back in **registration order**, which is
deterministic and predictable, and is not a ranking.

## 6. Two decisions worth stating

**A broken detector is contained.** One that raises is recorded as a
`DetectorFailure` and the run continues, because one broken detector must not take
down the ten beside it — and a caller needs to *know* it happened rather than
silently receiving fewer findings. `strict=True` re-raises for callers who would
rather stop than receive a partial answer.

**Skipped is not the same as found-nothing.** A detector skipped for a missing
ATR reference is recorded in `run.skipped` with a reason (`NO_ATR`,
`NO_CLOSED_BARS`). An empty `findings` list means "we ran the detectors and they
found nothing"; a populated `skipped` means "we could not measure this". The two
are different claims and are kept apart.

## 7. A finding about the presence rule

The default presence rule is `payload.get("found", True)` — a payload that says
`found=False` is not a finding, and a payload that never mentions `found` **is**
one.

`FadingSetup` has no `found` field at all, so the default already treats it
correctly and the fade adapter's `present=` hook is a statement of intent rather
than a fix. It is kept because a `found` field added to `FadingSetup` later, or a
tightening of the default, would otherwise start silently dropping terminal fades
from the output. This is pinned by a test
(`test_the_default_presence_rule_needs_no_override_for_a_foundless_model`) rather
than left to a comment.

## 8. Known limitations

- `DEFAULT_REGISTRY` is a process-wide mutable global, provided so a third party
  can register a detector on import. `build_default_registry()` is preferred in
  library code and tests, because a shared mutable global makes test order matter.
  A test pins that the two are independent.
- The registry is not yet consulted by `Analyzer.analyze()`, which still calls its
  detectors directly. The architecture claim of §9 is about adding a detector
  without editing the analyzer, and `build_default_registry()` satisfies it; wiring
  the pipeline to *read* the registry is Phase 16's pipeline work.
