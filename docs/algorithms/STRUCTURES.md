# Price-Action Structures

## 1. Scope

Phase 5 produces **facts and structural observations**. Nothing in this layer is
a signal, a direction to trade, or a prediction. An exhaustion reading is not a
reversal; a wedge is not a short; a failed breakout says only that the break
did not hold.

## 2. Concept taxonomy

| Item | Label |
|---|---|
| Push count, run length | `ALGORITHMIC` |
| Overlap, inside/outside, gap geometry | `OBJECTIVE` |
| Edge touch counts | `OBJECTIVE` |
| Climax / stall thresholds | `HEURISTIC` |
| Wedge, overshoot, barbwire, channel | `PROXY` |
| Second-entry geometry | `ALGORITHMIC` |
| "A second entry is more reliable" | **Not claimed.** See §7. |

Full definitions: [CONCEPT_TAXONOMY.md](../architecture/CONCEPT_TAXONOMY.md).

## 3. Module layout

`core/structures.py` is a **facade**. Each concept has one authoritative home:

| Concept | Module |
|---|---|
| Climax / stall classification | `price_action.climaxes` |
| Push runs, strong-bar pressure | `price_action.pressure` |
| Wedge / contraction geometry | `price_action.wedges` |
| Composite exhaustion | `price_action.exhaustion` |
| Overlap, barbwire, inside runs | `price_action.overlap` |
| Micro gaps | `price_action.gaps` |
| Parallel price channels | `core.channels` |
| Trading ranges, breakouts, reclaims | `core.ranges` |
| Second-entry structure | `core.second_entry` |

## 4. Channels

A channel is two **parallel** lines through confirmed swing extremes. Both
boundaries are derived from confirmed swings, so a channel is never published
before the swings defining it have themselves been confirmed.

```text
upper_slope = (H2.price - H1.price) / (H2.bar - H1.bar)
lower_slope = (L2.price - L1.price) / (L2.bar - L1.bar)
```

The direction comes from the slope of the highs. A rising high line with a
falling low line is a **wedge, not a channel**, and is rejected. A channel is
also rejected when the two slopes disagree by more than
`max_parallel_deviation_atr` (0.5) of the larger slope, which is what "parallel"
means here.

Both lines are then projected forward, and the first bar that closes beyond one
of them (by more than `double_tol_atr` ATR) marks the channel broken.

**Limitations.** Parallel construction forces symmetry: an accelerating channel
is not representable, and a decelerating one is reported as broken early. Only
the two most recent touchpoints per side are used. A channel is not support, and
a break is a measurement, not a signal.

## 5. Trading ranges

A range needs **tests on both edges**: `count_edge_touches >= min_touches` (2) on
the high *and* the low, inside the lookback window. A trending market tests the
high repeatedly and the low not at all, so it is correctly rejected.

A bar touches an edge when its extreme reached the level but it did not close
beyond it by more than the tolerance.

**The `hold_bars` design decision.** A range defined by the maximum high of a
window that *includes* the current bar can never be broken by that bar, because
the break would simply redefine the edge. `hold_bars` (default 1) excludes the
newest N bars from the edge calculation, leaving room for a break to be observed
against edges set earlier. Raising it to 2 leaves room for a break *and* a
reclaim. This is why `detect_trading_range` is parameterised here rather than
just extending a window forward.

**Failed breakout.** After a decisive break, price is checked for a close back
inside the range within `failed_bo_bars` (5) bars. That is the reclaim, and
`is_failed` is true only when both are present.

**Limitations.** The edges move as the window advances, so the same range seen at
a later bar may differ. That is inherent to a window-based definition, not
repainting. Callers needing a frozen range should anchor it explicitly. Touch
counting is tolerance-sensitive.

## 6. Exhaustion

Five conditions, each measured separately, then counted into `breadth` (0-5):

| Condition | Test | Needs |
|---|---|---|
| `climax` | `range >= big_bar_atr * ATR` | ATR |
| `stall` | small range, tails both sides | ATR |
| `push_ok` | `pushes >= max(2, min_pushes)` | — |
| `wedge` | decelerating run | — |
| `overshoot` | extreme past a 20-bar SMA band by `> 0.3 ATR` | 20 bars |

Overshoot band:

```text
bull: high > max(SMA20, HH - 0.2 * (HH - LL)) + 0.3 * ATR
bear: low  < min(SMA20, LL + 0.2 * (HH - LL)) - 0.3 * ATR
```

## 7. Second entry

The pattern, oldest to newest:

```text
push (entry 1)  ->  counter-move  ->  push (entry 2)
```

Entry 2 is the directional run ending at the analysis bar. The counter-move
between the entries must be at least `min_pullback_atr` (0.5) ATR deep, measured
from entry 1's extreme to the far side of the counter-move -- **not** to entry
2's extreme, which may already be beyond entry 1 and would make the depth
negative. `extends` records whether entry 2 exceeded entry 1's extreme, but is
reported rather than required.

**What this does not claim.** That a second entry is more reliable than a first
is an `INTERPRETATION` and is not asserted anywhere in this project. This module
reports that the structure is present. Two entries is a small sample, and it is
not evidence of an edge.

## 8. Configuration

| Key | Default | Used by |
|---|---|---|
| `big_bar_atr` | `2.0` | climax |
| `small_bar_atr` | `0.5` | stall |
| `min_pushes` | `3` | `push_ok` |
| `use_wedge` | `True` | wedge detection on/off |
| `overlap_ratio` | `0.50` | barbwire, chop |
| `failed_bo_bars` | `5` | reclaim window |
| `double_tol_atr` | `0.25` | channel break tolerance |

Window parameters (`lookback`, `min_touches`, `hold_bars`, `min_pullback_atr`,
`max_separation`) are function parameters rather than global config, since they
are situational tuning rather than engine-wide policy.
