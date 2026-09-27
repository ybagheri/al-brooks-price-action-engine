# Concept Taxonomy

Price action mixes objective geometry with discretionary judgement. Presenting
the second as the first is the main way a library like this misleads its users,
so **every feature in this project carries an explicit classification**.

This document defines the labels, explains how to apply them, and records the
classification of everything currently implemented.

## 1. Why this exists

"Trend" is not a thing. It is a judgement a human makes from a picture. A
library cannot reproduce that judgement, and pretending to have reproduced it
produces numbers that look authoritative and are not.

So when this project says `BULL_TREND`, it does not mean "the market is in a
bull trend". It means "a specific documented set of geometric conditions were
met, and here is the exact set". The distinction is the whole point.

## 2. The labels

| Label | Meaning | Example |
|---|---|---|
| `OBJECTIVE` | A geometric or arithmetic fact about the data. No judgement, no parameter choice that could reasonably be called a preference. | A bar's high, low, close. `high - low`. |
| `ALGORITHMIC` | Unambiguously defined by an algorithm, but the algorithm embodies a *choice* of method. Other definitions exist and are also defensible. | Fractal swing detection with `k`-bar wings. |
| `PROXY` | A measurable stand-in for a discretionary concept. The concept has no exact definition, so this is one systematic approximation of it. | Market-state classification from EMA slope, swing counts and bar overlap. |
| `HEURISTIC` | A tunable rule-of-thumb chosen by this project. Defensible, but the specific thresholds are not derivable from first principles. | A 0.15-0.90 pullback depth band for a two-legged pullback. |
| `INTERPRETATION` | A synthesised judgement over multiple inputs. The most subjective layer, and the one most likely to be wrong. | "This market is more likely to continue than reverse." |
| `STATISTICAL` | An empirically calibrated quantity. **Only valid if validated against data, with the validation documented.** | None currently. See §5. |

Two important corollaries:

- `OBJECTIVE` does not mean *useful*. A bar's high is objective and tells you
  very little.
- `HEURISTIC` is not a pejorative. Every threshold in this project is a
  heuristic. The label is there so the reader knows exactly how much weight to
  put on it.

## 3. Required documentation per heuristic

Every non-`OBJECTIVE` feature must document all five of the following. This is
not optional; it is the project's core honesty contract.

1. **What Brooks concept it attempts to represent.**
2. **The exact algorithm**, including formulas and thresholds.
3. **Why this proxy was selected** over plausible alternatives.
4. **What it does NOT claim.** Be explicit and specific here.
5. **Known limitations** and false-positive risks.

The single most important is #4. A `HEURISTIC` that does not state its failure
modes is worse than no heuristic at all, because it invites over-trust.

## 4. Classification of the current implementation

### `core/bars.py` — Bar, BarSeries

| Item | Label | Notes |
|---|---|---|
| `Bar` OHLCV fields, validation | `OBJECTIVE` | Direct from the data feed. |
| Bar-derived geometry (`range`, `body`, wicks, `close_location`) | `OBJECTIVE` | Arithmetic on OHLC. |
| `is_doji` (body ≤ 15% of range) | `HEURISTIC` | The 0.15 threshold is a convention chosen here, not a derivable constant. |
| Oldest-first indexing | `OBJECTIVE` | A deliberate design decision, not a judgement about the market. |

### `price_action/bars.py` — bar-by-bar engine

| Item | Label | Notes |
|---|---|---|
| Range, body, wick sizes, close location | `OBJECTIVE` | Arithmetic. |
| `is_doji` | `HEURISTIC` | Threshold convention. |
| Big bar (≥ 2.0 × ATR), small bar (≤ 0.5 × ATR) | `HEURISTIC` | ATR-relative, but the multiples are chosen values. |
| Strong close (≥ 0.70 of range toward direction) | `HEURISTIC` | A convention about what "strong" means. |
| Inside / outside bar | `OBJECTIVE` | Pure inequalities on OHLC. |
| ii pattern counts | `ALGORITHMIC` | Consecutive-inside-bar run length; unambiguous. |
| Barbwire | `PROXY` | Stands in for "no clear direction, both sides being hit". The Brooks concept is visual; this is a measurable approximation. |
| Pair overlap | `OBJECTIVE` | A defined geometric ratio. |
| Pressure counters | `PROXY` | Stands in for cumulative buying/selling pressure from bar tails. Pressure is psychological; this counts bars. |
| ATR (Wilder) | `ALGORITHMIC` | Standard smoothing method, one of several. |

### `core/swings.py` — swings and pivots

| Item | Label | Notes |
|---|---|---|
| Fractal swing high/low with `k` wings | `ALGORITHMIC` | Unambiguous, but many definitions exist. `k=3` is a choice. |
| Earliest-wins tie-breaking | `ALGORITHMIC` | Chosen to make results deterministic. |
| `confirmed_bar_index = bar + k` | `OBJECTIVE` | The mechanism that makes no-lookahead possible. |

### `core/legs.py` — legs

| Item | Label | Notes |
|---|---|---|
| Leg between consecutive alternate swings | `ALGORITHMIC` | Mechanical. |
| `price_change`, `bars_count` | `OBJECTIVE` | Arithmetic. |
| Leg symmetry ratio | `OBJECTIVE` | A ratio; interpreting it as "balanced" is a judgement. |
| Two-legged structure detection | `ALGORITHMIC` | Mechanical pattern match. |

### `context/market_state.py` — market context

| Item | Label | Notes |
|---|---|---|
| EMA20/EMA50 gap, higher-high counts, overlap ratio | `OBJECTIVE` | Measured values. |
| The six modes and their scoring weights | `PROXY` | **The central proxy of the project.** Stands in for a discretionary read of the chart. |
| `strength` | `PROXY` | A blend of proxy inputs; not a probability. |
| `TRANSITION` mode | `PROXY` | Inferred from conflicting inputs. Heavily interpretive. |

### `core/structures.py` — structures

| Item | Label | Notes |
|---|---|---|
| Climax (range ≥ 2.0 × ATR) | `HEURISTIC` | Multiple is chosen. |
| Stall bar (small range, two-sided wicks) | `HEURISTIC` | Thresholds chosen. |
| Push count (consecutive closes + extremes) | `ALGORITHMIC` | Mechanical. |
| Wedge (shrinking ranges or ≥ 4 pushes) | `PROXY` | Stands in for a drawn wedge shape. |
| Overshoot beyond 20-bar SMA band | `PROXY` | Stands in for "extended too far". The band and 0.3 ATR are chosen. |
| `breadth` count | `OBJECTIVE` | A count of the above. Meaningful only insofar as those are meaningful. |

### `setups/pullback.py` — H1/H2, L1/L2

| Item | Label | Notes |
|---|---|---|
| Trend direction from EMA gap vs 0.4 ATR | `PROXY` | Context gate; a proxy for "is there a trend to pull back in". |
| H1/H2 counting rules | `ALGORITHMIC` | Mechanical once context is assumed. |
| Pullback depth band 0.15-0.90 | `HEURISTIC` | **Chosen by this project.** |
| "Quality" of an H2 | `HEURISTIC` | Not a probability. Not validated. |

### `setups/double.py` — double tops / bottoms

| Item | Label | Notes |
|---|---|---|
| Two swing highs within 0.25 × ATR | `ALGORITHMIC` | Tolerance is configurable and chosen. |
| Separation requirement of 0.5 ATR | `HEURISTIC` | Prevents trivially adjacent bars counting as a double. |
| Major vs micro classification | `OBJECTIVE` | A window-length distinction, not a quality claim. |

### `setups/breakout.py` — breakouts

| Item | Label | Notes |
|---|---|---|
| Breakout of a swing or N-bar reference | `ALGORITHMIC` | With configurable tolerance. |
| State machine transitions | `ALGORITHMIC` | Explicit state graph. |
| `FOLLOW` / `FAILED` classification | `HEURISTIC` | The 0.10 ATR tolerance and window are chosen. |

### `setups/reversal.py` — MTR

| Item | Label | Notes |
|---|---|---|
| EMA20 cross and retest detection | `ALGORITHMIC` | Mechanical. |
| Four-leg MTR sequence | `PROXY` | Stands in for a discretionary structural read. |
| `score` (25 points per satisfied leg) | `HEURISTIC` | **Not a probability.** A transparent checklist count, nothing more. |
| MAJOR vs MINOR threshold | `HEURISTIC` | Chosen. |

### `setups/measured_move.py` — measured moves

| Item | Label | Notes |
|---|---|---|
| Leg geometry and target arithmetic | `OBJECTIVE` | `$T = B_0 \pm (A_1 - A_0)$` is arithmetic. |
| Pullback depth band 0.15-0.90 | `HEURISTIC` | Chosen. |
| CHANNEL band 0.02-0.15 | `HEURISTIC` | Chosen; disjoint from REGULAR by construction. |
| Range height, gap size | `OBJECTIVE` | Once the window is chosen, the arithmetic is exact. |
| Window lengths (50 bars, 20 bars) | `HEURISTIC` | Chosen. |
| INVERSE break/reclaim detection | `ALGORITHMIC` | Mechanical; weakest family, gated separately. |
| Family choice itself | `INTERPRETATION` | Which projection family best describes a given move is a judgement. |

## 5. What is not classified: statistical quantities

No feature in this project is labelled `STATISTICAL`, because **nothing here has
been statistically validated.**

In particular, no `score`, `confidence`, or `strength` value is a probability,
an expected value, a win rate, or a likelihood. They are transparent checklists:
"four of four MTR legs present" is a count, and a count is not a forecast.

If a future validation phase calibrates any of these against historical data,
the calibration method, sample, and confidence intervals must be documented
here — and only then may the label change.

## 6. Wording rules

- Write "systematic proxy for trend", not "trend detection".
- Write "evidence score", not "confidence" or "probability".
- Write "heuristic", not "rule" or "model".
- Never write "this is what Al Brooks means". See [SOURCES.md](../../SOURCES.md).
