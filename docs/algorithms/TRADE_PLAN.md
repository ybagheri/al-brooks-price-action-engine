# Trade Plan Specification

## 1. Role

Every layer up to setup evaluation reports *what the structure is*. A trade plan
is the first layer to answer a different question: **where would the levels be**,
if a trade were taken.

It is the narrowest layer in the project. A `TradePlan` is entry, stop, target,
the arithmetic between them, a statement of what would void the reading behind
them, and the reasons it could not build them. It is the layer the architecture
diagram places between setup evaluation and the decision engine
(`ARCHITECTURE.md` §2).

## 2. What a plan is not

**It is not a recommendation.** `to_dict()` carries `"is_recommendation": false`,
so a consumer is told rather than left to know. A plan exists for a reader who
already has a reading of the market and wants the geometry checked.

**It is not a ranking.** `plans_from_findings()` returns plans in the order the
findings arrived — the registry's registration order, which the registry
documents as deterministic and explicitly not a ranking. Plans are not sorted by
reward:risk, for the same reason `evaluation.compare()` refuses to be a
recommendation.

**It is not an order.** There is no order type, lot size, position sizing,
slippage or session filter anywhere in this module. Order types belong to the
execution layer (Phase 21); sizing needs an account risk policy this project does
not have. See `ROADMAP.md` → *Deliberately Not Built*.

**No number in it is a probability.** `reward_to_risk` is arithmetic.
`CONCEPT_TAXONOMY.md` §5 classifies nothing here as `STATISTICAL`, because
nothing has been validated against outcomes, and §6 asks for "heuristic" rather
than "model" in prose. A 3.0 reward:risk does not mean this trade is good.

## 3. The load-bearing idea: every level carries a basis

A stop at `101.20` means something different depending on where it came from.
This is Phase 13's `basis` field applied to prices, and it is the reason a plan
is not simply three floats.

| `entry_basis` | Claim |
|---|---|
| `SETUP_REFERENCE` | the price the setup itself recorded |
| `LAST_CLOSE` | the close of the plan's bar, because the setup named no price |

| `stop_basis` | Claim |
|---|---|
| `PULLBACK_EXTREME` | the low the pullback was built on |
| `BREAKOUT_REFERENCE` | the level that was broken |
| `PATTERN_EXTREME` | the adverse extreme of a double top / bottom |
| `SWING` | the most recent confirmed swing against the trade |
| `ATR_FALLBACK` | **no structural claim at all** |
| `NONE` | no stop could be built |

| `target_basis` | Claim |
|---|---|
| `MEASURED_MOVE` | a projection's own `target_price` |
| `FADE_ORIGIN` | where the projected move started — what a fade aims back at |
| `SWING` | the most recent confirmed swing in the trade's direction |
| `ATR_FALLBACK` | **no structural claim at all** |
| `NONE` | no target could be built |

The `ATR_FALLBACK` rows are the point. A plan without a stop is not a plan, so
when a setup names no level one is produced anyway — and it is recorded as a
volatility multiple, raises `VOLATILITY_FALLBACK_STOP` /
`VOLATILITY_FALLBACK_TARGET`, and leaves `has_structural_stop` False. A reader
can therefore never mistake a 1-ATR default for a swing low the market made.

## 4. Derivation

Let `E` be the entry, `A` the ATR at the plan's bar, `B` the configured buffer,
and `away = +1` for a long and `-1` for a short.

### Entry

1. The first key in the family's `entry_keys` that carries a usable price. Basis
   `SETUP_REFERENCE`.
2. Otherwise the close at `bar_index`. Basis `LAST_CLOSE`.

A price is "usable" only if it is finite and strictly positive. `0.0` is
rejected on purpose: every model in this engine uses `0.0` as the *not observed*
default for a price, so accepting it would read a placeholder as a level.

### Stop

1. The family's own `stop_keys` value, **or** the adverse extreme of its
   `stop_extreme_keys`: the **minimum** across them for a long, the **maximum**
   for a short. A double bottom's stop belongs below *both* lows.
2. Otherwise the most recent confirmed swing that is strictly on the protective
   side of the entry — the newest confirmed swing **low** below `E` for a long,
   the newest confirmed swing **high** above it for a short. Basis `SWING`.
3. Otherwise `E - away * plan_fallback_stop_atr * A`. Basis `ATR_FALLBACK`.

Steps 1 and 2 are then buffered clear of the level:
`stop = reference - away * B`, where `B = plan_stop_buffer_atr * A`.

The fallback is a volatility **distance**, not a volatility buffer. Applying the
buffer to the entry instead would produce a `plan_stop_buffer_atr`-wide stop,
which is the opposite of what `plan_fallback_stop_atr` means.

### Target

1. The family's own `target_keys` value, **if strictly ahead of the entry**.
2. Otherwise the most recent confirmed swing in the trade's direction. Basis
   `SWING`.
3. Otherwise `E + away * plan_fallback_target_atr * A`. Basis `ATR_FALLBACK`.

A projected target that is *behind* the entry is dropped rather than used with a
negative reward — it means the projection and the entry describe different
things — and `PROJECTED_TARGET_BEHIND_ENTRY` records that it happened.

### Risk and reward

```text
risk            = |E - stop|
reward          = |E - target|
reward_to_risk  = reward / risk   (0.0 when risk == 0)
risk_to_reward  = risk / reward   (0.0 when reward == 0)
```

Both directions are named explicitly rather than shipping a bare `ratio`, so no
consumer has to guess which convention it is reading. `reward_to_risk` pairs with
`AnalyzerConfig.min_rr`, which the decision engine reads as a gate.

`reward_to_risk` is `0.0` rather than `inf` at zero risk: `inf` travels into
JSON as a non-standard literal, and a plan with no risk is not a good plan — it
is not a plan.

## 5. Issues are arithmetic; warnings are judgement-adjacent

`issues` holds only statements that are **false about the numbers**. A plan
carrying one has `is_valid == False`.

| Issue | Meaning |
|---|---|
| `NO_DIRECTION` | the setup named no direction |
| `NO_ATR` | no volatility reference, so nothing can be expressed as a multiple |
| `ENTRY_UNDEFINED` | no setup price and no bar to read a close from |
| `STOP_UNDEFINED` | no stop could be built |
| `STOP_NOT_PROTECTIVE` | the stop is not on the protective side of the entry |
| `TARGET_UNDEFINED` | no target could be built |
| `TARGET_NOT_AHEAD` | the target is not in the trade's direction |
| `RISK_NOT_POSITIVE` | entry and stop are the same price |

`STOP_NOT_PROTECTIVE`, `TARGET_NOT_AHEAD` and `RISK_NOT_POSITIVE` are decided by
`TradePlan.__post_init__`, **not** by the builder, so a `TradePlan` assembled by
a caller or a future layer cannot be `is_valid` with geometry it does not have.
The rest genuinely need the inputs to judge.

A wrong-side stop is reported rather than clamped. Clamping would invent a level
nobody chose, and "the setup's stop is on the wrong side" is exactly the kind of
fact a reader needs.

`warnings` holds everything the layer noticed and **deliberately did not act
on**: `VOLATILITY_FALLBACK_STOP`, `VOLATILITY_FALLBACK_TARGET`, `STOP_WIDE`,
`PROJECTED_TARGET_BEHIND_ENTRY`, `TERMINAL_SETUP_STATE`,
`EVIDENCE_SCORE_IS_NOT_A_PROBABILITY`.

**Gating on warnings is the decision engine's job**, and it now exists: Phase 15
reads `TERMINAL_SETUP_STATE` as the blocking `TERMINAL_SETUP` gate, and adds
`NO_DIRECTION`, `NO_ATR`, `EVIDENCE_TOO_WEAK`, `RISK_REWARD_TOO_LOW`,
`TRADE_IS_LATE` and `TOO_MANY_FAILED_ATTEMPTS` beside it
(`DECISION_ENGINE.md` §5). This layer reports geometry; it does not decide which
geometry is worth taking. A plan whose risk exceeds `plan_max_stop_atr` is still
returned, still `is_valid`, and carries `STOP_WIDE` — and `min_rr`, not
`plan_max_stop_atr`, is what the decision layer gates on. Deciding it here would
be doing the decision engine's work without the explanation machinery that makes
its output auditable.

A setup in a terminal negative state — a `FAILED` breakout, an `INVALIDATED`
lifecycle — raises `TERMINAL_SETUP_STATE` and is still planned. Its geometry is
coherent arithmetic; whether a failed breakout deserves a plan is a different
question, and hiding the plan would remove the reader's chance to ask it.

## 6. One builder, a table of anatomies

The setup families record their geometry in incompatible places. A pullback
carries `stop_price` and `reference_price`; a measured move keeps its origin
nested under `origin.price`; a fading setup's *trade* direction is
`fade_direction`, not `direction`; a reversal carries no prices at all. Writing
five builders would duplicate the level-derivation algorithm five times, which
`CONTRIBUTING.md` rule 5 forbids.

`SetupAnatomy` is therefore a row of **data**, and `build_trade_plan()` is the
single algorithm that reads it. Keys are dotted paths, tried in order, so a
nested field is addressable without anybody flattening a payload.

| Family | Direction | Entry | Stop | Target |
|---|---|---|---|---|
| `PULLBACK` | `direction` | `reference_price` | `stop_price` | swing / ATR |
| `BREAKOUT` | `direction` | last close | `reference_price` | swing / ATR |
| `MEASURED_MOVE` | `direction` | `origin.price`, `reference_price` | swing / ATR | `target_price` |
| `FADING_MEASURED_MOVE` | `fade_direction`, `direction` | last close | swing / ATR | `projection.origin.price` |
| `REVERSAL` | `direction` | last close | swing / ATR | swing / ATR |
| `DOUBLE_TOP` / `DOUBLE_BOTTOM` | `direction` | last close | min/max of `price1`, `price2` | swing / ATR |

Two rows are worth reading twice:

- **A breakout has no entry key.** A breakout is entered *on the break*, and its
  reference is a level price is leaving, not one it trades at. The entry falls
  back to the close and says so via `LAST_CLOSE`.
- **A fade reads `fade_direction` first.** `FadingSetup.direction` is the
  *projection's*. Reading it as the trade direction produces a plan in the
  direction of the move being faded.

Adding a family is a table entry, the same one-change rule `ARCHITECTURE.md` §9
states for setup detectors. An unknown family is not an error: a third-party
detector still gets a plan, built from `DEFAULT_ANATOMY`, which derives every
level and says so.

## 7. The closed-bar contract

`build_trade_plan()` reads bars `0..bar_index` and nothing after it. The entry
fallback is the close at `bar_index`, and a swing is usable only when its
`confirmed_bar_index` is at or before `bar_index` — a fractal swing is not
knowable until `k` bars after it happens, and letting it decide a stop dated
before its own confirmation is lookahead.

`bar_index` is clamped to the series rather than rejected, matching every
detector in the engine, and a negative index becomes `ENTRY_UNDEFINED` rather
than an exception.

The invariant asserted by the suite:

> The plan for a given bar index is **identical** whether or not later bars exist.

## 8. Configuration

| Key | Default | Used for |
|---|---|---|
| `plan_stop_buffer_atr` | `0.25` | buffer beyond a structural level |
| `plan_fallback_stop_atr` | `1.0` | stop distance when no structure exists |
| `plan_fallback_target_atr` | `2.0` | target distance when nothing lies ahead |
| `plan_max_stop_atr` | `3.0` | `STOP_WIDE` threshold |

All four are on `AnalyzerConfig` because `ARCHITECTURE.md` §11 requires every
threshold to be configurable rather than a literal inside a detector. They are
`HEURISTIC`: the multiples are chosen values, not derivable ones.

## 9. Known limitations and false-positive risks

- **A double top/bottom's own measured target is not computed.**
  `DoublePattern` records the two extremes but not the neckline-to-extreme
  height a double target needs, and this project will not invent a geometry the
  detector did not record. The target is a swing or a volatility multiple, and
  `DOUBLE_TARGET_NOT_MEASURED` is carried on every such plan.
- **A reversal plan has no structural levels at all.** `ReversalResult` is a
  checklist of satisfied legs. Every level is derived, `has_structural_stop` is
  False, and `REVERSAL_HAS_NO_LEVELS` says why.
- **The volatility fallback is the common case, not the exception.** Only the
  pullback and breakout families always carry a structural stop. A reader who
  filters on `has_structural_stop` will discard most plans, and that is the
  intended reading rather than a bug.
- **The buffer is a fixed fraction of ATR**, so a stop through a level that
  mattered *more* than usual is not treated differently. A wider buffer per setup
  type would be a judgement this layer does not make.
- **A swing stop is only as good as the swing detector.** `SWING` is a basis, not
  a validation; a fractal at `k=3` can be a level the market ignored.
- **The plan layer is in `Analyzer.analyze()`.** It arrived with Phase 15, the
  phase that needed it: `AnalysisResult.trade_plans` is populated and
  `layers["trade_plans"]` is `True`. It plans **only the setups the registry
  found**, so wiring it in could not introduce a new lookahead surface. Since
  Phase 16 that is all eleven shipped detectors, doubles and fading measured
  moves included.
- **No plan here has been checked against an outcome.** The backtesting interface
  (`albrooks.backtest`, Phase 18) reports path geometry and produces no P&L, and
  the golden fixtures (Phase 19) establish only what the engine *names*. Nothing
  in this document is a performance claim, and a plan is not a recommendation
  (`to_dict()` carries `is_recommendation: false`). See `VALIDATION.md` §1.
