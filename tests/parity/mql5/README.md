# Where the MQL5 sidecars go

An MQL5 build writes one file per parity case into this directory, named
`<case_id>.mql5.json`, in the envelope `tests/parity/contract.py` describes, with
`"producer": "mql5"`.

**This directory is empty.** No MQL5 build of this engine exists yet; Phase 21
writes the first one. Until then a parity run reports `UNVERIFIED` — not a pass,
and not a failure either, because nothing was compared.

Nothing here should be hand-written to make a run pass. A vector that was not
produced by an MQL5 build carries `"producer": "python"`, and the runner refuses
to compare it as parity evidence.
