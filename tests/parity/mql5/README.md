# Where the MQL5 sidecars go

An MQL5 build writes one file per parity case into this directory, named
`<case_id>.mql5.json`, in the envelope `tests/parity/contract.py` describes, with
`"producer": "mql5"`.

## Status: one real sidecar, one case, disagreeing

`parity_range_breakout_001.mql5.json` is here, produced by a real MetaEditor
build that ran in the Strategy Tester and read that case's own bars. It is
compared, and it **disagrees** — on `market_state`, `setups`, `trade_plans` and
`decision`, which the port has not written yet. On `atr`, `swings`,
`bars_processed` and `last_closed_bar` it agrees with Python at a worst relative
deviation of **0.0**.

Parity is therefore **not** established, and the run reports `FAILED`.

Each file carries a `"ported"` list naming the groups that build actually
implemented. `--allow-partial` uses it to suppress a disagreement only outside
those groups, so an unfinished port is distinguishable from a broken one. A
disagreement *inside* a declared group still fails, and a file with no `ported`
key is treated as claiming nothing, so deleting the key is not a way to switch
the gate off.

The other two cases still name no sidecar, and a case set that is only partly
filled can never report agreement.

## Rebuilding it

```bat
python scripts/build_mql5.py --case parity_range_breakout_001
python -m tests.parity.runner --allow-partial
```

The script compiles, deploys, stages the case, runs the tester, and copies the
sidecar back. It has no path that copies the Python reference here, and no flag
that makes one appear.

## Do not hand-write a file

Nothing here should be written by hand to make a run pass. A vector that was not
produced by an MQL5 build carries `"producer": "python"`, and the runner refuses
to compare it as parity evidence. A file that *claims* `"producer": "mql5"` would
be worse than leaving this directory empty: the harness would then be reporting
an agreement it never measured, which is the one thing it was built to prevent.
