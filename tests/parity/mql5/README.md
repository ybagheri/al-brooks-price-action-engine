# Where the MQL5 sidecars go

An MQL5 build writes one file per parity case into this directory, named
`<case_id>.mql5.json`, in the envelope `tests/parity/contract.py` describes, with
`"producer": "mql5"`.

## Status: three real sidecars, three cases, all agreeing

All three files here were produced by real MetaEditor builds that ran in the
Strategy Tester and read each case's own bars:

| File | Case | Result |
|---|---|---|
| `parity_bear_rally_001.mql5.json` | `parity_bear_rally_001` | `MATCH` |
| `parity_range_breakout_001.mql5.json` | `parity_range_breakout_001` | `MATCH` |
| `parity_trend_001.mql5.json` | `parity_trend_001` | `MATCH` |

The run reports `AGREED`, and the **worst relative deviation is `0.0`** on every
`NUMBER` leaf of every case — not merely inside the `1e-9` tolerance.

That is agreement between two implementations of the same code, over three
hand-drawn charts. It is not a proof of equivalence, it says nothing about inputs
outside the case set, and it says nothing about whether any of this works on a
market. Nothing in this project has been validated against outcomes.

Each file carries a `"ported"` list naming the groups that build implemented. It
was load-bearing while the port was partial, and it is now the whole `SCOPE` —
which is why `--allow-partial` has been removed from CI: there is no group a
disagreement can land outside of. The list stays because it is a machine-checkable
claim, and a build that quietly stopped implementing a group would be caught by
`test_the_partial_mql5_port_agrees_exactly_where_it_claims_to` rather than by
reading a version string.

## Rebuilding them

```bat
python scripts/build_mql5.py --case parity_range_breakout_001
python -m tests.parity.runner
```

The script mirrors the terminal to a writable directory, compiles, stages the
case, runs the tester, and copies the sidecar back. It has no path that copies
the Python reference here, and no flag that makes one appear.

Rebuild after changing anything under `mql5/`, and commit the new sidecars in the
same change. A stale sidecar is a claim about a build that no longer exists.

## Do not hand-write a file

Nothing here should be written by hand to make a run pass. A vector that was not
produced by an MQL5 build carries `"producer": "python"`, and the runner refuses
to compare it as parity evidence. A file that *claims* `"producer": "mql5"` would
be worse than leaving this directory empty: the harness would then be reporting
an agreement it never measured, which is the one thing it was built to prevent.
