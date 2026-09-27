# Fading Measured Move (FM) Specification

## 1. Role

The measured-move engine (Phase 10) answers *where* price is projected to go. This
module answers the separate question a trader actually asks of a projection: **as
price approaches that target, is there reason to expect it to stop and reverse?**

It consumes projections and never produces them. The dependency direction is fixed
and one-way:

> **FM consumes MeasuredMove. MeasuredMove must never depend on FM.**

## 2. The lifecycle

```text
PROJECTED ──► POTENTIAL ──► DEVELOPING ──► CONFIRMED ──► COMPLETED
     │            │            │             │
     └────────────┴────────────┴─────────────┴──► INVALIDATED
```

| State | Entered when | Terminal |
|---|---|---|
| `PROJECTED` | the projection forms; `created_bar` is recorded | no |
| `POTENTIAL` | the bar's extreme comes within `fm_approach_atr` of the target | no |
| `DEVELOPING` | price *touches* the target **and** exhaustion is present | no |
| `CONFIRMED` | a reversal signal bar in the fade direction, at the target | no |
| `COMPLETED` | one closed bar after `CONFIRMED` | yes |
| `INVALIDATED` | a close overshoots the target by `fm_over_atr`, or the projection expires | yes |

**At most one transition per closed bar.** A projection can never skip from
`PROJECTED` to `CONFIRMED` on a single bar, so the sequence is always auditable bar
by bar. A state may also step *backwards* — `DEVELOPING` returns to `POTENTIAL` when
price leaves the target zone — and that is intentional: the lifecycle reports where
price actually is, not the furthest point it once reached.

## 3. Transition order, and why it is that order

Inside a single bar the checks run in a fixed order:

1. **Expiry** (`age > fm_max_bars_forward`).
2. **Invalidation by overshoot** (close beyond the target by `fm_over_atr`).
3. The current state's own advance.

Expiry and overshoot are checked first, and independently of state, because both are
disqualifying regardless of what else the bar did. Checking them later would let a
single bar reach `CONFIRMED` and then be invalidated, leaving a projection that was
confirmed and dead in the same bar. It would also let an ancient projection be
revived by a bar that merely happened to sit near its target.

## 4. Fading discipline

**Touch is not a fade.** This is why `POTENTIAL` and `DEVELOPING` are separate
states. Reaching a projected target is common and means nothing on its own; reaching
it *with exhaustion* is the observation. `CONFIRMED` requires more again — an actual
signal bar.

The module **fades the target zone, never the trend**, and produces no entry, stop,
size, or order. The states are observations about how price behaved around a
projection. `FadingSetup` stores the projection's `direction` and the
`fade_direction` separately, because a bull projection is faded short and conflating
the two is the easiest way to fade a trend by mistake.

## 5. Measurements

### 5.1 Approach (`PROJECTED` → `POTENTIAL`)

`0 <= distance <= fm_approach_atr * ATR`, where `distance` is measured from the bar's
extreme *in the projection's direction* — the high for a bull projection, the low for
a bear one. The lower bound of zero matters: a bar that has already overshot the
target is not approaching it.

### 5.2 Touch and exhaustion (`POTENTIAL` → `DEVELOPING`)

`|distance| <= fm_tol_atr * ATR` **and** `detect_exhaustion(...).breadth >= 1`. The
exhaustion reading is the five-condition structure from
`price_action/exhaustion.py`: climax, stall, pushes, wedge, overshoot.

> **Known interaction worth knowing about.** The specification says "touch alone
> stays `POTENTIAL`", which implies a touch with *no* exhaustion is reachable. With
> this engine's exhaustion conditions it very nearly is not. The `overshoot`
> condition fires when the bar's extreme sits more than `0.3 ATR` past a 20-bar band
> **and is the extreme of that window** — and a bar touching a measured-move target
> is by construction the extreme of the recent range. So `overshoot` alone usually
> satisfies the gate on the touching bar.
>
> The gate is kept because it is the specification's rule, it is what stops a touch
> with no exhaustion at all from advancing, and a future tightening of the exhaustion
> conditions would make it bind harder. But it binds more loosely than the wording
> suggests, and
> `test_a_touch_is_almost_always_accompanied_by_exhaustion_here` records that so a
> change to `detect_overshoot` is noticed rather than discovered.

### 5.3 The signal bar (`DEVELOPING` → `CONFIRMED`)

Four requirements, all of which must hold, plus an optional fifth:

| Requirement | Test |
|---|---|
| Direction | the bar's body points the fade way |
| Body | `body / range >= fm_min_body` |
| Close | the close sits in the extreme `fm_close_pct` of the range |
| Adverse wick | `adverse / range <= fm_max_wick` |
| Engulfing (optional) | engulfs the prior body and is at least as large |

The adverse-wick test is what separates a genuine reversal bar from one that merely
closed lower while being sold into all the way to its low. Engulfing defaults to
**off**: it is the strictest of the five and would suppress most otherwise valid
signals.

With `fm_require_ft` set, confirmation is deferred until the *next* closed bar
extends beyond the signal bar's extreme. A fade confirmed by a bar that has not yet
had the chance to fail is not confirmed.

### 5.4 Invalidation

A **close** beyond the target by more than `fm_over_atr * ATR` invalidates the
projection from any active state. The test is on the close rather than the extreme
because a wick through the target that closes back inside it is a failed break, not

## 6. What this does not claim

- A `CONFIRMED` fade is **not** more likely to work than a `POTENTIAL` one. That
  ordering is a hypothesis for out-of-sample testing, not a measured property.
- No state is a probability. Nothing here is calibrated against outcomes, and no
  performance claim is made anywhere in this project.
- `COMPLETED` is **not** a verdict that the fade was right. It records only that the
  lifecycle ended.
- `INVERSE` projections are the weakest input and are gated by `fm_enable_inverse`.

## 7. Configuration

| Key | Default | Meaning |
|---|---|---|
| `fm_approach_atr` | `1.0` | ATR multiple at which a projection becomes `POTENTIAL` |
| `fm_tol_atr` | `0.25` | ATR multiple defining "at the target" |
| `fm_over_atr` | `0.50` | close beyond the target that invalidates |
| `fm_require_ft` | `False` | defer confirmation by one bar, requiring follow-through |
| `fm_enable_inverse` | `True` | include `INVERSE` projections |
| `fm_max_bars_forward` | `100` | bars before a projection expires |
| `fm_min_body` | `0.30` | signal-bar body as a share of its range |
| `fm_close_pct` | `0.50` | required share of the range the close must sit in |
| `fm_max_wick` | `0.60` | maximum adverse wick as a share of the range |
| `fm_require_engulf` | `False` | require the signal bar to engulf the prior body |
| `fm_max_active` | `20` | most projections tracked at once |
| `fm_recent_swings` | `8` | recent swing triples scanned for projections |

## 8. Closed-bar contract

`update_setups` clamps `idx` to `last_closed`, so a caller cannot advance the
lifecycle using bars it declared unavailable. Output for a given `last_closed` is
identical whether or not later bars exist, as everywhere else in the engine.

## 9. Usage

```python
from albrooks.price_action.bars import calculate_atr_series
from albrooks.setups.fading_measured_move import track_fading_measured_moves

atr = calculate_atr_series(bars, period=14)[-1]
setups = track_fading_measured_moves(
    bars, last_closed=len(bars) - 1, atr=atr, swings=swings
)
for s in setups:
    if s.state in ("DEVELOPING", "CONFIRMED"):
        print(s.state, s.family, s.target_price, s.reason)
```

an overshoot.

Expiry at `fm_max_bars_forward` bars (default 100) bounds how long a projection stays
alive. Both terminal states freeze: a projection that has played out is returned
unchanged by later updates rather than being dropped or revived.
