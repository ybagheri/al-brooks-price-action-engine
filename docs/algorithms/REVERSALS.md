# Reversals: MTR and MiTR

## 1. Three layers, and why

The specification makes this separation **mandatory**, and it is correct.
Collapsing detection, quality and decision into one function produces a single
number that cannot be reasoned about: "reversal detected, 75/100" hides whether
anything was detected at all, and hides that nobody has decided anything.

| Layer | Function | Answers | Never |
|---|---|---|---|
| Detection | `detect_reversal` | Is the structure present? Which legs? | Computes a score |
| Quality | `assess_reversal_quality` | How many legs, and which are missing? | Searches for a pattern |
| Decision | *Phase 15* | Should anyone act? | Lives anywhere yet |

`analyze_reversal` remains as a convenience wrapper that runs both, and is
byte-equivalent to the pre-refactor behaviour. New code should call the two
layers separately.

A test asserts the separation structurally: `ReversalLegs` has no `score` and no
`verdict` attribute at all.

## 2. The four legs

A Major Trend Reversal is a four-phase sequence:

| # | Code | Test |
|---|---|---|
| 1 | `EMA_BREAK` | close on the reversal side of the 20-EMA, having crossed from the trend side within 10 bars |
| 2 | `EMA_RETEST_HELD` | price returns to the EMA and holds on the far side |
| 3 | `SWING_BREAKOUT_WITH_REVERSAL` | the swing structure breaks **with** the reversal and follows through |
| 4 | `REVERSAL_PRESSURE` | at least 5 consecutive pushes in the reversal direction |

A Minor Trend Reversal satisfies some but not all. `MAJOR` requires all four.

The codes are stable strings, not enum members, because the Phase 13 evidence
model serialises them directly into agent-facing JSON.

## 3. The score is a count

```text
score = 25 * (number of satisfied legs)      # 0, 25, 50, 75, 100
verdict = MAJOR if legs == 4 else MINOR if legs >= 1 else NONE
```

That is the entire formula. A score of 100 means **four of four legs are
present**. It does not mean certain, likely, or profitable. A test asserts the
score is always a multiple of the per-leg weight, which pins it as a count and
prevents it quietly becoming a calibrated probability later.

`satisfied` and `missing` are complementary, and a test asserts that across all
16 leg combinations, so the evidence can never silently under-report.

## 4. What this does not claim

- **`MAJOR` is not more likely to work than `MINOR`.** That ordering is a
  hypothesis for out-of-sample testing, not a measured property.
- The score is not a probability, expectancy, win rate, or confidence interval.
- Leg 3 depends on the breakout engine, so its `FOLLOW_THROUGH` state carries
  that engine's own tolerances and limitations
  (see [BREAKOUTS.md](BREAKOUTS.md)).
- The 5-push pressure threshold, the 10-bar cross lookback and the 0.25 ATR EMA
  tolerance are `HEURISTIC` values chosen by this project.
- A detected reversal is a structure, not a signal. Acting on it is Phase 15.

## 5. Closed-bar contract

Every leg is evaluated on bars up to `last_closed` only.
