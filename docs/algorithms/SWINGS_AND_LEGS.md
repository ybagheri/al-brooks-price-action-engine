# Swings, Pivots and Legs

## 1. Concept taxonomy

See [CONCEPT_TAXONOMY.md](../architecture/CONCEPT_TAXONOMY.md). Summary:

| Item | Label |
|---|---|
| Swing high/low location | `ALGORITHMIC` |
| Confirmation delay | `OBJECTIVE` |
| Leg endpoints, size, duration | `OBJECTIVE` |
| Symmetry ratio | `OBJECTIVE` (the number; judging it is not) |
| Two-legged structure match | `ALGORITHMIC` |
| Pivot strength / touches | `OBJECTIVE` counts, `HEURISTIC` significance thresholds |

## 2. The lookahead problem

A fractal swing high at bar *s* is defined using bars to the *right* of *s*. It
is therefore unknowable at bar *s*. Most naive implementations quietly violate
this and repaint: the swing appears, then moves, then disappears.

This engine resolves it with **delayed confirmation**:

> A swing at bar `s` with `k` wings becomes usable only once bar `s + k` closes.

Every `SwingPoint` records `confirmed_bar_index = s + k`, and every consumer
filters on it. The consequence is the project's core invariant:

> The analysis for a given bar index is **identical** whether or not later bars
> exist.

This is enforced by `tests/unit/test_phase3_pivots.py::test_pivots_have_no_lookahead`.

## 3. Swing detection

Bar `s` is a **swing high** when it is the highest high over `[s-k, s+k]`, and
a **swing low** when it is the lowest low over the same window.

- `k` (default 3) comes from `AnalyzerConfig.swing_k`.
- Search starts at `s = k`, so a swing always has a full left wing.
- Search stops at `s + k <= last_closed`, which is what enforces the delay.

**Tie-breaking.** When several bars share the extreme, the *earliest* one wins.
A bar is disqualified if any bar in its right wing `(s, s+k]` matches its high
(or low) exactly. This makes the output deterministic on flat data, which
matters for reproducibility and for parity testing.

**Closed-bar contract.** `find_swings` never reads beyond `last_closed_idx`.

## 4. Legs

A **leg** is the price move between two consecutive alternate swings:

```text
leg = (start_index, end_index, start_price, end_price, direction)
direction = +1 if end_price > start_price else -1
```

Legs are built by `build_legs_from_swings`, which walks consecutive swing pairs
and drops any pair whose swings share a direction (not a real leg).

| Field | Meaning |
|---|---|
| `bars_count` | Duration in bars. |
| `price_change` | Absolute size. |
| `confirmed_index` | The later of the two swings' confirmation bars. |

A leg is only usable once *both* its endpoints are confirmed, which is why
`confirmed_index` takes the maximum rather than the minimum.

### Leg symmetry

```text
symmetry_ratio = leg2.price_change / leg1.price_change
```

`1.0` means the two legs are equal in size. This is an `OBJECTIVE` ratio;
calling a market "balanced" because of it is an `INTERPRETATION` and is not
made here.

### Two-legged structures

`detect_two_leg_structures` matches the pattern `leg1 (d) -> pullback (!d) ->
leg2 (d)` and reports:

- `pullback_ratio` = pullback size / leg1 size
- `symmetry_ratio` = leg2 size / leg1 size

This is a mechanical pattern match. It is **not** a quality judgement, and a
detected structure is not a signal.

## 5. Pivots

A **pivot** is a swing annotated with how significant it turned out to be.
`core/pivots.py` builds on `find_swings` rather than reimplementing fractal
detection, so the project keeps exactly one authoritative swing algorithm.

| Field | Meaning |
|---|---|
| `strength` | Bars in the dominance window that failed to break the pivot. Starts at 1. |
| `touches` | Later bars that retested within `tolerance_atr * ATR` without breaking it. |
| `is_major` | `touches >= major_touches` (default 2). |

**Interpretation.** A level that is repeatedly tested and holds is one the
market respected. `is_major` is a `HEURISTIC` stand-in for that judgement, and
`major_touches = 2` is a chosen value, not a derived one.

### What pivots do not claim

- A major pivot is **not** support or resistance. Those are judgements about
  future behaviour; this is a count of past retests.
- Pivot levels are **not** entry or exit signals.
- `strength` is **not** a probability that the level holds.
- A pivot that never gets retested is not "weak" — it is simply untested. The
  two are indistinguishable from these data alone.

### Limitations

- The dominance window (default 20 bars) is a fixed bar count, not an
  ATR-normalised or volatility-adaptive one. On very different instruments and
  timeframes this may need different values.
- Touch counting is sensitive to `tolerance_atr`. Too tight and genuine tests
  are missed; too loose and unrelated bars count.
- Both measures are computed from closed bars only, so a pivot's `touches` grows
  as bars arrive. The *location* never moves, but significance is not final
  until enough time has passed.

## 6. Configuration

| Key | Default | Meaning |
|---|---|---|
| `swing_k` | `3` | Fractal wing length, in bars. |
| `min_leg_bars` | `3` | Minimum leg duration. |
| `max_leg_bars` | `100` | Maximum leg duration. |
| `min_leg_atr` | `1.0` | Minimum leg size, in ATR multiples. |

Pivot-specific windows (`strength_window`, `touch_window`, `tolerance_atr`,
`major_touches`) are parameters of `find_pivots` rather than global config, since
they are situational tuning rather than engine-wide policy.
