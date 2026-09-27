# Market Context Engine

## 1. The honest framing

`BULL_TREND` in this engine does **not** mean "the market is in a bull trend".
It means: a documented set of geometric conditions scored highest over a
specific window. "Trend" is not a thing in the data; it is a judgement a human
makes from a picture. A library that reports it without that framing produces
numbers that look authoritative and are not.

The most important sentence in this document is that one. Everything else is
mechanics.

## 2. Concept taxonomy

| Item | Label |
|---|---|
| EMA20/EMA50 gap, higher-high counts, overlap ratio | `OBJECTIVE` |
| Window span in ATR, bar overlap ratio | `OBJECTIVE` |
| The six modes and their scoring weights | `PROXY` |
| `strength` | `PROXY` (a share of a vote, **not** a probability) |
| `TRANSITION` | `PROXY`, the most interpretive output here |

## 3. Module layout

`context/market_state.py` is an **orchestrator**. Measurements live beside it:

| Module | Supplies |
|---|---|
| `context.trend` | EMA slope, directional pressure |
| `context.channel` | bar-overlap chop |
| `context.trading_range` | window span, compaction, balance |
| `context.breakout_mode` | range tightening |
| `context.market_state` | sums, normalises, picks the winner |

Each measurement module exposes a `raw_score(s)` function returning
un-normalised contributions, so the scoring formula is readable in one place
and the inputs are testable in isolation.

## 4. The six modes

```text
BULL_TREND  BEAR_TREND  BULL_CHANNEL  BEAR_CHANNEL  TRADING_RANGE  BREAKOUT_MODE
```

plus `TRANSITION` when no mode clears the score floor, and `UNKNOWN` when the
engine is disabled or there is not enough history.

### Raw scores

```text
BULL_TREND      = bull_slope + bull_pressure + expand
BEAR_TREND      = bear_slope + bear_pressure + expand
BULL_CHANNEL    = bull_slope + chop + compact
BEAR_CHANNEL    = bear_slope + chop + compact
TRADING_RANGE   = compact + chop + balance
BREAKOUT_MODE   = tight + compact + chop
```

### Inputs

| Input | Definition | Range |
|---|---|---|
| `slope` | `clamp((EMA20 - EMA50) / (2 * ATR), -1, 1)` | -1..1 |
| `pressure` | net strong bull/bear bars over the lookback | -1..1 |
| `chop` | fraction of recent bar pairs overlapping `>= overlap_ratio` | 0..1 |
| `span_atr` | `(window high - window low) / ATR` | 0.. |
| `expand` | `clamp01((span - 3.0) / 3.0)` | 0..1 |
| `compact` | `clamp01((6.0 - span) / 4.0)` | 0..1 |
| `balance` | `1 - abs(pressure)` | 0..1 |
| `tight` | newest bar range below the median of the prior four | bool |

Percentages are distributed by largest-remainder so they sum to exactly 100 and
are deterministic.

## 5. The `state` / `mode` alias

`mode` is the canonical field. `state` is retained as an alias for backward
compatibility, and a test asserts they never diverge. Both appear in
`to_dict()`.

`direction` is `+1` for bull-leaning modes, `-1` for bear-leaning, `0` for
neutral modes (`TRADING_RANGE`, `BREAKOUT_MODE`, `TRANSITION`).

## 6. What `strength` is not

`strength` is the winning mode's share of the vote, in 0..1. It is **not**:

- a probability of continuation,
- an expected value,
- a confidence interval,
- a win rate.

A test asserts it cannot exceed 1, that the reported mode is always the one
holding the largest share, and that the shares sum to 100 -- so the field
cannot quietly drift into a probability claim as the engine evolves.

## 7. What this does not claim

- The mode is not a prediction. `BULL_TREND` is not "price will go up".
- A mode can be wrong for many bars before it changes. The engine has no
  smoothing beyond the window itself.
- The windows (20 bars state, 10 bars overlap) are chosen values, not derived
  ones, and are not volatility-adaptive.
- Chop and compactness overlap heavily: a quiet, overlapping market scores well
  for both `TRADING_RANGE` and the channel modes. Which one wins is decided by
  the independent slope input, not by a clean separation of the concepts.
- `BREAKOUT_MODE` is ranked to lose to any genuine directional mode, so
  compression alone will not be reported as a breakout setup. That is a
  deliberate ranking, not a measured one.

## 8. Configuration

| Key | Default | Meaning |
|---|---|---|
| `state_lookback` | `20` | Bars in the range window |
| `state_overlap_bars` | `10` | Bars in the chop window |
| `enable_market_state` | `True` | Master switch |
| `pressure_lookback` | `10` | Bars in the pressure window |
| `strong_close_pct` | `0.70` | Close position for a "strong" bar |
| `min_body_pct` | `0.30` | Body fraction for a "strong" bar |
| `overlap_ratio` | `0.50` | Overlap fraction for the chop count |
