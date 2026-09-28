# Handoff — Phase 20

A point-in-time note for whoever picks this up next. **If this file disagrees with
`ROADMAP.md`, `ROADMAP.md` is right**, and this file should be deleted rather than
patched. It is not a phase deliverable and no test reads it.

Last commit: `feat(parity): add the Python/MQL5 parity contract and harness (Phase 20)`.
Full suite: 640 tests, `ruff` and `mypy` clean, both `scripts/` checks passing.

## What shipped

Phase 20 built the **contract** an MQL5 port would be compared against. It
compared nothing, and says so.

| Piece | What it is |
|---|---|
| `tests/parity/contract.py` | The canonical vector: `SCOPE` (8 groups), `FIELD_CLASSES` (33 leaves), the per-leaf comparison class, the tolerance, and the flattening that makes a missing field detectable |
| `tests/parity/compare.py` | Field-by-field comparison, every difference reported with a path and both values |
| `tests/parity/runner.py` | Case loading, the report, the seven case statuses, and the command line |
| `tests/parity/cases/` | Three hand-drawn cases, each naming the divergence it exists to catch |
| `tests/parity/mql5/` | Where the first sidecar goes. **Empty.** |
| `tests/parity/reference/` | Python-produced vectors, used to exercise the comparator. **Not parity evidence.** |
| `docs/PYTHON_MQL5_PARITY.md` | The specification, and what Phase 21 owes |
| `tests/unit/test_phase20_parity.py` | 57 tests |

## The state a reader must not misread

- **No MQL5 build of this engine has been written.** Zero of three cases have been
  compared and **no parity claim is made anywhere in this project**.
- A run today reports `UNVERIFIED` — a status distinct from both a pass and a
  failure, because no comparison happened:

  ```bash
  python -m tests.parity.runner
  ```

- The harness is built so this state cannot be mistaken for a result. A sidecar
  whose `producer` is not `mql5` is not counted at all, which is what makes the
  committed Python-produced vectors safe to keep. A sidecar covering a strict
  subset of the scope is refused. A sidecar written against another schema is
  refused. `AGREED` requires **every** case to have been compared, so a
  half-filled run is `FAILED` rather than a pass a boolean cannot qualify.

## Why the phase was split

The roadmap had a cycle: Phase 20 needed an MQL5 build to compare against, and
Phase 21 depended on Phase 20. Neither could start. Phase 20 therefore owns the
*contract* and Phase 21 owns the *fill*. The alternative — port first, comparison
second — means writing the specification from the port's own behaviour, which is
how a parity harness ends up asserting only what both sides already agree on.

## The next step

**Phase 21 — MT5 Adapter & MQL5 Layer.** `src/albrooks/adapters/mt5/` and
`mql5/Include/AlBrooks/`, per `docs/PYTHON_MQL5_PARITY.md` §8. In order:

1. Implement the scope in MQL5. The four places a port most easily diverges, and
   the reason each is in scope, are the **ATR seed**, the **swing tie-break**, the
   **`BarSeries` direction** (MT5 is newest-first, this engine oldest-first), and
   the **null convention**.
2. Freeze the live series in the adapter. `NON_REPAINT_CONTRACT.md` §4 makes that
   the adapter's obligation; an adapter that passes a forming bar will never agree
   with a Python backtest, for reasons that have nothing to do with the port.
3. Write one sidecar per case into `tests/parity/mql5/`, set each case's
   `mql5_vector`, and remove `--allow-unverified` from `.github/workflows/ci.yml`.
   A test links the two: it fails if the flag is still there once the first real
   sidecar lands.
4. **Record the disagreements the first run produces.** The expectation is that it
   fails. A harness whose first recorded result is a clean pass should be checked
   for having compared nothing.

Phase 21 also closes a finding Phase 19 recorded rather than fixed: the fade
lifecycle is unreachable through the pipeline, because `track_fading_measured_moves`
is never called by the engine. Giving a stateless detector a stateful
responsibility belongs with a stateful caller, which is the adapter.

After that: **Phase 22** (AI/LLM interface, owed
`src/albrooks/serialization/json.py`, `examples/llm_analysis.py` and
`docs/algorithms/AI_INTERFACE.md`) and **Phase 23** (bilingual documentation,
which owes no new code path).

## Two things worth knowing before touching this code

- **`bars_processed` is the one field in scope that is not closed-bar stable.** It
  counts the bars the run was given, so appending future bars moves it. It is
  deliberately in the scope anyway: the obligation it imposes is an input
  condition rather than a behavioural claim, and a port that silently truncated
  its series is exactly what it exists to catch. The closed-bar test excludes it
  by name.
- **`--write-reference` exists here and is forbidden for golden fixtures.** A
  golden expectation is a claim about what is *right*, and automating it removes
  the only part worth having. A reference vector is a claim about what this code
  currently prints, and every file it writes declares `producer: "python"`.
  `tests/parity/` pins no values; `tests/fixtures/golden/` is the regression suite.
