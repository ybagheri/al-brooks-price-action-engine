# Evidence Model Specification

## 1. Role

Every layer that reports a finding also reports *why* it fired. Until this phase,
each did so in its own vocabulary, and the only place that met them was
`Analyzer._evidence()` — which produced entries where four of the five sources
had **no `weight` key at all**. A consumer asking "how strong is this" got a
silent `None` for anything except a measured move.

This module gives the five vocabularies one shape, and says plainly what the
resulting number is.

## 2. The five vocabularies

| Source | Its own evidence | Kind of claim |
|---|---|---|
| Market state | `CODE: detail` strings, no weight | mixed: sometimes a magnitude, sometimes a bare flag |
| Measured move | `MeasuredMoveEvidence(code, weight, detail)` | a measured magnitude in 0..1 |
| Reversal | satisfied / missing leg codes, 0-100 count | a discrete count of legs |
| Pullback | lifecycle `state` (`CANDIDATE`..`INVALIDATED`) | a position in a state machine |
| Breakout | `outcome` plus `trap` / `second_leg_trap` | a position plus adverse flags |

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

## 7. Known limitations

- The lifecycle values used by the pullback adapter (`CANDIDATE` 1/3,
  `PROVISIONAL` 2/3, `CONFIRMED` 1.0) are evenly spaced for stability and
  reproducibility. The gaps are **not** meaningful: a `PROVISIONAL` pullback is
  not "twice as provisional" as a `CANDIDATE` one.
- The market-state adapter reads a trailing number out of a detail string to
  decide whether a factor is `MEASURED`. This works for the current three codes
  and would need revisiting if the market-state engine started emitting
  mid-sentence numbers, which is why the parser only ever reads the last token.
- The model is not yet consumed by `Analyzer.analyze()`. The pipeline's own
  `evidence` list is unchanged; wiring the two together is Phase 16's pipeline
  work, and doing it here would have changed output the existing pipeline tests
  pin.
