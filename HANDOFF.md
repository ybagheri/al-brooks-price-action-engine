# Handoff — Phase 22 complete, Phase 21 partial

> **Read this if you are a model picking this repository up cold.** The short
> version is in the three sections immediately below. Everything after them is
> detail.

A point-in-time note for whoever picks this up next. **If this file disagrees with
`ROADMAP.md`, `ROADMAP.md` is right**, and this file should be deleted rather than
patched. It is not a phase deliverable and no test reads it.

Full suite: 743 tests, `ruff` and `mypy` clean, both `scripts/` checks passing,
and 8 live-terminal checks pass when `ALBROOKS_MT5_PATH` is set.

## Where this stands, in four lines

- **The engine is finished.** Phases 0-20 and 22 are complete and tested: bars
  through features, structures, context, eleven detectors, evidence, trade plans,
  a gated decision, a multi-timeframe veto, backtesting, golden fixtures, an MT5
  adapter, and an LLM-facing serialization.
- **One phase is blocked on hardware, not on effort.** Phase 21's MQL5 port needs
  MetaEditor and a terminal. `mql5/` does not exist, `tests/parity/mql5/` is empty,
  and parity reports `UNVERIFIED` — a status distinct from both a pass and a
  failure, because nothing was compared.
- **One phase is documentation-only.** Phase 23 expands the existing English and
  Persian documents and owes no new code.
- **Nothing here is validated.** No number in this project is a probability, a win
  rate or an edge. `docs/algorithms/VALIDATION.md` §9 lists the four missing
  ingredients, the largest of which is a stated null. Any change that makes this
  project sound like it has an edge is a regression, not a feature.

## What to do next, in order

1. **Phase 21 on a machine with MetaEditor.** `docs/PYTHON_MQL5_PARITY.md` §8 has
   the ordered list. Expect the first run to **fail** — a port's ATR seed, swing
   tie-break, series direction and null convention are four easy places to diverge,
   which is why each is in scope. Record the disagreements rather than tuning them
   away. **Never hand-write a `"producer": "mql5"` sidecar**; it would turn the
   Phase 20 harness into a decoration.
2. **Phase 23.** Documentation only. `test_project_status.py` already checks that
   both READMEs and every algorithm document are claimed by a manifest and say the
   same thing, so the Persian documents have to move with the English ones.
3. **Phase 21 or a validation phase**, whichever you have the tooling for. Nothing
   in this project has been checked against outcomes, and that is the largest gap,
   not the phase count.

## The thing to know second: the fake was wrong and a real terminal said so

The adapter was validated against an injected fake, and **all 54 tests passed while
three live defects were present.** A real Alpari MT5 (build 6230,
`MetaTrader5` 5.0.6180) then found:

1. **`copy_rates` does not exist** in the Python bindings — only
   `copy_rates_from_pos`, `copy_rates_from`, `copy_rates_range`. The fake
   implemented it, because the MQL5 documentation names it.
2. **The payload is oldest-first**, not newest-first. The original check *refused*
   anything not newest-first — the MQL5 native convention, not the bindings' — so it
   would have raised on every real payload. The property that matters is
   **monotonicity, not direction**; both are now normalised and the direction
   observed is returned rather than discarded.
3. **The server clock ran +3.099 hours ahead of the local one.** Over a 50-bar M15
   window the local clock discarded 13 closed bars. The failure is *directional*: a
   local clock behind the server over-freezes, and one ahead would keep a
   still-forming bar — a look-ahead.

All three are fixed. The transferable lesson is recorded in
`docs/algorithms/MT5_ADAPTER.md` §10: **a fake encodes the author's assumptions.**
Fifty-four green tests certified that the code matched a mental model of MetaTrader,
which is not the claim "this works against MetaTrader".

`tests/integration/test_phase21_live_mt5.py` is the correction — 8 read-only checks
covering exactly what a fake cannot. They **skip** without a terminal:

```bat
set ALBROOKS_MT5_PATH="C:\Users\<you>\AppData\Roaming\Alpari MT5_4\terminal64.exe"
python -m pytest tests\integration\test_phase21_live_mt5.py -v -rs
```

**A skip is not a pass.** It means the file did not run.

## What Phase 21 delivered, and what it did not

**Delivered** — `src/albrooks/adapters/mt5/`, `docs/algorithms/MT5_ADAPTER.md`,
60 unit tests and 8 live-terminal checks. The two obligations
`NON_REPAINT_CONTRACT.md` §4 assigns to an adapter, plus the stateful caller
Phase 19 deferred to.

**Not delivered** — `mql5/Include/AlBrooks/`, and therefore the sidecars that
would fill `tests/parity/mql5/`. **This is blocked on hardware, not on effort:** an
MQL5 port of eleven detectors, the market-state classifier, the plan geometry and
the decision engine can only be *validated* by compiling it with MetaEditor and
running it against a live terminal. Neither exists on the machine this was written
on. The checkbox stays open and parity still reports `UNVERIFIED`.

The temptation to close the gap by hand-writing a `"producer": "mql5"` sidecar is
the one thing not to do. It would turn the Phase 20 harness into a decoration, and
`docs/PYTHON_MQL5_PARITY.md` §6 exists specifically to make that impossible.

## The three things worth knowing before touching this code

- **The freeze decides by time, not by position, and on the *terminal's* clock.**
  `bar.time + period <= now`, because `Bar.time` is the *open* time. "Drop the last
  row" is wrong at every bar boundary and silently wrong across a weekend. The
  `now` must be the server clock — the local one was 3.1 hours off — and
  `FreezeReport.clock` records which was used, so a degradation is visible.
- **Both MetaTrader directions are accepted; only a non-monotonic payload is
  refused.** The Python bindings are oldest-first and MQL5 native is newest-first,
  so `normalize_order()` handles either and returns which it saw. Sorting a
  mis-ordered payload would hide the caller's bug behind a working result — but
  *refusing a legitimate convention* is the same mistake pointed the other way.
- **The session re-derives; it does not accumulate.** The obvious implementation of
  an `AnalysisSession` — keep the fade setups in `self`, advance one bar per call —
  would break `RPC-1`. A session that has seen bars 21..40 and then answers for bar
  20 holds state derived from bars the caller declared unavailable. So
  `track_fading_measured_moves` is re-run on the frozen window every call, and the
  only state kept is the previous result. The test analyses the *longer* series
  first, so a stateful implementation would have to leak deliberately to pass.

## Two conventions that will surprise you

- **`LAST_COMPLETE_PHASE` is a set, not a watermark.** Completed phases are **not
  contiguous** and cannot be: Phase 22 needed nothing external and shipped while
  Phase 21's MQL5 port waits on MetaEditor. `test_project_status.py` used to
  assert "phases 0 through N are done", which became false the moment 22 landed.
  `COMPLETE_PHASES` is derived from `PHASES_STILL_OPEN`, and the progress sentence
  is asserted to agree with its own checkboxes — a summary that reads as truth and
  is not is the specific failure that test file exists to catch.
- **A new *layer* inherits the non-repaint contract by asserting `RPC-1` for
  itself.** A detector added through the registry is covered by `RPC-7` by
  construction; a layer is not. `NON_REPAINT_CONTRACT.md` §7 has the whole rule,
  and `docs/algorithms/AI_INTERFACE.md` is the example of a layer that did it.
