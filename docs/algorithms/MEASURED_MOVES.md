# Measured Move Engine Specification

## 1. Overview
The measured move (MM) engine projects a **target price** for the continuation of a
move, using only closed bars. It owns five projection families and nothing else: it
does not judge signal quality, does not fade, and does not trade. The fade lifecycle
(Phase 11) consumes these targets; it does not redefine them.

Every family is a pure function of closed bars plus a reference `ATR`, so the same
call on the same data always returns the same target.

## 2. Shared Geometry

Leg-based families read three consecutive confirmed swings `(A0, A1, B0)`:

| Pattern | A0 | A1 | B0 | Direction | Measured range |
|---|---|---|---|---|---|
| Bull | swing low | swing high | pullback low | `+1` | `A1 - A0` |
| Bear | swing high | swing low | pullback high | `-1` | `A0 - A1` |

**Pullback depth** is the retracement of `B0` against the leg, normalized by the
measured range:

$$
\text{depth} = \begin{cases}
\frac{A_1 - B_0}{A_1 - A_0} & \text{bull} \\[4pt]
\frac{B_0 - A_1}{A_0 - A_1} & \text{bear}
\end{cases}
$$

Shared gates, all of which must hold for a leg-based projection to form:

- chronological order: `A0.bar < A1.bar < B0.bar`
- leg length: `min_leg_bars <= A1.bar - A0.bar <= max_leg_bars`
- leg size: `measured range >= min_leg_atr * ATR`
- pullback length: `B0.bar - A1.bar <= max_pb_bars`

## 3. Families

### 3.1 `REGULAR` — Leg 1 = Leg 2 (AB = CD)
The canonical Al Brooks measured move: the second leg of a trend is expected to
cover roughly the distance of the first.

- Pullback band: `min_pb_ratio <= depth <= max_pb_ratio` (default `0.15 .. 0.90`,
  both bounds inclusive).
- `Target = B0.price +/- measured range`.

A depth below `min_pb_ratio` is not a pullback at all (see `CHANNEL`); a depth above
`max_pb_ratio` means the leg has already been invalidated, because price left the
leg's own range rather than retracing inside it.

### 3.2 `CHANNEL` — shallow-pullback continuation
Identical geometry, but restricted to pullbacks **shallower** than the regular
minimum: `0.02 <= depth < min_pb_ratio`.

This is the flag/flagpole case: a strong trend that pauses only briefly at the prior
high. Because the depth bands are disjoint, `REGULAR` and `CHANNEL` are mutually
exclusive by construction — the same triple can never produce both.
`Target = B0.price +/- measured range`.

### 3.3 `RANGE` — trading-range height breakout
Evaluated on the newest closed bar `B` using the `range_lookback` closed bars that
end one bar before it.

- `height = max(High) - min(Low)` over that window; requires
  `height >= min_leg_atr * ATR`.
- Bull breakout (`B.close > HH`): `Target = B.close + height`.
- Bear breakout (`B.close < LL`): `Target = B.close - height`.
- Inside the range: no projection.

Unlike `REGULAR`, this family needs no completed swing leg — it fires on the breakout
close itself, in either direction, exactly once per qualifying bar.


### 3.4 `GAP` — measuring gap
Every strong trend bar is a breakout, i.e. a gap away from the prior extreme. When
bar `G` satisfies:

- `Range(G) >= min_gap_atr * ATR`
- Bull: `G.low > G-1.high` and `(G.close - G.low) / Range >= 0.75`
- Bear: `G.high < G-1.low` and `(G.high - G.close) / Range >= 0.75`

then the **gap size itself** is the measured impulse:
`gap = G.close - G-1.high` (bull) or `G-1.low - G.close` (bear), gated at
`gap >= 0.25 * ATR`, and `Target = G.close +/- gap`.

### 3.5 `INVERSE` — failed breakout of the leg extreme
When the terminal swing `A1` of a leg is broken and then reclaimed within
`failed_bo_bars` closed bars, the break is treated as a failed breakout and an
opposite projection of the same size is formed. The anchor is the **far side** of
the failure bar, which is the conservative choice:

- Bull leg broken above `A1` then reclaimed -> bearish target
  `low of the failure-high bar - leg range`
- Bear leg broken below `A1` then reclaimed -> bullish target
  `high of the failure-low bar + leg range`

Both the break and the reclaim must be **closes** through `A1`. `INVERSE` is the
weakest family in the engine and is gated separately (`enable_inverse_mm`) so it can
be excluded from live use until it has been reviewed out of sample.


## 4. No-Repaint Contract
- All families read bars `[0 .. last_closed]` only; a `last_closed` beyond the
  available data is clamped rather than rejected.
- Swing families consume only swings whose confirmation bar is `<= last_closed`, so a
  swing can never contribute before its confirmation bar closes.
- The output for a given `last_closed` is therefore **identical** whether or not later
  bars exist. This is asserted directly in the test suite.

## 5. Configuration
| Key | Default | Meaning |
|---|---|---|
| `enable_range_mm` | `True` | Master switch for the `RANGE` family |
| `range_lookback` | `50` | Bars in the pre-breakout range window |
| `enable_channel_mm` | `True` | Master switch for the `CHANNEL` family |
| `enable_gap_mm` | `True` | Master switch for the `GAP` family |
| `min_gap_atr` | `1.0` | Minimum gap-bar range, in ATR multiples |
| `enable_inverse_mm` | `True` | Master switch for the `INVERSE` family |
| `min_leg_atr` | `1.0` | Minimum measured range, in ATR multiples |
| `min_leg_bars` / `max_leg_bars` | `3` / `100` | Leg length bounds, in bars |
| `min_pb_ratio` / `max_pb_ratio` | `0.15` / `0.90` | Regular pullback depth band |
| `max_pb_bars` | `50` | Maximum bars between `A1` and `B0` |
| `failed_bo_bars` | `5` | Inverse break/reclaim window |

> **Deliberate deviation from the reference project.** In `FM-Indicator` the `RANGE`,
> `CHANNEL` and `GAP` families were experimental and defaulted to off. Here they
> default to on, because this module is a framework rather than one strategy: the
> family flags exist to *narrow* the analysis, not to switch it on.

## 6. Usage
```python
from albrooks.core.swings import find_swings
from albrooks.setups.measured_move import detect_measured_moves

swings = find_swings(bars, last_closed_idx=last_closed, k=3)
for p in detect_measured_moves(bars, swings, atr=atr, last_closed=last_closed):
    print(p.family, p.direction, p.target_price, p.to_dict())
```
