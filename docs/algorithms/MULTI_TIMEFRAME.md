# Multi-Timeframe Specification

## 1. Role

Every layer up to this one reasons about **one** timeframe. An M15 bull signal
inside an H1 bear trend and the same signal inside an H1 bull trend were
indistinguishable to the engine, and `DECISION_ENGINE.md` §11 has said so since
Phase 15.

This phase adds the higher-timeframe read and holds the lower-timeframe decision
to it, in `src/albrooks/engine/pipeline.py`. It also completes the pipeline work
deferred since Phase 12: `Analyzer.analyze()` now **reads the setup registry**
rather than calling four detectors directly, so the pipeline holds one detection
path and `setups` covers all eleven shipped detectors.

## 2. Alignment, and why it is the whole problem

An H1 bar is not knowable until its last M15 bar has closed. So the first job is
not "find the H1 trend" — it is **deciding which H1 bars exist yet**.

> **The rule.** `Bar.time` is the bar's **open** time. A higher-timeframe bar is
> usable at lower-timeframe bar `i` only once it has **closed**, i.e. only when
> `htf.time + htf_step <= ltf.time[i] + ltf_step`.

Equivalently, with `r` lower bars per higher bar, the newest usable higher bar is

```text
k = floor((i + 1) / r) - 1
```

which is **not** `i // r`. A low bar closing at the same instant as a high bar's
close is *inside* that high bar, not after it. Getting this wrong by one is
enough to read a whole high-timeframe bar of the future, and it is the specific
mistake the test suite exists to catch: one test makes the *forming* high bar
extreme and asserts the bias does not move.

The alignment works in **close** times, not open times. A naive `htf.time <
ltf.time` test would read the currently-forming high bar and hand the low
timeframe an hour of future prices.

## 3. Timestamps are measured, not parsed

`measure_step()` returns the **mode** of the positive gaps between consecutive
bar times, not the mean. One session break or weekend gap would drag a mean away
from the bar's own period, and a weekend gap used as the step misaligns every bar
after it. Ties break toward the *smaller* gap, so a series of duplicated bars
resolves to its own period.

Nothing here parses a timeframe string. `M15`, `H4`, `D1` and every broker's
spelling of them are too varied to parse reliably, and a mis-parsed timeframe is a
silent misalignment — the worst kind, because the numbers still look reasonable.
`ratio` is **supplied by the caller** and cross-checked against the timestamps.

## 4. Alignment diagnostics

`Alignment` reports what it did and what it could not do:

| Field | Meaning |
|---|---|
| `ratio` | what the caller supplied |
| `ltf_step`, `htf_step` | measured from each series' own timestamps |
| `observed_ratio` | `htf_step / ltf_step` |
| `htf_index` | the newest higher bar that had closed, `-1` if none |
| `warnings` | diagnostics, empty when clean |

| Warning | Meaning |
|---|---|
| `MISSING_TIMESTAMPS` | a series had no measurable step (all `time` are the `0.0` default) |
| `NON_MONOTONIC_TIME` | timestamps do not strictly increase, so a bar cannot be placed in time |
| `TIMEFRAME_RATIO_MISMATCH` | observed ratio differs from the supplied one by more than `RATIO_TOLERANCE` (0.01) |
| `TIMEFRAME_RATIO_NOT_SUPPLIED` | `ratio <= 0`; the alignment proceeds on the timestamps |
| `NO_TIME_OVERLAP` | the two series do not overlap, so no higher bar is ever usable |

Two of these are worth reading closely:

- **A wrong ratio is reported and the alignment still proceeds.** A caller's wrong
  model of their own data is worth saying; it does not make the timestamps wrong,
  and refusing to align would throw away a usable series.
- **`MISSING_TIMESTAMPS` and `NON_MONOTONIC_TIME` stop the alignment entirely.**
  Without a step there are no close times to compare, and bisecting a
  non-monotonic series would answer a question nobody asked.

## 5. The bias

`HTFBias` is the smallest thing that can be true: a direction, the proxy strength
behind it, the mode, the higher bar it came from, and a reason.

The four "no bias" reasons are kept apart, because collapsing them would let a
data problem read as a neutral market:

| `reason` | What it means |
|---|---|
| `HTF_ALIGNED` | a directional read at or above `htf_min_strength` |
| `HTF_NOT_CLASSIFIED` | aligned, but the HTF proxy is a range, a transition, or too weak to lean |
| `HTF_NOT_ALIGNED` | no higher bar had closed yet at this low bar |
| `HTF_NOT_ALIGNED_IN_TIME` | the timestamps could not be lined up at all |

`HTF_NOT_CLASSIFIED` covers both "the market state is invalid because the series is
too short" and "the winning mode's share is below the threshold". Both are
honest readings and neither is a direction, so they share a code; the difference
between them is the `strength` and `mode` fields.

## 6. The bias is a veto input, not a signal

`apply_htf_veto()` withholds a lower-timeframe decision that runs against a
directional bias, as `WAIT` / `AGAINST_HIGHER_TIMEFRAME`, with the bias in the
veto's detail and two extra lines of explanation.

Three things it deliberately does not do:

1. **It does not invert.** The engine knows an M15 long disagrees with an H1 bear.
   It does not know the long is a short, and turning the signal round would be a
   claim this project has not earned.
2. **It does not touch an abstention.** Overwriting a `WAIT` that already had a
   reason would replace a true statement with a weaker one: the higher timeframe
   was not why it waited.
3. **It does not fire on a weak read.** A higher timeframe in `TRADING_RANGE`, in
   `TRANSITION`, or below `htf_min_strength` gives direction `0`, and a direction
   of `0` opposes nothing. A clean trend scores 0.67; a choppy one scores 0.50.
   The default `htf_min_strength = 0.60` therefore requires a *dominant* mode
   rather than a plurality — and a test pins the same fixture vetoing at 0.30 and
   not vetoing at the default, so the gate is provably not trigger-happy.

`htf_opposition_veto = False` reports the same bias without gating on it, for a
caller that treats the higher timeframe as context rather than as a filter.

## 7. How the no-lookahead property is obtained

Not by filtering after the fact — by construction. The higher-timeframe analysis
is run **as of** the aligned bar with `last_closed=k`, the same "analyse as of a
bar" contract every detector in this engine already obeys. The pipeline therefore
never holds a full higher-timeframe result and reaches into it for a historical
bar, because it never holds one.

The invariant, asserted end to end across **both** series:

> The result for a given low-timeframe index is identical whether or not later bars
> are appended to either series.

## 8. What the bias is not

`MarketState.strength` is a **proxy share of score**, not a probability of
continuation, and `htf_min_strength` is a chosen threshold on it. Both are
`HEURISTIC` in `CONCEPT_TAXONOMY.md` §4. "Bullish higher timeframe" means "a
documented set of geometric conditions on the higher series scored highest, and
the winner's share was at least `htf_min_strength`" — not "the market will keep
going up".

## 9. The pipeline reads the registry

The second half of this phase, and the last piece of the `ARCHITECTURE.md` §9
claim that Phases 12 to 15 kept deferring.

`Analyzer.__init__` now takes an optional `registry`, defaulting to
`build_default_registry()`, and `analyze()` runs it over one `SetupContext`. The
direct `analyze_breakout` / `detect_h1_h2` / `detect_l1_l2` / `analyze_reversal`
calls are gone, so there is one detection path rather than two.

Four things changed as a result, and each is asserted:

- **`setups` is complete.** It now covers the doubles and the fading measured
  moves the pipeline never ran itself. `findings` is the same list as the
  registry's normalised form.
- **`detectors` reports what ran.** `executed` names, `skipped` reasons, `failed`
  entries. This is what replaces the not-found payload per family that the old
  direct calls produced: "a detector ran and found nothing", "a detector could not
  be measured" and "a detector raised" are three statements, and an empty list
  expresses none of them.
- **A failure is promoted to a result warning.** The registry contains a raise
  rather than propagating it, so a run can come back with fewer setups than it
  should. `DETECTOR_FAILED:<name>` and `DETECTOR_SKIPPED:<name>` appear in
  `AnalysisResult.warnings` so a broken detector cannot quietly shrink a result.
- **The per-family layers are grouped by family, not by `kind`.** Two of the
  eleven shipped detectors are registered with the default `kind`, so grouping by
  `kind` silently lost them. The family comes from `setups.base.family_for()`,
  which is the single mapping the trade layer and the decision layer also use.

The pipeline's own key for the family is **`setup_family`**, not `family`,
because a payload may already use that name for a narrower classification — a
`MEASURED_MOVE` finding's `family` is `RANGE`, `CHANNEL`, `GAP` or `INVERSE`.
Overwriting it would throw away the projection family.

### Why `DEFAULT_REGISTRY` is still not read

It exists for the mutate-on-import pattern a third party might prefer, but
`Analyzer` does not read it by default. A process-wide mutable global makes
behaviour depend on import order and on test order, so a caller who wants extra
detectors passes `Analyzer(config, registry=...)` instead. That is the difference
between an opt-in and an ambient dependency, and `registry.py` already argues for
it.

## 10. Configuration

| Key | Default | Effect |
|---|---|---|
| `htf_min_strength` | `0.60` | the HTF proxy share at or above which a bias is directional |
| `htf_opposition_veto` | `True` | withhold a decision that runs against a directional bias |
| `htf_report_unclassified` | `True` | report an unclassifiable higher series rather than omitting it |

## 11. Known limitations and false-positive risks

- **The veto is a single, blunt rule.** "The higher timeframe disagrees" is the
  only thing it knows, and a genuine counter-trend trade is indistinguishable from
  a mistake at this resolution. `htf_opposition_veto=False` exists precisely
  because the default is a choice, not a finding.
- **The bias is derived from one HTF bar's classification**, not from a
  higher-timeframe *structure*. There is no HTF swing, leg, or setup analysis, so
  the higher timeframe contributes context and nothing else.
- **Alignment assumes contiguous bars.** A session with gaps, or a series that
  skips a session entirely, still aligns correctly on timestamps — that is the
  point — but a series with *irregular* spacing cannot have a single step, and
  the mode is then whatever spacing is most common.
- **`ratio` is the caller's to get right.** A wrong one is reported and the
  timestamps carry the alignment anyway, so a wrong ratio does not corrupt the
  bias; it does mean the caller's model of their data is wrong somewhere.
- **A fade and a measured move are opposite trades on the same setup.** The
  decision layer treats them as competing readings, which they are, and the
  conflict gate is what stops it choosing between them when the evidence is
  level. The fade's lifecycle factor is what keeps that from being a permanent
  tie on every strong projection.
- **Nothing here has been validated.** A higher-timeframe veto sounds like a
  well-known improvement, and it may well be one — but nothing in this project has
  been checked against outcomes, so the claim here is only that the two readings
  can be compared and the comparison reported.
