# Python / MQL5 Parity

The specification for proving that an MQL5 build of this engine and the Python
one agree, and — more importantly — for being honest about the fact that
**nothing has been compared yet.**

Phase 20 delivers the harness: the contract, the case set, the comparison policy
and the report. Phase 21 delivers the MQL5 build that fills it. The harness
shipped first because the contract is the part that has to be right before
anyone writes a second implementation against it, and because a contract written
after the port exists is a contract shaped around whatever the port happened to
do.

## 1. What this is, and what it is not

**It is** a mechanical way to ask a closed question: given these bars and these
configuration keys, do the two implementations produce the same readings?

**It is not** a claim that the two implementations are equivalent. A harness run
over three hand-drawn charts establishes agreement on those three charts. It does
not establish general equivalence, it says nothing about inputs the case set does
not contain, and — like everything else in this project — it says nothing about
whether any of this works. A parity result is an agreement about code.

There are now **three** MQL5 sidecars in this repository, one per case, and the
run reports `AGREED`: all three cases were compared, every declared leaf agreed,
and the **worst relative deviation is `0.0`** — not merely inside the `1e-9`
tolerance, but exactly zero, on every `NUMBER` leaf.

Read that claim at the size it actually has. It is agreement about code, over
three hand-drawn charts and one declared scope. It is not a proof that the two
implementations are equivalent, it says nothing about inputs the case set does
not contain, and it says nothing whatsoever about whether any of this works on a
market. Nothing in this project has been validated against outcomes.

## 2. Why the harness shipped before the implementation

The roadmap as first written had a cycle in it: Phase 20 needed an MQL5 build to
compare against, and Phase 21 depended on Phase 20. Neither could start, and the
temptation in that situation is to write a document saying parity is planned.

The way out is to separate the two things the cycle confused:

| Phase | What it owns |
|---|---|
| **20** | The *contract*: the canonical form both sides implement, the comparison policy, the cases, and a runner that reports honestly while one side is missing. |
| **21** | The *fill*: the MQL5 build, its sidecars, and the first run that compares anything. |

The alternative — writing the MQL5 port first and the comparison second — means
writing the specification from the port's own behaviour, which is how a parity
harness ends up asserting only what both sides already agree on.

## 3. The canonical form

Two implementations cannot be compared by diffing their outputs, because they
will not have the same outputs. Python's `AnalysisResult` is a tree of dicts
built by `asdict()`; an MQL5 build is a sequence of struct writes. So both sides
reduce one closed-bar run to the same declared structure — the **parity vector** —
and the harness compares vectors.

```jsonc
{
  "schema": "albrooks-parity/1",   // the contract version; a mismatch is refused
  "case_id": "parity_trend_001",
  "producer": "mql5",              // the only value that counts as a second implementation
  "producer_version": "build 4700",
  "scope": [ "last_closed_bar", "bars_processed", "atr", "market_state",
             "swings", "setups", "trade_plans", "decision" ],
  "vector": { }
}
```

### 3.1 What is in scope, and why each field is

Every field was included by asking one question: *what would a wrong port get
wrong here?* Nothing was included because it is interesting.

| Field | Class | What a disagreement would mean |
|---|---|---|
| `last_closed_bar` | `EXACT_INT` | The two sides read different bars. MT5 series are newest-first and this engine is oldest-first, so an off-by-one is the single likeliest divergence in the whole port. |
| `bars_processed` | `EXACT_INT` | The same error, caught from the other end. **The one field in the scope that is not closed-bar stable** — see §3.2. |
| `atr` | `NUMBER` | Wilder smoothing is a recursive chain: a different seed, window, or summation order shows up here first. |
| `market_state.valid` / `.mode` / `.direction` | `EXACT_BOOL` / `EXACT_CODE` / `EXACT_INT` | The classification everything else is conditioned on. `BULL_TREND` against `TRADING_RANGE` is not rounding. |
| `market_state.strength` | `NUMBER` | The proxy share the higher-timeframe veto thresholds against, so a difference here changes decisions elsewhere. |
| `swings_count` | `EXACT_INT` | How many structures were found. |
| `swings[].bar_index` | `EXACT_INT` | Where the swing is. |
| `swings[].confirmed_bar_index` | `EXACT_INT` | **The non-repaint claim.** A port that emits the pivot bar instead of the confirming bar has broken `RPC-1`, and one-bar slop is not rounding. |
| `swings[].price` | `NUMBER` | The level itself. |
| `swings[].direction` | `EXACT_INT` | `+1` high, `-1` low. |
| `setups_count` | `EXACT_INT` | How many setups were found. |
| `setups[].detector` / `.kind` / `.setup_family` | `EXACT_CODE` | Which detector fired, and under which family — the label the whole evidence and gating chain is keyed on. |
| `setups[].direction` | `EXACT_INT` | The direction the finding claims. |
| `setups[].setup_type` | `CODE_OR_NULL` | The finding's own state. Nullable, so `CODE_OR_NULL` distinguishes "neither side had one" from "only one did". |
| `trade_plans_count` | `EXACT_INT` | How many plans exist. |
| `trade_plans[].entry` / `.stop` / `.target` | `NUMBER` | The geometry. |
| `trade_plans[].stop_basis` / `.target_basis` | `EXACT_CODE` | **Why** each level is where it is. A port that computed the right number from the wrong level is making a claim this engine does not make, and it would be invisible without these. |
| `trade_plans[].reward_to_risk` | `NUMBER` | The arithmetic between them. |
| `trade_plans[].is_valid` / `.has_structural_stop` | `EXACT_BOOL` | Whether the plan passes its own checks, and whether its stop is structural or a volatility fallback. |
| `decision.action` / `.reason` | `EXACT_CODE` | The product-level answer, and *why*. A `WAIT` for two different reasons is a real disagreement. |
| `decision.direction` / `.is_actionable` | `EXACT_INT` / `EXACT_BOOL` | The direction carried through, and whether anything was actionable at all. |

### 3.2 One field is not closed-bar stable

`bars_processed` counts the bars the run was **given**, not the bars it read, so
appending future bars to a series moves it — correctly, since the input grew.
Every other field in the scope describes the analysis and is covered by `RPC-1`.

It is left in rather than dropped, because the obligation it imposes is weaker and
easier to state precisely: an MQL5 side must be *fed the same number of bars*.
That is a checkable input condition rather than a behavioural claim, and a port
that silently truncated its series is exactly the kind of error this field exists
to catch. The test that asserts closed-bar stability therefore excludes it, by
name and with a comment saying why.

### 3.3 What is deliberately out of scope

| Excluded | Why |
|---|---|
| `explanation`, `invalidation`, `management`, `warnings`, evidence `detail` | Prose written for a human. Two implementations phrasing the same reasoning differently is not a defect; if the numbers agree, the reasoning agrees. A text diff produces noise. |
| `is_probability`, `is_recommendation` | Constant `false` on both sides by construction, so comparing them proves nothing. The Phase 19 suite asserts them here instead. |
| The `layers` map | Also constant. It distinguishes "found nothing" from "did not run" — a property of one implementation. |
| Backtest outcomes, golden expectations | Python-only concepts with no MQL5 counterpart, already owned by `docs/algorithms/BACKTESTING.md` and `docs/algorithms/VALIDATION.md`. |

### 3.4 Ordering is not part of the contract

Lists are compared as **multisets**. The harness sorts both sides by the
canonical JSON encoding of their own elements before diffing, so an MQL5 build may
emit its findings in any order — its registry is not this project's registry, and
`SETUP_ENGINE.md` §5 is explicit that registration order is not a ranking.

The cost is real and is stated rather than hidden: **a genuine ordering difference
between the two ports would not be caught.** A *count* difference would be, and
that is the difference that changes behaviour. Duplicates are preserved, so a
detector firing twice where the other fires once is a disagreement about counts.

### 3.5 A missing field is a disagreement

Both vectors are flattened to `path -> (class, value)` before comparison, and the
two maps are walked over their **union** of keys. A field the other side did not
send therefore produces a difference at a named path rather than being skipped. A
harness that compares only the fields it receives will pass an implementation of
three fields; this one will not.

A *count* difference between two lists is the case where a path exists on one side
only, and it is reported twice on purpose: at the `*_count` leaf, which is the
statement a reader wants, and at the element the shorter side does not have,
which is the evidence for it.

A leaf that is in neither `FIELD_CLASSES` nor the vector is a `VectorError`, not a
guess — in either direction. An undeclared key is refused as firmly as a missing
one, because a sidecar carrying fields the contract does not describe is
describing a different vector, and a harness that compared the parts it
recognised would report agreement over a file it did not understand. A guessed
comparison class is a comparison nobody chose.

## 4. The comparison policy

An index that differs by one is a repaint bug. A price that differs in the ninth
significant digit is a summation order. Those are different failures, so the
tolerance is per leaf rather than one epsilon for the whole vector.

| Class | Comparison |
|---|---|
| `EXACT_INT` | `==` |
| `EXACT_CODE` | `==` |
| `EXACT_BOOL` | `==`, with a `bool`/`int` type guard so `true` cannot pass as `1` |
| `CODE_OR_NULL` | Equal when both are `null`, or when both are the same string |
| `NUMBER` | Within `RELATIVE_TOLERANCE` of the reference; `ABSOLUTE_FLOOR` when the reference is within `RELATIVE_TOLERANCE` of zero |

`RELATIVE_TOLERANCE = 1e-9`, about nine significant digits. Far tighter than any
threshold in this project — the smallest gate margin is `min_pb_ratio = 0.15` — and
loose enough to absorb a different order of summation. A real logic divergence
(the wrong swing, the wrong ATR branch, a gate on the wrong side) moves a value by
a percent or by whole bars, not by the fifteenth digit.

A `NaN` or an infinity on either side is a **failure, never a match**. `nan != nan`
holds in every language, which is exactly why it has to be handled before the
comparison rather than by it.

**The worst observed deviation is reported for every case, pass or fail.** A case
that passed with a margin of 1e-15 and a case that passed with 9e-10 are both
`MATCH`, and the difference between them is the entire reason a tolerance exists.

**A tolerance is not a proof of identical arithmetic.** It is a statement about
where two implementations may legitimately differ, and it is a weak one. The
strong statement is the rest of the scope being `EXACT_INT` and `EXACT_CODE`.

## 5. The case set

Three cases, each hand-drawn, each shaped to make one class of divergence
visible. Full bar lists are in `tests/parity/cases/`.

| Case | Bars | What it is for |
|---|---|---|
| `parity_trend_001` | 34 | A rising trend with three pushes and three pullbacks. Catches series-direction and ATR-seeding errors before anything else can. |
| `parity_range_breakout_001` | 30 | Twenty bars of range whose highs deliberately recur inside every 5-bar window, then an upside break. Makes the swing tie-break load bearing: without the earliest-wins rule the two sides find different *numbers* of swings. |
| `parity_bear_rally_001` | 32 | A bear trend whose rally returns toward the origin. Catches direction-typed geometry — a short's stop and target resolved on the wrong side. |

**No case carries expected values.** A golden fixture pins what this engine
should say; a parity case supplies an input and asks two implementations to
agree. What pins this repository's behaviour is `tests/fixtures/golden/`.

## 6. The report, and the statuses it refuses to merge

| Case status | Meaning | Comparable? |
|---|---|---|
| `MATCH` | Compared; every declared leaf agreed. | yes |
| `MISMATCH` | Compared; at least one leaf did not. | yes |
| `MQL5_ABSENT` | The case names no sidecar, or the named file is not there. | no |
| `NOT_AN_MQL5_SIDECAR` | A sidecar exists but `producer` is not `mql5`. | no |
| `SCHEMA_MISMATCH` | The sidecar implements a different canonical form. | no |
| `SCOPE_REDUCED` | The sidecar covers a strict subset of `SCOPE`. | no |
| `CASE_ERROR` | The case file or the Python run is broken. | no |

The last five are not evidence of disagreement — they are evidence that the two
files do not describe the same comparison, which is a different problem for
whoever has to fix it. Folding them into `MISMATCH` would overstate what has been
learned.

Three refusals are the load-bearing part:

- **`producer` must be `mql5`.** This is what makes `tests/parity/reference/`
  safe to commit: those files are Python-produced, used to exercise the
  comparator, and the runner will not count one as a second implementation.
- **A reduced `scope` is refused.** "We agree on the three fields we implemented"
  is not parity.
- **A different `schema` is refused.** Two sides implementing different contracts
  can agree on everything they both check and still not be implementing the same
  thing.

### 6.1 The report-level status

| Status | Meaning |
|---|---|
| `UNVERIFIED` | **Nothing was compared.** Neither a pass nor a failure. |
| `AGREED` | Every case was compared and every one matched. |
| `FAILED` | Something disagreed, or a case could not be compared. |

`claims_parity` is true only for `AGREED`, which requires **every** case to have
matched. Half the case set filled in is not half a pass; it is a report only
someone who knows which half is missing can read, and a boolean cannot say that —
so a partially filled run is `FAILED`, not `AGREED`.

`UNVERIFIED` is a separate exit code (2) from `FAILED` (1) for the `RPC-18`
reason: a CI job that fails because the second implementation has not been built
yet trains people to ignore the job that matters. That is why the softening flags
existed at all, and why each was removed the moment its state stopped applying:
`--allow-unverified` covered the `UNVERIFIED` state, and `--allow-partial` covered
the `FAILED`-on-an-unported-group state. **CI now runs with no flag**, because the
shipped state is `AGREED` and there is nothing left to soften —
`AB_PORTED_GROUPS` names every group in `SCOPE`, so there is no group a
disagreement could land outside of.

`tests/unit/test_phase20_parity.py` asserts the absence of the flags and their
absence from `.github/workflows/ci.yml` stay in step, **and** that an unflagged
run over a perturbed sidecar still exits non-zero. A flag that does nothing is
worse than no flag, because a reader assumes it is load-bearing — and removing the
flags is only safe while something else is still able to fail the job.

The report carries its own `caveats`, following `BACKTESTING.md`'s precedent that a
report cannot leave without them. They are asserted to still be there on an
`AGREED` run, for the same reason: a green build must not be able to quietly stop
carrying the limits of its own claim.

## 7. Status

**3 MQL5 sidecars exist, one per case, each produced by a real MQL5 build.**
**All 3 cases have been compared, and all 3 matched.**

```text
$ python -m tests.parity.runner
parity_bear_rally_001: MATCH (worst relative deviation 0.000e+00)
parity_range_breakout_001: MATCH (worst relative deviation 0.000e+00)
parity_trend_001: MATCH (worst relative deviation 0.000e+00)

status: AGREED -- All 3 case(s) agreed on every declared field. This is
agreement on the supplied cases, not a general proof of equivalence.
```

**No claim about the market is made anywhere in this project.** An `AGREED` parity
run is an agreement between two implementations of the same code. It says nothing
about whether that code works, and nothing here has been validated against
outcomes.

## 8. What Phase 21 had to do, and what it did

**Done.** Items 1 and 2 shipped with `src/albrooks/adapters/mt5/`; the port half
of item 1 is `mql5/Include/AlBrooks/`, and item 3 is three real sidecars with
every case's `mql5_vector` set and `--allow-unverified` removed from CI. The
build loop is scripted in `scripts/build_mql5.py`, and
`docs/algorithms/MQL5_BUILD_LOOP.md` has the same list from the adapter's side.

1. ~~Write `mql5/Include/AlBrooks/` implementing `SCOPE`.~~ **Done.** The port was
   not free, and the four places the document predicted a divergence are the four
   that had to be got right: the ATR seed is Wilder's and backfilled with the
   seed rather than zero; the swing tie-break is earliest-wins, forward, on the
   right wing only; the series direction is oldest-first; and `setup_type` emits
   JSON `null` where MQL5 has no null at all.
2. Freeze the live series in the adapter. `NON_REPAINT_CONTRACT.md` §4 makes
   freezing the adapter's obligation, not the engine's, and an adapter that passes
   a forming bar produces numbers that will never agree with a Python backtest
   for reasons that have nothing to do with the port. **Done on the Python side** —
   `series.freeze_closed_bars()` decides by *time*
   (`bar.time + period <= now`, since `Bar.time` is the open time) rather than by
   position, which is wrong at every bar boundary and silently wrong across a
   session break; see `docs/algorithms/MT5_ADAPTER.md` §3. The MQL5 side owes the
   same obligation, and `ParityExporter.mq5` pays it: it applies the same rule and
   then *checks* that the count it emits equals the count it read, so a silent
   truncation cannot defeat the field that exists to catch one.
3. ~~Write one sidecar per case into `tests/parity/mql5/`, set each case's
   `mql5_vector`, and remove `--allow-unverified` from CI.~~ **Done.**
4. ~~Report the disagreements that appear.~~ **Done, and the first one is worth
   recording**, because it is the argument for the whole harness.

   A port whose first recorded result is a pass should be checked for having
   compared nothing. This one was checked by starting **partial**: only `atr` and
   `swings` were declared in `AB_PORTED_GROUPS`, so every run was visibly
   `FAILED` and the unported groups could be seen disagreeing. Each group was then
   added one at a time, and the run had to go `MATCH` for that group specifically
   before the next was started.

   The first real disagreement came from porting `trade_plans`: the MQL5 side
   reported a `SWING` target where Python reported `ATR_FALLBACK`, on a case whose
   swings make a perfect target. Passing the real swings "fixed" the number and
   **broke the port** — because `candidates_from_findings` does not pass `swings`
   to `build_trade_plan` at all, so the swing fallback is unreachable in the
   running engine. The fix was to supply an empty list, because that is what the
   Python side has. Tuning the number until it agreed would have produced a port
   that computes the right answer for the wrong reason.

   **A hand-written `"producer": "mql5"` file would be worse than no MQL5 code at
   all**, because the harness would then be reporting an agreement it never
   measured. `scripts/build_mql5.py` has no path that copies the Python reference
   and no flag that would make one appear, and that is deliberate.

## 9. Source

`tests/parity/contract.py` — the canonical form, the scope, the tolerance
`tests/parity/compare.py` — the comparison and its difference vocabulary
`tests/parity/runner.py` — the case runner, the report and the command line
`tests/parity/cases/` — the three cases
`tests/parity/mql5/` — the three sidecars, each from a real MQL5 build
`mql5/Include/AlBrooks/` — the port itself
`scripts/build_mql5.py` — the compile, run and read-back loop
`tests/unit/test_phase20_parity.py` — the suite, including the assertions that
keep this document honest
`docs/algorithms/NON_REPAINT_CONTRACT.md` — `RPC-1`, `RPC-14`, `RPC-15`
`docs/algorithms/VALIDATION.md` — what parity is not
