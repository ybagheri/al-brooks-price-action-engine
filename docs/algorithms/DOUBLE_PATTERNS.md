# Double Tops and Double Bottoms

## 1. Three separate questions

| Question | Answered by |
|---|---|
| Is there a double? | `find_major_double_*`, `detect_micro_double_*` |
| Has the level been tested again? | `classify_double_context`, `detect_double_test` |
| Did price break it, and did the break hold? | `classify_double_context` |

These are deliberately not merged. "Two highs at the same level", "a third test
of that level", and "a break that failed" are three different facts, and
collapsing them loses the information that distinguishes a level the market
respects from one it merely passed through.

## 2. Major vs micro

**Major** patterns are built from **confirmed swing** extremes, and require a
trough between them of at least `0.5 * ATR`, so two adjacent bars cannot
masquerade as a double.

**Micro** patterns are built from bar extremes inside a 5-bar window, with the
separation requirement halved to `0.25 * ATR`.

Major vs micro is a **window-length distinction, not a quality claim**. A micro
double top is not "weaker" in any measured sense; it is a smaller structure.

## 3. Level matching

Two extremes match when they are within `double_tol_atr * ATR` (default 0.25).
The shared **level** is the mean of the two extremes. That tolerance is a
`HEURISTIC` value chosen by this project: it decides what "the same level"
means, and no first-principles derivation of 0.25 exists.

## 4. Test, break, failure

Working forward from `bar2`:

- **Test**: the bar reaches the level but does not close beyond it.
- **Break**: the bar closes beyond the level by more than the tolerance, *in the
  direction that goes through the level*.
- **Failed break**: after a break, a bar closes back on the original side.

Two rules in that sequence are load-bearing and were both wrong in a first
draft:

**Only the through-direction counts as a break.** A double top is resistance,
so only an upside break is a break. A close falling away below it is the pattern
working as intended, not a breakdown. Without this restriction every double top
"broke" downward on the very next bar.

**Reclaim is evaluated before a new break.** After a break has occurred, a
close that returns to the original side of the level *also* clears the opposite
break threshold. Checking the break first misfiles every reclaim as a fresh
break in the same direction, so no failed break is ever reported.

## 5. What this does not claim

- **A double top is not a sell signal and a double bottom is not a buy
  signal.** `direction` records the conventional reading of the shape. Nothing
  here attaches a probability, expectancy, or reliability to it, and none has
  been validated.
- A third test does not make a level "strong". It makes it *tested*.
- A failed break is not a reversal. It says the break did not hold, nothing more.
- Tighter tolerance finds fewer, cleaner levels and will miss genuine doubles on
  volatile instruments; wider tolerance finds more and will pair unrelated
  extremes. There is no validated optimum.

## 6. Configuration

| Key | Default | Meaning |
|---|---|---|
| `double_tol_atr` | `0.25` | Level-matching tolerance, in ATR |
| `failed_bo_bars` | `5` | Reclaim window, in bars |

## 7. API

```python
# base detection (no context)
pattern = detect_micro_double_top(bars, idx, last_closed, atr, config)

# detection with context
pattern = detect_micro_double_top_with_context(bars, idx, last_closed, atr, config)
pattern.level, pattern.is_tested, pattern.breakout_bar, pattern.is_failed

# context applied to an existing pattern
pattern = classify_double_context(pattern, bars, last_closed, atr, config)

# standalone level test, for callers holding a level rather than a pattern
count = detect_double_test(bars, last_closed, level, is_resistance, atr, config)
```
