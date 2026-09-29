# Parity harness

The Python / MQL5 parity contract, the case set, and the runner.
`docs/PYTHON_MQL5_PARITY.md` is the specification and the argument for why the
harness is built this way; this file is the practical guide.

## Status: three real sidecars, and they agree

**All three cases are compared and all three match.** Each has an MQL5-produced
sidecar, every declared leaf agrees, and the **worst relative deviation is `0.0`** —
not merely inside the `1e-9` tolerance, but exactly zero.

```text
parity_bear_rally_001: MATCH (worst relative deviation 0.000e+00)
parity_range_breakout_001: MATCH (worst relative deviation 0.000e+00)
parity_trend_001: MATCH (worst relative deviation 0.000e+00)
status: AGREED
```

That status, the sidecar count and the compared-case count are all asserted by
`tests/unit/test_phase20_parity.py` **against the run itself**, so a document or a
test that drifts from reality fails rather than reading as true.

Read the claim at the size it has. It is agreement between two implementations of
the same code, over three hand-drawn charts and one declared scope. It is not a
proof of equivalence, it says nothing about inputs outside the case set, and it
says nothing about whether any of this works on a market. Nothing in this project
has been validated against outcomes.

The port got there by starting **partial**: only `atr` and `swings` were declared
in `AB_PORTED_GROUPS`, so every run was visibly `FAILED` and the unported groups
could be seen disagreeing. Each group was then added one at a time, and the run
had to go `MATCH` for that group before the next was started. `--allow-partial`
existed to keep that honest rather than red, and is now gone: there is no group a
disagreement can land outside of, so CI runs the harness with no flag at all.

The roadmap had the MQL5 build depending on this harness and this harness
depending on that build, which is a cycle; the way out was to make Phase 20 the
*contract* and Phase 21 the *fill*.

## Layout

| Path | What it is |
|---|---|
| `contract.py` | The canonical form: `SCOPE`, `FIELD_CLASSES`, the tolerance, and the flattening that makes a missing field detectable |
| `compare.py` | Field-by-field comparison, reporting every difference with a path |
| `runner.py` | Case loading, the report, and the command line |
| `cases/*.json` | The bar series, hand-drawn, with the disagreement each is designed to catch |
| `mql5/*.mql5.json` | Three sidecars, each produced by a real MQL5 build. **Never hand-written.** |
| `reference/` | This repository's own vectors, `producer: "python"`. Not parity evidence. |

## Running it

```bash
python -m tests.parity.runner         # exit 0 when AGREED, exit 1 on any disagreement
python -m tests.parity.runner --json  # the report as JSON
```

| Exit | Meaning |
|---|---|
| 0 | `AGREED` — every case compared and matched |
| 1 | `FAILED` — something disagreed, or a case could not be compared |
| 2 | `UNVERIFIED` — nothing was compared |

`UNVERIFIED` is a separate code from `FAILED` on purpose. A CI job that treats
"the second implementation has not been built yet" as a test failure trains people
to ignore the failure that matters. The two softening flags that once existed
(`--allow-unverified`, then `--allow-partial`) were each removed in the same change
that removed the state they covered, and a test asserts both their absence and
that an unflagged run over a perturbed sidecar still exits non-zero.

## Adding a case

Add `cases/<id>.json`, with a real `intent`. An intent is not a label: it says
which divergence the bars are shaped to expose, so that when the MQL5 side
disagrees, whoever reads the failure knows what the case was *for*.

```jsonc
{
  "id": "parity_trend_001",
  "intent": "which divergence these bars are designed to catch",
  "spec": "docs/algorithms/H1_H2_L1_L2.md",
  "chart": [ "0..3  first push, 100.0 -> 102.5" ],
  "config": {},            // only keys that differ from the defaults; the key must exist
  "last_closed": 33,
  "bars": [ { "i": 0, "time": 1700000000, "o": …, "h": …, "l": …, "c": … } ],
  "mql5_vector": "parity_trend_001.mql5.json"   // null until a real build supplies one
}
```

Landing a new sidecar means updating `test_the_mql5_directory_holds_exactly_the_
sidecars_this_project_produced`, which pins the inventory, and the docs, in the
same change. Each new sidecar is a new claim.

There are **no expected values**, and that is the difference from
`tests/fixtures/golden/`. A golden fixture pins what this engine *should* say; a
parity case only supplies an input and asks two implementations to agree. What
pins this repository's behaviour is the golden suite.

## Adding an MQL5 sidecar

**Do not write one.** Produce it:

```bash
python scripts/build_mql5.py --case <case_id>
python -m tests.parity.runner
```

The script has no path that copies the Python reference into place and no flag
that would make one appear. That is the point: a file in `mql5/` that the script
did not produce is a fabrication, and it would be worse than having no MQL5 code
at all, because the harness would then be reporting an agreement it never
measured. `docs/algorithms/MQL5_BUILD_LOOP.md` has the loop's traps.

The runner will refuse a sidecar that is not from an MQL5 build
(`NOT_AN_MQL5_SIDECAR`), one written against a different schema
(`SCHEMA_MISMATCH`), one for a different case (`CASE_ERROR`), one whose
`mql5_vector` escapes the vectors directory (`CASE_ERROR`), and one that covers
less than the full `SCOPE` (`SCOPE_REDUCED`). Those refusals are the reason
`reference/` is safe to commit: a Python-produced vector cannot be counted as a
second implementation.

## `reference/` is not a regression baseline

`--write-reference` regenerates those files, which the golden fixtures
deliberately forbid. The difference: a golden expectation is a claim about what
is *right*, and automating it removes the only part worth having; a reference
vector is a claim about what this code currently prints, used to exercise the
comparator, and every file it writes declares `producer: "python"`.

So: `tests/parity/` pins no values, and `tests/fixtures/golden/` remains the
regression suite.
