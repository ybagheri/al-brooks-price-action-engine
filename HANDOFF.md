# Handoff — Phase 21 (partial)

A point-in-time note for whoever picks this up next. **If this file disagrees with
`ROADMAP.md`, `ROADMAP.md` is right**, and this file should be deleted rather than
patched. It is not a phase deliverable and no test reads it.

Full suite: 700 tests, `ruff` and `mypy` clean, both `scripts/` checks passing.

## The thing to know first: the fake was wrong and a real terminal said so

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
54 tests. The two obligations `NON_REPAINT_CONTRACT.md` §4 assigns to an adapter,
plus the stateful caller Phase 19 deferred to.

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
  mis-ordered payload would hide the caller's bug behind a working result, which is
  the failure this whole layer exists to prevent — but *refusing a legitimate
  convention* is the same mistake pointed the other way.
- **The session re-derives; it does not accumulate.** The obvious implementation of
  an `AnalysisSession` — keep the fade setups in `self`, advance one bar per call —
  would break `RPC-1`. A session that has seen bars 21..40 and then answers for bar
  20 holds state derived from bars the caller declared unavailable. So
  `track_fading_measured_moves` is re-run on the frozen window every call, and the
  only state kept is the previous result. The test analyses the *longer* series
  first, so a stateful implementation would have to leak deliberately to pass.
- **The pipeline still reports `PROJECTED` for a fade, deliberately.** The registry
  is stateless and that is its contract. The session adds a caller rather than
  editing the registry, and `SessionResult.fade_source` says which reading is
  which. A test asserts **both** readings, so the change cannot quietly become
  "the pipeline now says something else".

## The next steps, in order

1. **Phase 21, completed** — on a machine with MetaEditor. Implement `SCOPE` in
   MQL5; the four places a port most easily diverges are the **ATR seed**, the
   **swing tie-break**, the **`BarSeries` direction** and the **null convention**.
   The live-terminal run above is the argument for doing this *against* a real
   terminal rather than by inspection: three defects survived 54 green tests, and an
   MQL5 port validated only by reading would carry the same class of error at ten
   times the size.
   Write one sidecar per case into `tests/parity/mql5/`, set each case's
   `mql5_vector`, and remove `--allow-unverified` from `.github/workflows/ci.yml`.
   **Record the disagreements the first run produces** — the expectation is that it
   fails, and a harness whose first recorded result is a clean pass should be
   checked for having compared nothing.
2. **Phase 22** — `src/albrooks/serialization/json.py`, `examples/llm_analysis.py`
   and `docs/algorithms/AI_INTERFACE.md`. Needs no external tooling.
3. **Phase 23** — bilingual documentation, which owes no new code path.
