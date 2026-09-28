# Backtesting

## 1. What this module is for

Phase 18 adds the first thing in this project that produces **numbers about
outcomes**. Every earlier phase asked "what is the market doing?"; this one asks
"when the engine said this, what did the path afterwards do?"

The answer is deliberately narrow:

| Measured | Not measured |
|---|---|
| which level came first | P&L |
| how many bars it took | an equity curve |
| maximum favourable excursion (MFE) | expectancy |
| maximum adverse excursion (MAE) | a profit factor |
| how many bars produced no decision | a win rate |
| how many signals arrived while a position was open | a forecast |

The right-hand column is not an oversight. It is the list of numbers a backtest
exists to produce, and each one is a claim about the future that this project
cannot support: **nothing here has been validated against outcomes.** Phase 19
built the golden fixture dataset (`tests/fixtures/golden/`) and deliberately did
*not* do that validation — it has no real labelled data to validate against, and
`VALIDATION.md` §9 sets out what would be required. Producing a green equity curve
here would be arithmetically trivial and evidentially worthless, so this module
does not produce one.

`sample_share()` exists and is not called `win_rate` on purpose. It is a
proportion of the events in the sample you supplied — a fact about the sample, not
about the market.

## 2. Where the line between decision and outcome is

This is the load-bearing boundary of the phase.

`replay()` calls `analyze(bars, last_closed=k)` at every bar and then reads bars
`k+1..` **for the outcome only**. Two separate statements, each tested separately:

- **The plan is invariant.** An event's entry, stop and target equal the plan from
  `analyze(bars, last_closed=k)` exactly, and do not change when bars are appended
  after `k`. This is `RPC-15` applied to this module, and it is what makes the
  outcome meaningful: the levels are the engine's own, not a hindsight choice.
- **The outcome is a function of the horizon, not of the future.** Append bars
  beyond `k + horizon` and nothing on the event moves.

The second guarantee has one honest exception, and the document states it rather
than hiding it: with `horizon=None` a path runs to the end of the supplied series,
so a `NEITHER` at bar `k` can legitimately become a `TARGET_FIRST` when more bars
arrive. That is not a look-ahead bug; it is what "no horizon" *means*. Claiming
invariance there would be the kind of overstatement this project refuses to make,
so `test_without_a_horizon_the_outcome_legitimately_changes_and_that_is_not_a_leak`
asserts that the change happens and says why it is allowed.

**Always pass a horizon when comparing runs.** Without one, the sample size
depends on how much data you happened to supply.

## 3. The three lies a backtest tells

### 3.1 The intra-bar order is unknowable

From OHLC you cannot know whether a bar's high or its low came first. A bar whose
high is past the target and whose low is through the stop cannot be ordered, and
a backtest that resolves it by picking the favourable order is not measuring
anything — it is choosing its own result.

So `AMBIGUOUS` is a first-class `Outcome`, recorded on the event and **never
overwritten**:

```python
event = replay(bars, horizon=10).events[0]
event.outcome                    # Outcome.AMBIGUOUS -- the raw fact
event.resolved(AmbiguityPolicy.STOP_FIRST)    # Outcome.STOP_FIRST
```

Resolution is a separate step applied at *reporting* time, so the raw record
survives. The default is `STOP_FIRST`, because the pessimistic reading is the only
one that can be defended as an assumption. `TARGET_FIRST` exists so a caller who
wants the best case can ask for it explicitly — not because it is the default.
`EXCLUDE` drops ambiguous events from the tally *and* puts nothing in their place,
so the total falls; that drop is the visible consequence of excluding.

A test asserts the policy does not quietly reclassify the rest of the sample: for
every non-ambiguous outcome, every policy returns it unchanged.

### 3.2 The fill price is an assumption, not a fact

A decision is made from a closed bar, so the earliest price that existed
afterwards is the **next bar's open**. `FillPolicy.NEXT_OPEN` is the default.
`SIGNAL_CLOSE` fills at a price the engine had when it could not yet have acted; it
is available for comparison and is named for what it assumes.

An event carries both `plan_entry` and `entry`, so "the plan said 104" and "it
filled at 104.3" stay distinguishable.

A fill can also arrive **already dead**: if the next open is through the stop, the
trade never existed. That is `INVALID_ENTRY`, with a reason in `detail`
(`FILL_ALREADY_THROUGH_STOP` or `FILL_ALREADY_PAST_TARGET`). It is counted as an
event rather than dropped, because a dropped invalid fill is a sample edited in
its own favour. It is excluded from the excursion means, since it has no path.

### 3.3 Overlapping signals inflate the sample

Three decisions in twelve bars are not three independent observations; they are
usually one trend, counted three times.

| Policy | Behaviour |
|---|---|
| `SKIP` (default) | at most one position at a time |
| `CLOSE_AND_REVERSE` | an opposite signal closes the open position and takes the new one |
| `PARALLEL` | every signal becomes an event |

`PARALLEL` names itself in the caveats, because its counts are not comparable with
a default run.

Whether a signal conflicts is answered by the open position's **own outcome**, not
by the horizon it was given. A position that reached its target three bars ago
does not go on blocking signals for the rest of the window. `CLOSE_AND_REVERSE`
additionally requires the signal to be *opposite*: a same-direction signal is the
trade already running, and counting it as taken would double one position.

A reversed position's path is cut at the bar before the new fill, and its `detail`
records `closed by an opposite signal`. Without that, a truncated path would be
indistinguishable from a horizon timeout — and with a fill at the new bar's open,
the level that closed the old position may not have been reached until intrabar
on that same bar, so the strictness is deliberate.

## 4. Reading the results

```python
from albrooks.backtest.events import replay

result = replay(bars, horizon=10)

result.counts()                 # outcome -> count, every outcome always present
result.sample_share(Outcome.TARGET_FIRST)
result.mean_mfe_atr()           # None rather than 0.0 if the sample is empty
result.skipped                  # why no event was made, per reason code
result.caveats                  # read these before the numbers
```

`counts()` always includes every outcome, including zeros, so a reader sees the
whole picture rather than only the categories that happened to occur.

`skipped` is a count per reason code, not nothing, because "no decision", "a
signal arrived while a position was open" and "the series was too short to fill"
are three different facts about a run and a bare event list expresses none of them.

`caveats` is returned **inside** the result rather than only in this document, so
a report cannot travel without them. Two of them are added dynamically, because
they are interactions a reader would otherwise get wrong:

- with no horizon, excursions are measured over everything that happened after the
  fill, which is not a holding period;
- `ConflictPolicy.SKIP` with no horizon holds a position open until a level is
  actually reached, so a position that never reaches one goes on skipping signals
  until the series ends.

`to_dict()` is JSON-serialisable and includes the events in full.

## 5. Excursions

`mfe` and `mae` are measured in price units from the **fill**, never negative, and
also given in ATR multiples (`mfe_atr`, `mae_atr`) — the only version comparable
across instruments and regimes. A long's favourable excursion is how far the high
went above the entry; a short's is how far the low went below.

They are measured **up to the exit**, not to the end of the horizon. A
stopped-out trade that keeps its excursion climbing for the rest of the window is
being credited with market action that happened after it was no longer in the
trade, and the resulting MFE is not a property of the trade at all. This was a
real defect during development, caught by a test that recomputes the excursion
from the bars up to the exit.

`bars_held` is the number of bars the position was open for, and for a `NEITHER`
event it is the length of the window — a timeout, not a loss, and `NEITHER` exists
so the two are not conflated.

## 6. A bug worth recording

The first version of level-touching used one helper for both the target and the
stop, reading the *favourable* extreme in both cases. A long's stop was therefore
never actually tested, and every "stop hit" the module reported was fabricated:
the low had never reached the level, but the helper returned the first bar whose
**high** passed the stop price.

It is now two helpers, `_first_target_touch` and `_first_stop_touch`, because the
extreme that matters depends on which side of the price the level is on. The
companion lesson is about testing: the first version of the test suite exercised
this code through a fixture, where the fabricated readings looked plausible. The
tests that now guard it build forward windows by hand and state the expected
answer, which is the only way a wrong answer is visible.

## 7. What this phase does not establish

- No outcome here says anything about the next one.
- No count here is a rate, a probability or an edge.
- The engine has **not** been validated against outcomes. Phase 19 built a
  semantic regression suite over five hand-drawn charts, which establishes what
  the engine *names* and nothing more. `VALIDATION.md` §1 says so and §9 says what
  would be needed to change it.
- `replay` is O(n²): it re-analyses from the start at every bar. An incremental
  path would be much faster and is deliberately absent, because
  `NON_REPAINT_CONTRACT.md` is worth more than the speed, and a cache that is
  right nine times in ten is the classic way a backtest reports a result the
  engine would never have produced live.

## 8. Source

`src/albrooks/backtest/events.py`
`tests/unit/test_phase18_backtesting.py`
