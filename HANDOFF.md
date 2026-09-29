# Handoff — Phase 21 complete, all 24 phases done

> **Read this if you are a model picking this repository up cold.** The short
> version is in the three sections immediately below. Everything after them is
> detail.

A point-in-time note for whoever picks this up next. **If this file disagrees with
`ROADMAP.md`, `ROADMAP.md` is right**, and this file should be deleted rather than
patched. It is not a phase deliverable and no test reads it.

Full suite: 773 tests, `ruff` and `mypy` clean, both `scripts/` checks passing,
and 8 live-terminal checks pass when `ALBROOKS_MT5_PATH` is set.

## Where this stands, in four lines

- **The engine is finished, and so is the port.** Phases 0-23 are complete and
  tested: bars through features, structures, context, eleven detectors, evidence,
  trade plans, a gated decision, a multi-timeframe veto, backtesting, golden
  fixtures, an MT5 adapter, an LLM-facing serialization, a Persian documentation
  tree, and an **MQL5 implementation of all of it**.
- **Parity is established over the declared scope, and only that.** A real
  MetaEditor build, run in a real Strategy Tester, produces a real sidecar for
  each of the three cases, and **all three agree with Python on every declared
  field, with a worst relative deviation of `0.0`** — not merely inside the
  `1e-9` tolerance. The run reports `AGREED`. `--allow-partial` is out of CI,
  because `AB_PORTED_GROUPS` now names every group in `SCOPE` and there is
  nothing left for a flag to suppress.
- **Nothing here is validated.** An `AGREED` parity run is an agreement about
  *code*, between two implementations of the same logic, over three hand-drawn
  charts. It is not a proof of equivalence, it says nothing about inputs outside
  the case set, and it says nothing whatever about whether any of this works on a
  market. No number in this project is a probability, a win rate or an edge, and
  `docs/algorithms/VALIDATION.md` §9 lists the four missing ingredients, the
  largest of which is a stated null. **That gap is now the largest thing left.**
- **There is no open phase.** The remaining work is validation, which is not a
  phase and cannot be done from inside this project without data.

## What to do next, in order

1. **Validation, and nothing else.** Nothing in this project has been checked
   against outcomes, and that is a larger gap than the phase count ever was. The
   prerequisites are in `docs/algorithms/VALIDATION.md` §9, and the first of them
   is a stated null. Do not begin by tuning a threshold; begin by writing down
   what would have to be true for a result to mean anything.
2. **Re-verify the port on another machine.** The sidecars are committed and the
   harness is `AGREED`, but the loop has been run on one machine with one broker
   account. `scripts/build_mql5.py` reads the account from the data folder
   rather than hard-coding it precisely so that it can be re-run elsewhere; a
   machine whose terminal folder is already writable can skip the mirror.
3. **If a case is added**, it needs a sidecar produced by a real build, the
   inventory test updated, and the docs moved in the same change. Each new
   sidecar is a new claim, and
   `test_the_mql5_directory_holds_exactly_the_sidecars_this_project_produced`
   exists to make that deliberate.

## Rebuilding the sidecars

```bat
python scripts/build_mql5.py --case parity_range_breakout_001
python -m tests.parity.runner
```

**Use the script.** Five traps are encoded in it, and two of them are *silent* —
they produce no error at all:

- **A live terminal swallows a batch run.** `terminal64.exe /config:...` against a
  data folder that already has an open instance does not start the tester: no
  error, no log line, no report. The symptom is an absent sidecar, which reads
  as a broken EA. The script therefore runs a **writable mirror** of the
  terminal rather than the installed one. A developer machine with four terminals
  open is a normal machine.
- **`C:\Program Files` is not writable without elevation**, so a `/portable` tree
  rooted at the install cannot be staged into. The mirror is a directory copy.
- The tester agent **wipes its own `MQL5/Files` on every startup**, so inputs and
  outputs go through `FILE_COMMON`.
- `Login` and `Server` must be in **both** `[Common]` and `[Tester]`.
- MetaEditor **will not compile into a portable tree** — which the mirror sidesteps
  by being an ordinary directory.

**Never hand-write a sidecar**, and never add a flag to the build script that
copies the Python reference into place. The script has no such path on purpose.

## The first disagreement, and why it is the interesting one

Porting `trade_plans`, the MQL5 side reported a `SWING` target where Python
reported `ATR_FALLBACK`, on a case whose swings make a perfect target. The
tempting fix — hand the plan layer the real swings — produced the **right number
and a broken port**, because `candidates_from_findings` never passes `swings` to
`build_trade_plan` and that fallback is therefore unreachable in the running
engine. The fix was to supply an empty list, because that is what the Python side
has.

This is the case the whole harness was built to catch, and it is worth reading
before changing anything about the port: **a port that computes the right answer
for the wrong reason is not a port.** `docs/algorithms/MT5_ADAPTER.md` §5 records
it.

## Two conventions that will surprise you in the port

- **`ported` is checked, its absence is not.** A sidecar with no `ported` key is
  treated as claiming nothing, so *every* disagreement counts against it. That is
  deliberate and slightly counter-intuitive: it means you cannot make a failing run
  pass by deleting a key. It is now the whole `SCOPE`, so the asymmetry has
  nothing left to bite on — but the check stays.
- **A count leaf is named `<group>_count` and lives at the top level**, not inside
  its group, so `setups_count` would otherwise be attributed to a group no sidecar
  declares. `partial_gate` maps it back, and there is a test saying why.

## The thing to know second: the fake was wrong and a real terminal said so

The adapter was validated against an injected fake, and **all 54 tests passed while
three live defects were present.** A real Alpari MT5 (build 6230,
`MetaTrader5` 5.0.6180) then found:

1. **`copy_rates` does not exist** in the Python bindings — only
   `copy_rates_from_pos`, `copy_rates_from`, `copy_rates_range`. The fake
   implemented it, because the MQL5 documentation names it.
2. **The payload is oldest-first**, not newest-first. The original check *refused*
   anything not newest-first — the MQL5 native convention, not the bindings' — so
   it would have raised on every real payload. The property that matters is
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

## The three things worth knowing before touching this code

- **The freeze decides by time, not by position, and on the *terminal's* clock.**
  `bar.time + period <= now`, because `Bar.time` is the *open* time. "Drop the last
  row" is wrong at every bar boundary and silently wrong across a weekend. The
  `now` must be the server clock — the local one was 3.1 hours off — and
  `FreezeReport.clock` records which was used, so a degradation is visible. The
  MQL5 port applies the same rule and then *checks* that the count it emitted
  equals the count it read.
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
  Phase 21's MQL5 port waited on MetaEditor. `test_project_status.py` used to
  assert "phases 0 through N are done", which became false the moment 22 landed.
  `COMPLETE_PHASES` is derived from `PHASES_STILL_OPEN`, and the progress sentence
  is asserted to agree with its own checkboxes — a summary that reads as truth and
  is not is the specific failure that test file exists to catch. **`PHASES_STILL_OPEN`
  is now empty**, and the empty set is asserted as a claim: no row may report
  itself as "not started".
- **A new *layer* inherits the non-repaint contract by asserting `RPC-1` for
  itself.** A detector added through the registry is covered by `RPC-7` by
  construction; a layer is not. `NON_REPAINT_CONTRACT.md` §7 has the whole rule,
  and `docs/algorithms/AI_INTERFACE.md` is the example of a layer that did it.

