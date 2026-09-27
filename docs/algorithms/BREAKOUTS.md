# Breakout Engine

## 1. State machine

```text
NONE -> PENDING -> BREAKOUT -> FOLLOW_THROUGH
                  \-> FAILED
```

| State | Meaning |
|---|---|
| `NONE` | No breakout reference has been cleared. |
| `BREAKOUT` | The current bar cleared the reference. No follow-through exists yet. |
| `PENDING` | An earlier bar cleared it; nothing has resolved either way. |
| `FOLLOW_THROUGH` | A later bar extended beyond the reference again. |
| `FAILED` | A later bar closed back on the original side. |

`BREAKOUT` and `PENDING` are deliberately distinct. A caller acting on the
breakout bar is acting *before* any follow-through exists, and collapsing the two
would hide that. `is_resolved` is `True` only for `FOLLOW_THROUGH` and `FAILED`.

`outcome` is retained as the historical field (`PENDING` / `FOLLOW` / `FAILED`)
so existing callers keep working; `state` carries the fuller machine.

## 2. Reference selection

A breakout is a **close** beyond a reference, by more than `0.10 * ATR`:

1. The most recent confirmed **swing** extreme on that side, if the close clears it.
2. Otherwise the **N-bar** range extreme (default 20 bars, minimum 10).

A swing reference takes precedence when both would qualify, because a level
price actually reversed from is more meaningful than a window edge. The choice
is recorded in `reference_kind` (`SWING`, `N_BAR`, `CHANNEL`).

**Channel breakouts** (`detect_channel_breakout`) project the channel boundary
forward from the channel's own last touchpoint, rather than from a moving window
edge, and are reported with `reference_kind="CHANNEL"`.

## 3. Failed versus pending

`FAILED` takes precedence: if any bar after the breakout closed back through the
reference, that is the resolution, and follow-through is not considered. A
breakout can be `FAILED` and still have extended further before failing.

## 4. Second-leg trap

A breakout's **second leg** is the move that lures in late followers. If price
extends beyond the reference and then reverses back through it, the late
followers are trapped. `detect_second_leg_trap` returns the reclaim bar.

Separately, `trap` on `BreakoutResult` answers a different question: was there an
**earlier same-direction breakout within 20 bars that also failed**? That is a
repeat-attempt pattern, not a second leg, and the two are reported as distinct
fields.

## 5. Breakout pullback

A pullback into a breakout is the retest. It is recorded when price returns
within tolerance of the reference **without** closing through it. A close back
through the reference is a failure, not a pullback, and is reported by the state
machine instead — so the two can never both be true for the same bar.

## 6. What this does not claim

- **`FOLLOW_THROUGH` is not more likely to continue than `FAILED` is to
  reverse.** That ordering is a hypothesis for out-of-sample testing.
- A second-leg trap is not a reliable short. It identifies where late followers
  would have been caught, nothing about what happens next.
- The `0.10 * ATR` tolerance, the 5-bar search window and the 20-bar N-bar
  reference are `HEURISTIC` values chosen by this project.
- A breakout detected on the reference bar tells you nothing about follow-through
  until a later bar closes. That is what the `BREAKOUT` vs `PENDING` split
  encodes.

## 7. Closed-bar contract

Every transition is evaluated on closed bars only, and the search never reads
past `last_closed`.
