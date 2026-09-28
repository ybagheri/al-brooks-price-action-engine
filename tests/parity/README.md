# Parity harness

The Python / MQL5 parity contract, the case set, and the runner.
`docs/PYTHON_MQL5_PARITY.md` is the specification and the argument for why the
harness is built this way; this file is the practical guide.

## Status: the harness ships, unfilled

**No MQL5 sidecar exists.** `mql5/` is empty, every case names `null`, and a run
reports `UNVERIFIED` with the claim *"nothing about parity has been established"*.
That is the honest state of Phase 20 and it is asserted by
`tests/unit/test_phase20_parity.py`, so the day a sidecar appears the suite says
so rather than going quiet.

Phase 21 owns the MQL5 build. The roadmap had it depending on this harness and
this harness depending on that build, which is a cycle; the way out was to make
Phase 20 the *contract* and Phase 21 the *fill*, and to say so in the
documentation rather than shipping a parity claim with nothing behind it.

## Layout

| Path | What it is |
|---|---|
| `contract.py` | The canonical form: `SCOPE`, `FIELD_CLASSES`, the tolerance, and the flattening that makes a missing field detectable |
| `compare.py` | Field-by-field comparison, reporting every difference with a path |
| `runner.py` | Case loading, the report, and the command line |
| `cases/*.json` | The bar series, hand-drawn, with the disagreement each is designed to catch |
| `mql5/` | Where Phase 21's sidecars go. **Empty.** |
| `reference/` | This repository's own vectors, `producer: "python"`. Not parity evidence. |

## Running it

```bash
python -m tests.parity.runner                    # exit 2 while nothing is comparable
python -m tests.parity.runner --allow-unverified # exit 0; CI uses this until Phase 21
python -m tests.parity.runner --json             # the report as JSON
```

| Exit | Meaning |
|---|---|
| 0 | `AGREED` — every case compared and matched |
| 1 | `FAILED` — something disagreed, or a case could not be compared |
| 2 | `UNVERIFIED` — nothing was compared |

`UNVERIFIED` is a separate code from `FAILED` on purpose. A CI job that treats
"the second implementation has not been built yet" as a test failure trains people
to ignore the failure that matters.

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
  "mql5_vector": null      // "parity_trend_001.mql5.json" once Phase 21 supplies one
}
```

There are **no expected values**, and that is the difference from
`tests/fixtures/golden/`. A golden fixture pins what this engine *should* say; a
parity case only supplies an input and asks two implementations to agree. What
pins this repository's behaviour is the golden suite.

## Adding an MQL5 sidecar

Write `mql5/<case_id>.mql5.json` in the envelope `contract.dump()` produces, with
`"producer": "mql5"` and `"producer_version"` naming the build. Set the case's
`mql5_vector` to the filename.

The runner will refuse a sidecar that is not from an MQL5 build
(`NOT_AN_MQL5_SIDECAR`), one written against a different schema
(`SCHEMA_MISMATCH`), and one that covers less than the full `SCOPE`
(`SCOPE_REDUCED`). Those three refusals are the reason `reference/` is safe to
commit: a Python-produced vector cannot be counted as a second implementation.

## `reference/` is not a regression baseline

`--write-reference` regenerates those files, which the golden fixtures
deliberately forbid. The difference: a golden expectation is a claim about what
is *right*, and automating it removes the only part worth having; a reference
vector is a claim about what this code currently prints, used to exercise the
comparator, and every file it writes declares `producer: "python"`.

So: `tests/parity/` pins no values, and `tests/fixtures/golden/` remains the
regression suite.
