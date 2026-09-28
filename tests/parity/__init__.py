"""The Python / MQL5 parity harness (Phase 20).

This package exists because two implementations of the same engine are worth
nothing unless there is a mechanical way to ask whether they agree. It is the
*harness* — the case set, the canonical form both sides must produce, the
comparison policy, and the report — and it ships **with no MQL5 side filled in**.

`docs/PYTHON_MQL5_PARITY.md` is the specification; `README.md` in this directory
describes the case-file schema. The short version of why an unfilled harness is
still the right thing to ship: the alternative is a claim of parity with nothing
behind it, which is the one failure mode this project is built to avoid.

The `src` path is inserted here rather than in the CLI alone because
`contract.py` imports `albrooks` at module import time, and the package is
imported first. This mirrors `tests/conftest.py`, which does the same for pytest.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
