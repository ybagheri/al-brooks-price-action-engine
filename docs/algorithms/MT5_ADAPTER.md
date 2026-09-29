# MT5 Adapter

The MetaTrader 5 adapter, and an honest statement of the half of Phase 21 that
is not in this repository.

## 1. What this is

`src/albrooks/adapters/mt5/` reads bars from a MetaTrader 5 terminal and hands
them to the engine in the form the engine expects, discharging two obligations
that `docs/algorithms/NON_REPAINT_CONTRACT.md` assigns to the adapter rather than
to the analysis.

| Module | What it owns |
|---|---|
| `errors.py` | four failure types, kept apart because the recovery differs |
| `timeframes.py` | `ENUM_TIMEFRAMES` decoding, and the one period that cannot be measured |
| `series.py` | newest-first → oldest-first, and the forming-bar freeze |
| `feed.py` | the connection; the only module that names `MetaTrader5` |
| `session.py` | a stateful caller, which closes the Phase 19 fade finding |

It is the only part of the package allowed to import MetaTrader 5, and
`scripts/check_no_mt5_dependency.py` enforces that in CI rather than by
convention. The check polices an allow-list of one directory, which is only a
meaningful rule because the surface is that small — `test_only_the_feed_names_the_terminal_bindings`
in the phase suite fails if that grows.

## 2. Obligation one: the series direction

The engine is **oldest-first** everywhere — `Bar.index`, `last_closed`, every
`range(k, n)` in every detector. MetaTrader is not, and **which way it is not
depends on the API** (see §10):

| API | Direction |
|---|---|
| Python bindings, `copy_rates_*` | **oldest-first** (ascending) — measured |
| MQL5 native, `ArraySetAsSeries(true)` | **newest-first** (descending) |

`docs/PYTHON_MQL5_PARITY.md` §3.1 names this as *the single likeliest divergence in
the whole port*, and the reason is worth stating plainly: **a reversed series still
analyses.** It produces swings, a market state, a decision and a set of trade
plans, all of them internally consistent and all of them about the wrong direction.
Nothing about the output says "reversed". The failure is invisible until it is
expensive.

So the normalisation is not a convenience applied on the way past:

- `normalize_order()` is the only path from an MT5 payload to a `BarSeries`, and it
  returns oldest-first from **either** direction.
- It **returns the direction it observed** rather than discarding it, so a caller
  can log or assert on it. A silent flip moves every bar index, and the parity
  contract compares `bar_index` and `confirmed_bar_index` with `EXACT_INT` for
  precisely that reason.
- A payload whose timestamps are **neither** ascending nor descending is **refused**
  with `SeriesOrderError`. Monotonicity is the property that matters, not direction:
  both single directions are legitimate conventions, but a sequence that goes
  forwards then backwards, or repeats a timestamp, is broken — and inferring which
  way the caller meant from a broken sequence is the guess that produces a
  confident wrong answer.
- MT5's own field spelling (`tick_volume`) is mapped at this boundary, so the rest
  of the package never sees it.

`test_both_the_python_and_the_mql5_conventions_are_accepted_and_normalised` and
`test_a_genuinely_unordered_payload_is_still_refused` are the two halves.

## 3. Obligation two: the freeze

`NON_REPAINT_CONTRACT.md` §4 states the design: `Bar` has **no** forming-bar flag
and `BarSeries` is documented as a sequence of closed bars. A flag would have to
be threaded through every detector, and one that forgot to honour it would be a
look-ahead bug no test could see. So dropping the newest bar is the adapter's job.

### Why the freeze decides by time and not by position

The obvious implementation is "drop the last row". It is wrong, and wrong
*silently*, in three ordinary situations:

- the call lands in the instant after a bar closed and before the next opens, so
  the newest row is already closed and dropping it discards real data;
- a `copy_rates_from` / `copy_rates_range` window can end on a bar boundary;
- across a weekend or a session break, the newest bar may have closed hours ago.

Each of those makes the positional freeze either leak a still-forming bar or throw
away a closed one, and both look like a working adapter until a comparison fails
for no visible reason.

The rule here is the same closed-bar arithmetic the rest of the project already
uses — `Bar.time` is the **open** time, so a bar opened at `t` closes at
`t + period`:

> bar `i` is read only when `bar.time + period_seconds <= now`.

The boundary is inclusive. A bar that closed exactly now has closed, and this is
the one side worth pinning, because the alternative lags by a bar forever.

Three tests hold this down, and the second and third are the ones the positional
shortcut fails:

| Test | What it pins |
|---|---|
| `test_the_forming_bar_is_dropped_and_the_rest_are_kept` | the obligation itself, and the report naming the bar |
| `test_the_freeze_decides_by_time_not_by_position` | a call with nothing forming keeps **every** bar |
| `test_a_series_whose_newest_bar_closed_hours_ago_keeps_every_bar` | a session or weekend gap does not shrink the window |

### The clock is the terminal's, and this is not optional

`now` must come from the **server clock**, and the local clock is not a fallback —
it is a hazard. Measured on a live Alpari MT5 terminal:

```text
local epoch       1790655320  = 2026-09-29 04:15:20 UTC
server tick epoch 1790666477  = 2026-09-29 07:21:17 UTC
skew: server - local = +11157 s = +3.099 h
```

**3.1 hours** — twenty-six M15 bars. Over a 50-bar M15 window:

| Clock | Bars treated as closed | Bars wrongly dropped |
|---|---|---|
| local | 36 of 50 | **14** |
| server | 49 of 50 | 1 (the real one) |

And the failure is **directional**, which is why it cannot be waved through as
"conservative":

- Server **ahead** of local (measured here): the local clock says fewer bars have
  closed, so the freeze **discards 13 bars of real history**. Annoying, not unsound.
- Local **ahead** of server: the local clock says more bars have closed, so the
  freeze **keeps a bar that is still forming**. That is a look-ahead, and it is the
  exact failure this whole design exists to prevent.

So `MT5Feed.closed_bars()` reads the clock from the terminal and passes it in.
`FreezeReport.clock` records which one was used — `SERVER`, `CALLER` or `LOCAL` — so
a reader never has to guess, and a degradation to `LOCAL` is **visible** rather than
silent. A `now` supplied by the caller is `CALLER` and takes precedence: someone who
knows the right answer should not be overridden by a default.

`server_time()` is a **tick time** — the bindings have no `TimeCurrent()` — so it is
an approximation. On a quiet symbol the last tick may be older than now, which makes
the freeze **conservative**, the safe direction. `MT5Feed` prefers the symbol being
fetched and falls back to a liquid default only when it must.

`test_the_freeze_uses_the_terminals_clock_and_says_so` reproduces the 3.1-hour skew
in a fixture and asserts the exact number of bars it costs (12), so the fix cannot
be undone by switching the default back to `time.time()`.

### An all-forming series freezes to empty

Keeping the newest bar "just in case" is the leak the function exists to prevent.
The engine already has an honest answer for an empty series — `NO_BARS`, carried as
a reason rather than as an empty structure list — so the freeze returns empty and
lets that answer stand.

## 4. Timeframes, and the one that cannot be measured

`ENUM_TIMEFRAMES` is a scheme rather than arbitrary numbering, and reading it as
arbitrary is how a port ends up treating a 16,385-second hourly bar as 16,385
*minutes*:

| Band | Encoding | Example |
|---|---|---|
| Minutes | the minute count, `1..30` | `PERIOD_M5 = 5` |
| Hours | `16384 + hours` | `PERIOD_H1 = 16385`, `PERIOD_H4 = 16388` |
| Days | `16384 + hours`, up to 24 | `PERIOD_D1 = 16408` |
| Weeks | `32768 + weeks` | `PERIOD_W1 = 32769` |
| Months | `49152 + months` | `PERIOD_MN1 = 49153` |

`period_seconds()` decodes the scheme rather than carrying a table of twenty-odd
constants, because a table and the scheme are two ways of writing one fact and a
disagreement between them would be a silent one.

**A calendar month is refused.** It is 28, 29, 30 or 31 days, so there is no way to
decide from a bar's timestamp whether it has closed. `period_seconds(MN1)` raises
`TimeframeUnsupported` rather than assuming 30 days: a 30-day assumption is wrong
on at least two days of every month, and a freeze that is wrong on those days is a
look-ahead that *looks like a correct answer*. A caller who knows the period passes
`period_seconds` to `closed_bars()` and gets an exact freeze.

## 5. What is NOT here, and why

**`mql5/Include/AlBrooks/` does not exist.** No MQL5 build of this engine has been
written.

> **Correction, Phase 23 follow-up.** This section previously said the port was
> **"blocked on MetaEditor and a terminal"**. That was **wrong, and it was never
> checked.** MetaEditor 5.0.0.6230 ships in the same folder as the terminal, and
> the full compile-and-run loop works headlessly:
>
> ```
> MetaEditor64.exe /compile:<file>.mq5 /log:<log> /inc:<MQL5>      -> 0 errors, .ex5
> terminal64.exe  /portable /config:<tester>.ini                      -> "last test passed"
> ```
>
> The EA's files land in `Tester\Agent-127.0.0.1-3001\MQL5\Files\` and are
> readable from Python. The one non-obvious requirement: the tester's `Login` and
> `Server` must appear in **both** `[Common]` (so the terminal itself logs in) and
> `[Tester]` (so the local agent authorises). With them only in `[Common]` the
> agent fails with `tester agent authorization error`; with them in both, the
> test runs and finishes.
>
> So the port is not blocked. It is **unwritten**, which is a different and much
> less interesting statement. What follows is the ordered work, unchanged in
> substance.

An MQL5 port of this scope — eleven detectors, the market-state classifier, the
trade-plan geometry and the decision engine, all reproducing a 33-field canonical
vector — has simply not been written.

So the consequences are stated rather than hidden:

- **`tests/parity/mql5/` is still empty.** All three cases name no sidecar.
- **A parity run still reports `UNVERIFIED`** — a status distinct from both a pass
  and a failure, because nothing was compared.
- **`--allow-unverified` is still in `.github/workflows/ci.yml`**, and
  `tests/unit/test_phase20_parity.py` still asserts the flag and the shipped state
  stay in step.
- **No parity claim is made anywhere in this project.** The suite passing says the
  Python engine is internally consistent. It says nothing about agreement with a
  second implementation, because there is no second implementation.

A test in this phase's suite
(`test_no_mql5_sidecar_exists_and_the_parity_run_still_says_unverified`) asserts
the empty state, so the day a real sidecar lands the documentation has to move in
the same change. A status that only gets checked when someone remembers is not
checked.

### What a real Phase 21 completion still owes

Per `docs/PYTHON_MQL5_PARITY.md` §8, in order:

1. `mql5/Include/AlBrooks/` implementing `SCOPE`. The four places a port most
   easily diverges, and the reason each is in scope: the **ATR seed**, the **swing
   tie-break** (earliest-wins), the **`BarSeries` direction**, and the **null
   convention**.
2. One sidecar per case in `tests/parity/mql5/`, each case's `mql5_vector` set,
   and `--allow-unverified` removed from CI. A test links the two.
3. **The disagreements the first run produces, recorded.** The expectation is that
   it fails. A harness whose first recorded result is a clean pass should be
   checked for having compared nothing — and if a hand-written
   `"producer": "mql5"` file is ever committed to make it pass, that is worse than
   no MQL5 code at all, because the harness would then be reporting agreement it
   did not measure.

## 6. The Phase 19 finding, closed

`docs/algorithms/VALIDATION.md` §5.1 recorded that the fading-measured-move
lifecycle was unreachable through the pipeline. The cause was one line:
`setups/registry.py` registers `create_setups`, which only *seeds* a projection,
and `track_fading_measured_moves` — which advances the state machine — was never
called by the engine. A live consumer saw `PROJECTED` with `age 0` forever, for a
projection the market had already touched, reached and rejected.

Phase 19 declined to fix it because fixing it means giving a *stateless* detector
contract a stateful responsibility, and that belongs with a stateful caller.
`session.py` is that caller.

### The obvious fix is the wrong one

The natural implementation of an `AnalysisSession` is to keep the fade setups in
`self` and advance them one bar per call. That is an incremental state machine, and
it **breaks `RPC-1`** — the invariant the whole engine rests on:

> The analysis for a given bar index is identical whether or not later bars exist.

A session that has seen bars 21..40 and then answers for bar 20 is holding state
derived from bars the caller declared unavailable. That is look-ahead wearing the
costume of a convenience, and it is invisible: the numbers still look plausible.
It also makes the answer for bar 20 depend on *when* it was asked, which is exactly
what `RPC-15` exists to forbid.

So the session re-derives. `track_fading_measured_moves` is a deterministic
function of `(bars, last_closed)`, so re-running it on the frozen window gives the
same answer a live run, a backtest and a fresh call all give. The state the
session holds is **the previous result**, and nothing else — held so a caller can
ask what changed.

`test_the_session_re_derives_rather_than_accumulating` analyses the *longer* series
first, so a stateful implementation would have to leak deliberately to pass.

### What it does not do

**The pipeline still reports `PROJECTED`.** The registry is stateless and that is
its contract; this session adds a caller rather than editing the registry's
contract. `SessionResult` carries both readings and a `fade_source` field saying
which is which, so neither can be mistaken for the other — and
`test_the_session_reports_a_lifecycle_the_pipeline_cannot_reach` asserts *both*, so
the change cannot quietly become "the pipeline now says something else".

A fade is an **observation**, not a trade. The lifecycle produces no entry, no
stop and no order, and `test_the_session_does_not_turn_a_fade_into_a_trade` pins
that the session adds no route to treating a `DEVELOPING` fade as a signal.

## 7. Configuration

The adapter reads `AnalyzerConfig` and adds no keys of its own. The window floor
is derived from the default config rather than invented:

```
WINDOW_FLOOR = atr_period + 4 * swing_k + state_lookback, rounded up
            = 14 + 12 + 20 = 46 -> 60
```

It is a floor and not a recommendation. Below it, ATR has not settled and the
market-state lookback is not populated, and an un-warned result would read as "no
structure here" about a market that was never examined. The session reports
`MT5_WINDOW_BELOW_FLOOR` and the engine reports its own `warnings`; neither
substitutes for the other.

## 8. Usage

```python
from albrooks.adapters.mt5 import AnalysisSession, MT5Feed, M15

feed = MT5Feed()
feed.connect("EURUSD")            # raises MT5Unavailable if the terminal is down
session = AnalysisSession()

for _ in range(10):
    frozen = feed.closed_bars("EURUSD", M15, 300)
    result = session.on_bars(frozen.series, freeze=frozen.freeze)
    print(result.last_closed, result.analysis.decision["action"],
          [f.state for f in result.fades])
```

`connect()` takes an optional `path=` naming a specific `terminal64.exe`; without it
the bindings find the terminal themselves. The path must be the **executable**,
not its folder — a folder produces `Invalid "path" argument` and a
`MT5Unavailable` whose message reads like "the terminal is not running" when the
real problem is a bad path.

The `MetaTrader5` bindings ship with a MetaTrader 5 terminal on Windows and are not
on PyPI for other platforms, so `pip install albrooks` does not bring them. The
import is lazy, inside `MT5Feed.connect()`, which means `import
albrooks.adapters.mt5` works anywhere — on CI, on a Mac, in a consumer's test suite
— and only *using* the feed needs the terminal. A missing bindings module and a
terminal that is not running both raise `MT5Unavailable`, so a caller sees one
error type for "no terminal".

## 10. What a live terminal found, and why it is written down here

The adapter was first written against the *documented* API and the MQL5-native
convention, and every one of its 54 tests passed. Then it was run against a real
terminal — Alpari MT5, build 6230, `MetaTrader5` 5.0.6180, EURUSD — and **three
defects surfaced that no fake could have found:**

| # | Defect | What would have happened |
|---|---|---|
| 1 | `copy_rates` **does not exist** in the Python bindings | `AttributeError` on the first real fetch |
| 2 | The payload is **oldest-first**, not newest-first | `SeriesOrderError` on every real payload — the check was aimed at the wrong convention |
| 3 | The server clock ran **+3.1 hours** ahead of the local one | 13 of 50 M15 bars silently discarded |

All three are fixed. The reason to record them is the *shape* of the failure, not
the individual bugs:

> **A fake encodes the author's assumptions.** The fake implemented `copy_rates`
> because the documentation mentioned it, and returned newest-first because that is
> what `ArraySetAsSeries(true)` does. Both were reasonable readings and both were
> wrong. Fifty-four green tests certified that the code matched a mental model of
> MetaTrader, which is not the same claim as "this works against MetaTrader".

`tests/integration/test_phase21_live_mt5.py` is the correction. It is **skipped**
when no terminal is reachable, so CI stays hermetic, and it covers exactly the set
of claims a fake cannot check:

- which functions the bindings actually expose;
- which direction the payload actually arrives in;
- whether both conventions normalise to the same series;
- whether the server and local clocks can be read, and how far apart they are;
- that a live freeze drops exactly one bar on a liquid symbol;
- that `RPC-2` holds on a real series — no forming-bar price reaches a result.

**A fourth defect turned up in this file rather than in the adapter, and it took
two attempts.** The `RPC-2` check searched the serialised result for the forming
bar's high as a *substring*, and EURUSD quotes to five decimals, so a forming high
of `1.13640` matched `1.13645` — a **closed** bar's low. Fixing that to a numeric
comparison was necessary and not sufficient: on a later live run it fired again,
because the forming bar's high of `1.13654` was *also* the high of a closed bar.
Both failures were the test being wrong, not the engine.

The property that actually holds is narrower than the one the test was checking.
A leak means a price that exists **only** on the forming bar; a price the market
has also printed on a closed bar is not a leak no matter where it appears. So the
check now subtracts the closed bars' own extremes before comparing, and skips
when the forming bar's extremes happen to be entirely shared — because on such a
run the test cannot distinguish the two cases, and pretending otherwise would be
the same error in a third disguise.

That is the same lesson as the three adapter defects, one level down: **an
assumption about the data's shape, made confidently and not checked.** A
false-positive test is worse than no test, because it teaches you to ignore the
suite.

```bat
set ALBROOKS_MT5_PATH="C:\Users\<you>\AppData\Roaming\Alpari MT5_4\terminal64.exe"
set ALBROOKS_MT5_SYMBOL=EURUSD
python -m pytest tests\integration\test_phase21_live_mt5.py -v -rs
```

The path must be the **executable**, not its folder; a folder yields
`Invalid "path" argument` and a skip whose message reads like "the terminal is not
running" when the real problem is a bad path.

**A skip is not a pass.** It means the file did not run, and every skip here names
its reason including the exact `MetaTrader5` error — a suite that skips silently is
indistinguishable from one that passes.

The tests are **read-only**: `copy_rates_from_pos` and `symbol_info_tick` only. The
adapter sends no orders and neither do these.

### What the live run does *not* establish

- **Nothing about parity.** A working adapter on the Python side is not a second
  implementation. §7 stands.
- **Nothing about the MQL5 port.** `mql5/` is still empty.
- **Nothing about the readings.** The live suite asserts that a result was
  produced, not that it is any good. `VALIDATION.md` §9 is unchanged.
- **Nothing about other brokers.** Alpari EURUSD M15 is one venue and one symbol.
  The clock skew in particular is a property of that broker, not a constant — which
  is why the adapter *measures* the server clock rather than hard-coding an offset.

## 11. What this adapter does not do

It sends **no orders**, sizes **no positions**, and reads **no account state**.
`ROADMAP.md` records why: a trade plan is not an order; position sizing needs an
account risk policy — what fraction of equity one idea may risk — which is a
statement about the account and the operator rather than about the chart; and
nothing in this project has been validated against outcomes, so a lot size computed
here would be a number with nothing behind it.

This is a **bar source** and a caller. The only thing either produces is a reading.
