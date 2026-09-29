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

- **The engine is finished.** Phases 0-20, 22 and 23 are complete and tested:
  bars through features, structures, context, eleven detectors, evidence, trade
  plans, a gated decision, a multi-timeframe veto, backtesting, golden fixtures,
  an MT5 adapter, an LLM-facing serialization, and a Persian documentation tree.
- **One phase remains, and it is blocked on *writing*, not on tooling.**
  Phase 21's MQL5 port is now **partly written**. This was previously recorded as
  "blocked on MetaEditor" — **that was wrong and was never checked** — and then as
  "unwritten", which was true but is no longer. The toolchain is verified working
  end to end, and `scripts/build_mql5.py` scripts the whole loop:

  ```
  python scripts/build_mql5.py --case parity_range_breakout_001
  ```

  A real MetaEditor build now produces a real sidecar, and it **agrees with Python
  on `atr`, `swings`, `bars_processed` and `last_closed_bar` with a worst
  relative deviation of `0.0`.** The other four groups — `market_state`, `setups`,
  `trade_plans`, `decision` — are not ported, so the run reports `FAILED`.
  Parity is not established, and the harness will not pretend otherwise.
- **Nothing here is validated.** No number in this project is a probability, a win
  rate or an edge. `docs/algorithms/VALIDATION.md` §9 lists the four missing
  ingredients, the largest of which is a stated null. Any change that makes this
  project sound like it has an edge is a regression, not a feature.

## What to do next, in order

1. **Phase 21, the four unported groups.** The port is **partly written** and
   measured. `Core.mqh` covers ATR and swings; `market_state`, `setups`,
   `trade_plans` and `decision` are not written, and the run honestly reports
   `FAILED` because of them. The order below is by size, smallest first:

   | Group | What it needs | Source to port |
   |---|---|---|
   | `market_state` | the classifier and its four proxy modules, plus `_largest_remainder`. The largest single chunk, and the hardest to hit to 1e-9 because `strength` is a remainder-apportioned percentage of summed raw scores. | `src/albrooks/context/market_state.py` |
   | `setups` | the eleven detectors, the registry, and the `setup_type` null convention. Watch the null: **MQL5 has no `null`**, and emitting `"NONE"` fails every case. | `src/albrooks/setups/` |
   | `trade_plans` | plan geometry, both stop bases, and `reward_to_risk`. | `src/albrooks/trade/plan.py` |
   | `decision` | the gated decision and the vetoes. | `src/albrooks/decision/` |

   The remaining two cases, `parity_trend_001` and `parity_bear_rally_001`, still
   name no sidecar. A partly filled case set can never report agreement, so they
   come after the four groups.

2. **Each new group, in this order.** Add it to the port → add its name to
   `AB_PORTED_GROUPS` in `Parity.mqh` → rebuild →
   `python -m tests.parity.runner --allow-partial`. **Removing a name from
   `ported` is the regression tripwire**: a disagreement there fails CI even with
   the flag. Do not remove a group from `ported` in order to make a run pass.

3. **The moment the last case matches**, `report.status` becomes `AGREED` and
   `test_the_shipped_state_claims_no_parity` **fails on purpose**. That failure is
   the signal: remove `--allow-partial` from `.github/workflows/ci.yml`, update
   `test_the_ci_flag_matches_the_shipped_state`, and say so in the docs in the same
   change. Do not paper over it.

4. **Then validation.** Nothing in this project has been checked against outcomes,
   and that is the largest gap — larger than the phase count.

(Phases 22 and 23 are **done**; an earlier revision of this list still listed
Phase 23 as pending, which is the kind of staleness this project otherwise tries
hard to avoid. Corrected here.)

## Rebuilding the sidecar

```bat
python scripts/build_mql5.py --case parity_range_breakout_001
python -m tests.parity.runner --allow-partial
```

**Use the script.** Three of the five traps it encodes are not obvious and each
reads as something else: the agent wipes its own `MQL5/Files` on every startup, so
inputs go through `FILE_COMMON`; MetaEditor cannot compile into a portable tree,
so the `.ex5` is compiled in the data folder and copied to the program folder; and
the agent port number is not stable (`-3000` here, where the doc recorded `-3001`).

**Never hand-write a sidecar**, and never add a flag to the build script that
copies the Python reference into place. The script has no such path on purpose.

## Two conventions that will surprise you in the port

- **`ported` is checked, its absence is not.** A sidecar with no `ported` key is
  treated as claiming nothing, so *every* disagreement counts against it. That is
  deliberate and slightly counter-intuitive: it means you cannot make a failing run
  pass by deleting a key.
- **A count leaf is named `<group>_count` and lives at the top level**, not inside
  its group, so `setups_count` would otherwise be attributed to a group no sidecar
  declares — and silently suppressed as "not yet ported". `partial_gate` maps it
  back, and there is a test saying why.

## An environment gotcha that will cost you twenty minutes if you do not know it

`git push` fails with `Host key verification failed`, and the fix is **not** to
relax host key checking. The recorded GitHub host key is correct and was verified
against the server's presented fingerprint — they match exactly, so this is a
*lookup* failure, not a security problem.

The cause is that **`HOME` is empty in this shell**, so `ssh` cannot find
`~/.ssh/`, and the `Host github.com` block in `~/.ssh/config` gives
`UserKnownHostsFile` and `IdentityFile` as **backslash** paths that Windows
`OpenSSH` does not parse. Set both explicitly, with forward slashes:

```powershell
$git="C:\Users\bagheri\AppData\Local\Programs\Git\cmd\git.exe"
$env:GIT_SSH_COMMAND="ssh -o UserKnownHostsFile=C:/Users/bagheri/.ssh/known_hosts -o IdentitiesOnly=yes -i C:/Users/bagheri/.ssh/id_ed25519"
& $git push origin main
Remove-Item Env:\GIT_SSH_COMMAND
```

Two dead ends, recorded so they are not re-tried:

- **Git's bundled `ssh`** (`...\Git\usr\bin\ssh.exe`) has **no** `known_hosts` at
  all, so pointing `GIT_SSH_COMMAND` at it fails host verification. Use the
  Windows one already on `PATH`.
- **Setting `HOME` alone is not enough.** It still fails, because the backslash
  paths in `~/.ssh/config` are the other half of the problem.

The key itself is fine: `ssh -T git@github.com` returns "Hi ybagheri!".

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
