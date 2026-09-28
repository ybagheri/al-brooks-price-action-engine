# Evidence Model Specification

## 1. Role

Every layer that reports a finding also reports *why* it fired. Until this phase,
each did so in its own vocabulary, and the only place that met them was
`Analyzer._evidence()` — which produced entries where four of the five sources
had **no `weight` key at all**. A consumer asking "how strong is this" got a
silent `None` for anything except a measured move.

This module gives the five vocabularies one shape, and says plainly what the
resulting number is.

## 2. The six vocabularies

| Source | Its own evidence | Kind of claim |
|---|---|---|
| Market state | `CODE: detail` strings, no weight | mixed: sometimes a magnitude, sometimes a bare flag |
| Measured move | `MeasuredMoveEvidence(code, weight, detail)` | a measured magnitude in 0..1 |
| Reversal | satisfied / missing leg codes, 0-100 count | a discrete count of legs |
| Pullback | lifecycle `state` (`CANDIDATE`..`INVALIDATED`) | a position in a state machine |
| Breakout | `outcome` plus `trap` / `second_leg_trap` | a position plus adverse flags |
| Fading measured move | the projection's evidence **plus** its own lifecycle | a measurement plus a state-machine position |

These are not variants of one thing. Averaging them without distinction would
assert that they mean the same thing, which they do not.

## 3. The load-bearing field: `basis`

`EvidenceFactor.basis` records **why a weight is the number it is**.

| Basis | Meaning | Example |
|---|---|---|
| `MEASURED` | computed from the data against a documented scale | `MM_SCALE` |
| `LIFECYCLE` | a discrete position in a state machine | pullback `CONFIRMED` |
| `ASSERTED` | present, with no magnitude | `RANGE_TIGHTENING_COMPRESSION` |

A number without a basis is a claim waiting to be wrong. `CONFIRMED` is not
"0.75 confirmed"; scoring a state-machine position on a continuum would invent
precision the state machine does not have. Equally, an `ASSERTED` factor is
**not** recorded as `0.0`, which would read as "measured, and came out zero".

`ASSERTED` factors take `UNQUANTIFIED_WEIGHT` (0.5) and are flagged. `quantified_share`
then tells a caller how much of a bundle's evidence was actually measured, so a
"score" that was really a list of flags cannot pass unnoticed.

## 4. Aggregation

`score()` averages **within each source first**, then across sources, so every
contributing source gets an equal say.

A flat mean over all factors would not be neutral: the reversal adapter emits one
factor per satisfied leg while the pullback adapter emits exactly one, so a
four-leg reversal would outweigh a confirmed pullback purely by count. The
per-source means are kept in `EvidenceScore.by_source` so a caller can see which
source moved the number.

The score is a pure function of the bundle's own factors, so it can never drift
away from the evidence it summarises — the same guarantee the measured-move
`confidence` already makes.

### What the number is not

It is **not** a probability, a win rate, an expected value, or a likelihood.
Nothing here has been calibrated against outcomes, so there is no population of
cases to compute a rate against. `CONCEPT_TAXONOMY.md` §5 classifies no value in
this project as `STATISTICAL`, and §6 requires the phrase "evidence score"
rather than "confidence" in prose. `0.8` means "the factors were, on average, at
0.8 of their own scales" — not "this is right 80% of the time".

`EvidenceScore.to_dict()` carries `"is_probability": false` so a downstream
consumer is told rather than left to know.

## 5. Banding

`band()` maps a score to `STRONG` / `MODERATE` / `WEAK` / `NONE`, with thresholds
on `AnalyzerConfig` (`evidence_strong_band`, `evidence_moderate_band`) because
ARCHITECTURE.md §11 requires every threshold to be configurable rather than a
literal inside a detector.

Four bands, not ten. Finer banding would imply a resolution these heuristics do
not have, and a caller who needs the number already has it. An empty bundle is
`NONE`, not `WEAK`: "nothing was observed" and "what was observed was weak" are
different statements.

## 6. What is deliberately excluded

**Negative terminal states are not scored, they are dropped.** An `INVALIDATED`
pullback and a `FAILED` breakout are excluded by their adapters. Folding them in
as a low weight would make a dead setup look like a weak one, and the difference
between "scored badly" and "not a candidate" is exactly the distinction a caller
must not lose.

**Traps are recorded, not subtracted.** A bundle is always a mean of what was
observed, never a number that had things taken away from it. The adverse flags
appear as their own factors with their own codes.

**`compare()` is a presentation helper.** It ranks bundles by score for display,
and is deterministic for equal scores. Ranking two different kinds of claim — a
measured-move target against a reversal leg count — is a judgement this project
has not earned, so nothing downstream may treat its order as a recommendation.
That comparison is the decision engine's job (Phase 15).

**The decision engine is the one place that ranks.** Phase 15 landed, and
`decision.decide()` sorts eligible candidates by
`(-evidence_value, -reward_to_risk, candidate_id)`. It is the narrow exception this
document always pointed at, and the criteria are declared in `RANKING_BASIS` and
echoed in every decision so the ranking can be argued with. It is still a ranking
of transparent criteria with no outcome behind it. See `DECISION_ENGINE.md` §6.

**The model has a consumer.** `Analyzer.analyze()` builds one bundle per setup the
registry found and hands each to the decision layer as a `TradeCandidate`, which
is what `min_score` gates on. The pipeline's own flat `evidence` list keeps its
`source` / `code` / `detail` shape.

## 7. Known limitations

- The lifecycle values used by the pullback adapter (`CANDIDATE` 1/3,
  `PROVISIONAL` 2/3, `CONFIRMED` 1.0) are evenly spaced for stability and
  reproducibility. The gaps are **not** meaningful: a `PROVISIONAL` pullback is
  not "twice as provisional" as a `CANDIDATE` one.
- The market-state adapter reads a trailing number out of a detail string to
  decide whether a factor is `MEASURED`. This works for the current three codes
  and would need revisiting if the market-state engine started emitting
  mid-sentence numbers, which is why the parser only ever reads the last token.
- **`score()` averages within each source, so a bundle with one source scores that
  source's value outright.** A bundle holding only `MARKET_STATE` — which is added
  to every candidate and is identical for all of them — therefore scores at the
  market state's value with no penalty for having observed nothing about its own
  setup. This produced a real inversion in Phase 16, where a fading measured move
  scored 100 ppts on market context alone and outranked a measured move with real
  factors behind it. The decision layer's blocking `NO_OWN_EVIDENCE` gate is the
  structural fix; see `DECISION_ENGINE.md` §5.1.
- The fading-measured-move lifecycle values (`PROJECTED` 0.2, `POTENTIAL` 0.4,
  `DEVELOPING` 0.7, `CONFIRMED` 1.0) are evenly spaced for stability, exactly as
  the pullback adapter's are, and the gaps are **not** meaningful.
  `COMPLETED` and `INVALIDATED` are excluded, for the same reason `FAILED`
  breakouts are.
- `from_fading_measured_move()` was added in Phase 16 for the reason the pullback
  adapter exists: a fade is a lifecycle over someone else's target, and without
  the lifecycle factor the fade and the projection it fades scored **identically**,
  which the decision layer reported as a zero-width `EVIDENCE_CONFLICT` on every
  strong measured move.
- `from_measured_move()` and `from_reversal()` read a payload as readily as a
  model, added in Phase 15. Every detector's public path is `to_dict()`: the
  registry passes findings around as plain dicts and `analyze()` reports them as
  dicts, so an adapter that only understood objects could not reach the
  measured-move and reversal evidence at all. The object is still preferred, and
  a test asserts a payload and its model normalise identically.
- Market-state evidence is added to **every** bundle, because context is part of
  what backs a candidate. A consequence worth knowing: `score()` balances sources,
  so a bundle whose context is mostly bare assertions can score *lower* than the
  same bundle without it. That is the per-source rule working, not a bug.
