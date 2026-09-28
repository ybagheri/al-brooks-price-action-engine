# Decision Engine Specification

## 1. Role

Every layer below this one reports **what the structure is**. This is the layer
that answers a different question: **which of those, if any, is the one to act
on** — and it is also the layer that says *none of them*, which is an answer too.

`ROADMAP.md` records that this project does not rank competing setups and that the
comparison "belongs" here. So this phase does rank. The whole design is about
making that ranking **auditable rather than authoritative**.

## 2. What a decision is not

**It is not a validated edge.** The ranking criteria are declared
(`RANKING_BASIS`), applied in one fixed order, and echoed in every decision's
output. Two candidates with identical evidence and identical reward:risk are
separated only by a name, so the result is reproducible — and still unvalidated.
Nothing in this project has been checked against outcomes
(`CONCEPT_TAXONOMY.md` §5), so:

- there is no `confidence` field, and `Decision.to_dict()` carries
  `"is_probability": false`;
- `CONCEPT_TAXONOMY.md` §6's wording rule (evidence score, never confidence) is
  why the gate is `min_score` and not `min_confidence`;
- the explanation of a ranked decision says, in the output, that this is a
  comparison and not an edge.

**It is not an order.** No sizing, no order type, no session, no slippage. See
`ROADMAP.md` → *Deliberately Not Built*.

**It does not infer a trade it was not given.** With candidates that all fail, the
answer is `WAIT` with the failing gates named. Ranking the least bad candidate
would be a recommendation this layer has not earned, and §5 explains why that
sentence is there.

## 3. The four actions

| Action | `reason` | Meaning |
|---|---|---|
| `NO_TRADE` | `DECISION_DISABLED` | `enable_decision=False`. The engine declines to answer. |
| `NO_TRADE` | `NO_ANALYSIS` | No volatility reference, so no gate could be evaluated. |
| `NO_TRADE` | `NO_CANDIDATES` | Nothing was found, or nothing could be ranked. |
| `WAIT` | `ALL_CANDIDATES_VETOED` | Candidates existed; every one failed a blocking gate. |
| `WAIT` | `EVIDENCE_CONFLICT` | Both directions eligible, neither dominating. |
| `BUY` / `SELL` | `RANKED_CANDIDATE` | A ranked candidate, with its plan and the full explanation. |

`NO_TRADE` versus `WAIT` is a real distinction, not a formality. "I have nothing
to say" and "I have something and it does not meet the conditions" call for
different behaviour from a caller, and collapsing them would make an empty result
read as a judgement. `enable_decision=False` is `NO_TRADE`, never `WAIT` and
never an inferred trade — that is the one setting where a plausible-looking `BUY`
would be indefensible.

`Decision.is_actionable` is about the **action**, not the geometry. A plan can be
perfectly well formed and still not be something to act on.

## 4. The evidence scale, stated once

The evidence score is **0..1** (`EvidenceScore.value`). Two things here speak a
different scale and say so in the field name:

- `candidate.evidence_ppts` — the same number as percentage points, 0..100.
- `min_score` — on the 0..1 scale.

> **A default that was wrong, and what it would have done.** `min_score` was
> declared in Phase 1 as `40.0`, on a 0-100 scale. The Phase 13 evidence model
> produces 0..1, so as soon as the key was read it rejected **every** candidate,
> including a perfect one, and the decision layer would have answered
> `WAIT` / `ALL_CANDIDATES_VETOED` on every input forever. The default is now
> `0.40`, aligned with `evidence_moderate_band`. The key was documented as
> unwired for three phases precisely so that nobody was misled by it in the
> meantime; the ROADMAP's table carried the wrong number until this phase.

## 5. Gates (`decision/veto.py`)

A veto is a statement about a **single** candidate. It cannot mention another
candidate, so a veto list can never become a hidden ranking — which is why the
module exists separately from the engine.

| Code | Blocking | Key | The comparison |
|---|---|---|---|
| `NO_DIRECTION` | yes | — | The setup named no direction, so the plan is neither a buy nor a sell. |
| `INVALID_GEOMETRY` | yes | — | The plan's own levels are inconsistent (`TradePlan.issues`). |
| `TERMINAL_SETUP` | yes | — | The setup reached `FAILED` / `INVALIDATED`. |
| `NO_ATR` | yes | — | No volatility reference, so no ATR-relative gate was evaluable. |
| `EVIDENCE_TOO_WEAK` | yes | `min_score` | Evidence score below the limit. |
| `RISK_REWARD_TOO_LOW` | yes | `min_rr` | `reward_to_risk` below the limit. |
| `TRADE_IS_LATE` | yes | `max_late_atr` | `abs(close - entry) / atr` above the limit. |
| `TOO_MANY_FAILED_ATTEMPTS` | yes | `max_failed_attempts` | Adverse observations above the limit. |
| `NO_OWN_EVIDENCE` | yes | — | The bundle says nothing about this setup — only shared market context. Added in Phase 16; see §5.1. |
| `VOLATILITY_STOP_ONLY` | **no** | — | The stop is an ATR fallback, not a level the market produced. |
| `AGAINST_HIGHER_TIMEFRAME` | yes | `htf_opposition_veto` | Raised by `engine/pipeline.py`, not by a gate here. `MULTI_TIMEFRAME.md` §6. |

Four properties, all asserted in the test suite:

1. **No gate is short-circuited.** A candidate that fails four gates reports four,
   because a reader fixing one condition should not have to re-run to find the
   next.
2. **Every detail names both numbers.** A veto that only said
   `EVIDENCE_TOO_WEAK` would be unfalsifiable.
3. **Every threshold is a chosen number, not a calibrated one.** Setting
   `min_rr = 3.0` does not make a 3.1 plan better; it makes fewer plans eligible.
   All six gates are `HEURISTIC` in `CONCEPT_TAXONOMY.md` §2. `INVALID_GEOMETRY`
   and `NO_DIRECTION` are the exceptions — they carry no threshold at all.
4. **One advisory veto, and it is advisory on purpose.**
   `VOLATILITY_STOP_ONLY` marks a plan that is geometrically valid and
   structurally empty. Excluding it would be a judgement about what constitutes a
   real setup, which the engine has not earned; reporting it costs nothing and is
   the difference between a caller who can see the weakness and one who cannot.

### `max_failed_attempts` counts a deliberately narrow thing

The count is the plan's terminal flag plus every evidence factor whose code is in
`ADVERSE_EVIDENCE_CODES` — currently `BREAKOUT_TRAP` and `SECOND_LEG_TRAP`, the
only negative observations the Phase 13 adapters emit. An `INVALIDATED` pullback is
**excluded** by its adapter rather than scored, so it never reaches a count here.

That is a real limitation, not an oversight, and it is recorded rather than
papered over by widening the list. To make the count mean what its name suggests,
the evidence model has to be able to count failures.

The fading-measured-move lifecycle arrived in Phase 16, so a fade's state is now a
factor. Counting *failed* fades still needs the terminal states to be recordable
rather than excluded, which is a change to the adapters rather than a wider
constant here.

### 5.1 A candidate must say something about its own setup

`NO_OWN_EVIDENCE` is blocking, and it is the least obvious gate in the table.

`score()` averages **within** each source and then across sources, so a bundle
holding a single source scores that source's value outright. Market-state context
is added to *every* bundle — correctly, because it is part of what backs a
candidate — and it is identical for all of them, so on its own it says nothing
about any one setup. A bundle with nothing but context therefore scores at the
market state's value with **no penalty for having observed nothing**.

That produced a real inversion when Phase 16 started the pipeline reading the
registry: a fading measured move, whose evidence adapter did not exist, scored
100 ppts on market context alone, outranked a measured move with real measured
factors behind it, and then manufactured an `EVIDENCE_CONFLICT` against the real
read. Two fixes are in place — the fading adapter, and this gate — and the second
is the structural one: a missing adapter for any family now yields a *refused*
candidate rather than a plausible-looking one.

## 6. Ranking

```text
pool = eligible candidates on the dominant side
sort key = (-evidence_value, -reward_to_risk, candidate_id)
winner  = pool[0]
```

`RANKING_BASIS` is that list in prose, and it is echoed in every decision:

```text
evidence_score (0..1, higher first)
reward_to_risk (higher first)
candidate_id (ascending, for reproducibility only)
```

The `candidate_id` is `"<detector>#<position in the findings>"`. It exists so
that a run over the same findings always produces the same decision, and so that
the two genuinely different criteria cannot be confused with a third: the name
tie-break is only ever reached when the first two agree exactly.

The dominant side is the one whose **strongest** eligible candidate has the
higher `evidence_ppts`. Using the maximum rather than the mean is deliberate: a
side is represented by its best reading, and averaging would let three weak
candidates on one side outvote one strong candidate on the other.

## 7. Conflict

```text
contested = there is an eligible candidate on each side
gap       = abs(bull_ppts - bear_ppts)
conflict  = contested and gap < conflict_ppts
```

A gap exactly at the limit is **resolved**, not conflicted: the limit is
exclusive. One side alone can never be in conflict.

`WAIT` / `EVIDENCE_CONFLICT` is the right answer here and not a fudge. Two
readings that differ by less than `conflict_ppts` evidence points are a
disagreement, and picking the numerically larger one would be a claim about which
disagreement to believe.

## 8. Candidates

`TradeCandidate` is a plan, the bundle of evidence behind it, and the score
derived from that bundle, travelling together. The score is computed **once, at
construction**, so the number a gate reads and the number the decision reports
cannot be two different calculations of the same bundle.

`candidates_from_findings()` wraps registry-shaped `SetupFinding`s in the order
they arrived, preserving that order into `candidate_id`. A finding whose payload
is not a mapping is skipped rather than raising: one malformed detector must not
take the rest of the candidates down.

`bundle_for()` maps a family to its Phase 13 adapter and **adds the market-state
evidence to every bundle**. Context is part of what backs a candidate — the same
pullback in a strong trend and the same pullback in a tight range are not the
same claim — and a bundle that omitted it would score them identically. A family
with no adapter contributes no factors rather than a wrong number.

Note that adding context can *lower* a score: `score()` balances sources, so a
second source whose factors are mostly bare assertions pulls the aggregate down.
That is the Phase 13 rule working. A test asserts the contribution, not a rise.

## 9. The closed-bar contract

The decision reads the close at `last_closed` for the lateness gate, and
`last_closed` is clamped rather than rejected, matching every detector in the
engine. Nothing else is read, so the invariant holds:

> The decision for a given bar index is **identical** whether or not later bars
> exist.

The gate most likely to break it is `TRADE_IS_LATE`, and it is asserted
explicitly: appending bars must not move a decision dated at an earlier index.

## 10. Configuration

| Key | Default | Gate |
|---|---|---|
| `enable_decision` | `True` | whole layer; `False` answers `NO_TRADE` |
| `min_score` | `0.40` | `EVIDENCE_TOO_WEAK` |
| `min_rr` | `1.0` | `RISK_REWARD_TOO_LOW` |
| `max_late_atr` | `0.50` | `TRADE_IS_LATE` |
| `conflict_ppts` | `10.0` | `EVIDENCE_CONFLICT` |
| `max_failed_attempts` | `2` | `TOO_MANY_FAILED_ATTEMPTS` |

These six were declared in Phase 1 and consumed by nothing until this phase. That
gap was documented in `ROADMAP.md` and the README rather than left as a mystery,
and a test now asserts that each one changes an outcome — which is the only way
they stop being decorative again.

## 11. Known limitations and false-positive risks

- **Nothing here has been validated against outcomes.** The backtesting interface
  (`albrooks.backtest`, Phase 18) reports path geometry and outcome classes and
  deliberately produces no win rate; the golden fixtures (Phase 19) establish what
  the engine *names* over five hand-drawn charts and nothing more. `BUY` means
  "of the plans that passed every gate, this one had the most evidence by the
  criteria in §6". See `VALIDATION.md` §1 and §9.
- **A single-timeframe `analyze()` has no higher-timeframe context.** The
  explanation says so in its own output, because it is a true statement about the
  result. `engine/pipeline.py` supplies the higher-timeframe read and withholds a
  contraindicated decision; the single-timeframe entry point deliberately does not,
  so a caller that never asked for a second series is never silently given one.
- **`max_failed_attempts` counts two things.** See §5.
- **The evidence score is an average over sources, and the market-state source is
  identical for every candidate on a run.** Context therefore compresses the
  differences between candidates rather than creating them. That is a property of
  the Phase 13 aggregator, and it means `min_score` is partly a market filter. It
  is also why `NO_OWN_EVIDENCE` exists — see §5.1.
- **A `WAIT` is not a "probably later".** It means a stated condition was not met.
  Nothing here forecasts timing.
- **There is no exit logic.** A plan has an invalidation sentence; this layer
  never evaluates one, and a decision is made once, at a bar.
