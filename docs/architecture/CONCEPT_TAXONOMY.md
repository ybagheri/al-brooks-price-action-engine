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

### `trade/plan.py` — trade plans

| Item | Label | Notes |
|---|---|---|
| `risk`, `reward` (`abs` differences) | `OBJECTIVE` | Arithmetic on three prices. |
| `reward_to_risk` | `OBJECTIVE` | A ratio. Interpreting it as "worth taking" is a judgement this layer does not make. |
| `issues` (`STOP_NOT_PROTECTIVE`, `TARGET_NOT_AHEAD`, `RISK_NOT_POSITIVE`) | `OBJECTIVE` | Decided from the numbers themselves, in `__post_init__`, so a plan cannot be assembled that omits them. |
| `NO_DIRECTION`, `NO_ATR`, `*_UNDEFINED` | `OBJECTIVE` | Facts about the inputs. |
| `warnings` (`STOP_WIDE`, `TERMINAL_SETUP_STATE`, ...) | `PROXY` | Noticeable conditions reported **without** acting on them. Gating is the decision engine's job. |
| Stop / target basis (`PULLBACK_EXTREME`, `SWING`, `ATR_FALLBACK`, ...) | `OBJECTIVE` | Which of the setup's own levels the price came from. The *choice* of level is the heuristic below. |
| Buffer `0.25` × ATR beyond a structural level | `HEURISTIC` | Chosen. A level that mattered more than usual is not treated differently. |
| Fallback stop `1.0` × ATR, fallback target `2.0` × ATR | `HEURISTIC` | Chosen. **A multiple, not a claim about structure** — which is why it is labelled `ATR_FALLBACK` and warned about. |
| Which level to prefer when a setup offers several | `HEURISTIC` | The `SetupAnatomy` table's ordering. Chosen here, not derivable. |
| "A target behind the entry is dropped" | `HEURISTIC` | The projection and the entry disagreeing is a statement; what to do about it is a choice. |
| Anything about whether the trade is good | **not classified** | Deliberately absent. `reward_to_risk` is not a probability and no threshold is applied to it here. |

### `decision/` — the decision layer

| Item | Label | Notes |
|---|---|---|
| The four actions and their reason codes | `ALGORITHMIC` | A fixed graph: disabled / un-analysable / nothing found / all gated / conflicted / ranked. |
| `issues` consumed as blocking gates | `OBJECTIVE` | A broken stop or a target behind the entry is a fact, and the plan has already said so. |
| `NO_DIRECTION`, `NO_ATR` gates | `OBJECTIVE` | Facts about the input. |
| `min_score`, `min_rr`, `max_late_atr`, `conflict_ppts`, `max_failed_attempts` | `HEURISTIC` | **Every one of them.** Chosen thresholds on transparent numbers. Setting `min_rr` to 3.0 does not improve a 3.1 plan; it makes fewer plans eligible. |
| `max_late_atr` as a measure of staleness | `HEURISTIC` | A chosen reading of "late" — drift from the entry, not wrongness. |
| `max_failed_attempts` over `ADVERSE_EVIDENCE_CODES` | `HEURISTIC` | A narrow count (two codes) standing behind a broader name. `DECISION_ENGINE.md` §5. |
| The sort order `(-evidence, -reward:risk, id)` | `INTERPRETATION` | **The most subjective thing in the project.** It is a judgement about what makes a reading better, made with no outcome behind it. Declared in `RANKING_BASIS` and echoed in every decision so it can be argued with. |
| "The strongest candidate represents its side" | `INTERPRETATION` | A maximum rather than a mean, so three weak candidates cannot outvote one strong one. A choice, and a debatable one. |
| `EVIDENCE_CONFLICT` at `WAIT` | `INTERPRETATION` | Refusing to resolve a near-tie is a judgement — the one place this project declines to pick the larger number. |
| `BUY` / `SELL` | **not classified** | Deliberately absent. `Decision.to_dict()` carries `is_probability: false`; there is no `confidence` field in this project, and the gate is `min_score` for the reason §6 gives. |

### `engine/pipeline.py` — multi-timeframe

| Item | Label | Notes |
|---|---|---|
| `floor((i + 1) / r) - 1` — the newest usable higher bar | `OBJECTIVE` | Arithmetic on timestamps. Correct only because `Bar.time` is the open time and the comparison is on closes. |
| `measure_step` — the modal timestamp gap | `ALGORITHMIC` | Unambiguously defined, but a choice among mean, mode and last value; the mode is chosen because one session gap must not become the bar period. |
| `is_usable`, the `NO_*` reasons, the four bias reasons | `ALGORITHMIC` | A fixed vocabulary. The point of it is that distinct failures stay distinct. |
| `htf_min_strength` (0.60) | `HEURISTIC` | Chosen. A clean trend scores 0.67 and a choppy one 0.50, so the default requires a dominant mode rather than a plurality. |
| `htf_opposition_veto` | `HEURISTIC` | A policy choice with a documented off switch, because the default is a choice and not a finding. |
| `ratio` supplied rather than parsed | `ALGORITHMIC` | Every broker's timeframe spelling differs; a mis-parse is a silent misalignment. |
| "The higher timeframe disagrees, so withhold" | `INTERPRETATION` | The layer's one judgement, and a blunt one. A genuine counter-trend trade is indistinguishable from a mistake at this resolution. |
| Treating a contraindicated move as a short | **not built** | Deliberately refused. Knowing the two disagree is not knowing which to trade. |
| Whether a higher-timeframe bias improves outcomes | **not classified** | Deliberately absent, and not claimed. Nothing here has been validated. |

### The closed-bar contract

| Item | Label | Notes |
|---|---|---|
| `floor((i + 1) / r) - 1` in the multi-timeframe sense, and "identical whether or not later bars exist" | `OBJECTIVE` | A property of the arithmetic and of index threading. It is either true or it is not, which is why the eighteen guarantees are testable at all. |
| "A bar is usable only once closed" | `OBJECTIVE` | A statement about when information exists, not a judgement. |
| "A wider buffer on a level that mattered more" | **not built** | The buffer is a fixed ATR fraction, so a genuinely important level is not treated differently. `TRADE_PLAN.md` §9. |

### `backtest/events.py` — backtesting

| Item | Label | Notes |
|---|---|---|
| "The target was reached before the stop" | `OBJECTIVE` | A comparison of two bar offsets. It is either true or it is not. |
| "One bar contained both levels" | `OBJECTIVE` | Also a comparison, and the honest answer when OHLC cannot order the two. Recorded as `AMBIGUOUS` rather than resolved. |
| MFE / MAE | `OBJECTIVE` | The extreme of a known set of bars, measured from the fill. A geometric property of the path, not a judgement about it. |
| "The fill happened at the next bar's open" | `ALGORITHMIC` | An **assumption**, and named as one by `FillPolicy`. The earliest price that existed after a closed-bar decision, which is why it is the default — not an observation. |
| "The position was closed by an opposite signal" | `ALGORITHMIC` | A consequence of `ConflictPolicy.CLOSE_AND_REVERSE`. Recorded on the event so a truncated path is never mistaken for a horizon timeout. |
| The share of events with a given outcome | **not classified** | A proportion of the sample that was supplied. Named `sample_share`, not `win_rate`, precisely because it says nothing about the market. |
| P&L, equity curve, expectancy, profit factor, win rate | **deliberately absent** | Not "not built" — refused. Each is a claim about the future, and nothing here has been validated. `BACKTESTING.md` §1. |

The line to hold: everything `backtest/` produces is a fact about a **path**, and
the sample statistics derived from those paths are facts about a **sample**. The
moment either would be described as a property of the market rather than of the
data, it has crossed into the unclassified territory of §5.

### `tests/fixtures/golden/` — the golden dataset

| Item | Label | Notes |
|---|---|---|
| "This bar pattern is an H2" | `OBJECTIVE` | A question about which of four leg counts the bars contain. It is either true or it is not, and the fixture's falsifiers are built to make it false. |
| "A double top is detected here" | `OBJECTIVE` | Two highs inside a tolerance, separated by a deep enough trough. Arithmetic on bar extremes. |
| "The target is 111.1" | `OBJECTIVE` | `B0 + (A1 - A0)`, read off three swings. The projection arithmetic, with no engine output involved. |
| "This plan clears `min_rr`" | `ALGORITHMIC` | A comparison against a declared gate. It says the plan passes the project's own rule, not that the trade is good. |
| The golden suite as evidence that these setups work | **not classified, and refused** | Five hand-drawn charts establish what the engine *names*. `VALIDATION.md` §1 says so and §9 says what would be needed to change it. |

The distinction the dataset exists to hold: a fixture can establish that the
detector's *semantics* are as documented, and cannot establish anything about the
market. Those are different claims, and the second one is the one a golden file
would be mistaken for.

## 5. What is not classified: statistical quantities

No feature in this project is labelled `STATISTICAL`, because **nothing here has
been statistically validated.**

In particular, no `score`, `confidence`, or `strength` value is a probability,
an expected value, a win rate, or a likelihood. They are transparent checklists:
"four of four MTR legs present" is a count, and a count is not a forecast.

If a future validation phase calibrates any of these against historical data,
the calibration method, sample, and confidence intervals must be documented
here — and only then may the label change.

The backtesting phase is the first place where this gap could have been papered
over, since it produces outcome counts and it would have been a small step to
divide them and call the result a win rate. It does not, and
`tests/unit/test_phase18_backtesting.py` asserts the absence of `pnl`, `equity`,
`expectancy`, `profit_factor`, `win_rate`, `sharpe` and `balance` from the
serialized output — so the refusal is enforced rather than merely documented.

## 6. Wording rules

- Write "systematic proxy for trend", not "trend detection".
- Write "evidence score", not "confidence" or "probability".
- Write "heuristic", not "rule" or "model".
- Never write "this is what Al Brooks means". See [SOURCES.md](../../SOURCES.md).
